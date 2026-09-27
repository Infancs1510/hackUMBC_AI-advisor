"""Advising appointments: slot generation and a small SQLite store.

Appointments are data the app creates, so they live in their own database rather than in the
read-only HackUMBC CSVs. A partial unique index makes double-booking a slot impossible.
"""

import json
import sqlite3
from contextlib import closing
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from app.data.loader import DataStore
from app.models.appointments import (
    REASON_LABELS,
    AdvisingBrief,
    Appointment,
    ScheduleAppointment,
    ScheduleDay,
    ScheduleRules,
    ScheduleSlot,
    ScheduleSummary,
    Slot,
    SlotDay,
    SlotsResponse,
    WeekSchedule,
)
from app.services.career_matching import CareerProfile
from app.services.dashboard import build_dashboard
from app.services.degree_audit import build_degree_audit

DURATION = timedelta(minutes=30)
# Weekly advising hours (Mon=0 … Fri=4): 30-minute slots starting at these times.
SLOT_TIMES = [time(10, 0), time(10, 30), time(11, 0), time(13, 30), time(14, 0), time(15, 0)]
BOOKING_WINDOW_WEEKDAYS = 10  # two working weeks, starting tomorrow
MIN_NOTICE = timedelta(hours=2)

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    modality TEXT NOT NULL,
    start TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'booked',
    created_at TEXT NOT NULL,
    brief TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_booking_per_slot ON appointments(start) WHERE status = 'booked';
CREATE TABLE IF NOT EXISTS session_notes (
    appointment_id INTEGER PRIMARY KEY,
    note TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class AppointmentError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


def _time_label(t: time) -> str:
    return datetime.combine(date.today(), t).strftime("%I:%M %p").lstrip("0")


class AppointmentService:
    def __init__(self, db_path: Path, advisor_name: str, timezone: str):
        self.db_path = Path(db_path)
        self.advisor = advisor_name
        self.tz = ZoneInfo(timezone)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # --- slots -----------------------------------------------------------------------

    def _schedule(self, now: datetime) -> list[datetime]:
        starts, day = [], now.date()
        while len({s.date() for s in starts}) < BOOKING_WINDOW_WEEKDAYS:
            day += timedelta(days=1)
            if day.weekday() < 5:
                starts += [datetime.combine(day, t, tzinfo=self.tz) for t in SLOT_TIMES]
        return starts

    def _booked_starts(self) -> set[str]:
        with closing(self._connect()) as conn:
            return {r["start"] for r in conn.execute("SELECT start FROM appointments WHERE status = 'booked'")}

    def slots(self, now: datetime | None = None) -> SlotsResponse:
        now = now or self.now()
        booked = self._booked_starts()
        days: dict[date, SlotDay] = {}
        for start in self._schedule(now):
            day = days.setdefault(start.date(), SlotDay(
                date=start.date().isoformat(), weekday=start.strftime("%a"), label=f"{start:%b} {start.day}", slots=[],
            ))
            day.slots.append(Slot(
                start=start, label=_time_label(start.time()),
                available=start.isoformat() not in booked and start - now >= MIN_NOTICE,
            ))
        return SlotsResponse(
            advisor=self.advisor, timezone=str(self.tz), duration_minutes=int(DURATION.total_seconds() // 60),
            days=list(days.values()),
        )

    def _validate_slot(self, start: datetime, now: datetime) -> datetime:
        if start.tzinfo is None:
            start = start.replace(tzinfo=self.tz)
        start = start.astimezone(self.tz)
        if start not in self._schedule(now):
            raise AppointmentError("That time isn't one of the advising slots.")
        if start - now < MIN_NOTICE:
            raise AppointmentError("Appointments need at least 2 hours' notice.")
        return start

    # --- records ---------------------------------------------------------------------

    def _to_model(self, row: sqlite3.Row) -> Appointment:
        start = datetime.fromisoformat(row["start"])
        return Appointment(
            id=row["id"], campus_id=row["campus_id"], advisor=self.advisor,
            reason=row["reason"], reason_label=REASON_LABELS[row["reason"]], modality=row["modality"],
            start=start, end=start + DURATION, notes=row["notes"], status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]), brief=AdvisingBrief(**json.loads(row["brief"])),
        )

    def get(self, appointment_id: int) -> Appointment:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        if row is None:
            raise AppointmentError("Appointment not found.", 404)
        return self._to_model(row)

    def list_for(self, campus_id: str | None = None, upcoming_only: bool = True, now: datetime | None = None) -> list[Appointment]:
        now = now or self.now()
        query, params = "SELECT * FROM appointments WHERE 1=1", []
        if campus_id:
            query += " AND campus_id = ?"
            params.append(campus_id)
        with closing(self._connect()) as conn:
            rows = conn.execute(query + " ORDER BY start", params).fetchall()
        items = [self._to_model(r) for r in rows]
        if upcoming_only:
            items = [a for a in items if a.status == "booked" and a.end > now]
        return items

    def book(
        self, campus_id: str, reason: str, modality: str, start: datetime, notes: str,
        brief: AdvisingBrief, now: datetime | None = None,
    ) -> Appointment:
        now = now or self.now()
        start = self._validate_slot(start, now)
        if self.list_for(campus_id, upcoming_only=True, now=now):
            raise AppointmentError("You already have an upcoming appointment — reschedule it instead.", 409)
        try:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    "INSERT INTO appointments (campus_id, reason, modality, start, notes, created_at, brief) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (campus_id, reason, modality, start.isoformat(), notes.strip(), now.isoformat(), brief.model_dump_json()),
                )
                new_id = cur.lastrowid
        except sqlite3.IntegrityError as exc:
            raise AppointmentError("That slot was just taken — please pick another.", 409) from exc
        return self.get(new_id)

    def update(
        self, appointment: Appointment, start: datetime | None, modality: str | None, notes: str | None,
        now: datetime | None = None,
    ) -> Appointment:
        now = now or self.now()
        if appointment.status != "booked" or appointment.end <= now:
            raise AppointmentError("Only upcoming appointments can be changed.", 409)
        fields, params = [], []
        if start is not None:
            fields.append("start = ?")
            params.append(self._validate_slot(start, now).isoformat())
        if modality is not None:
            fields.append("modality = ?")
            params.append(modality)
        if notes is not None:
            fields.append("notes = ?")
            params.append(notes.strip())
        if fields:
            try:
                with closing(self._connect()) as conn, conn:
                    conn.execute(f"UPDATE appointments SET {', '.join(fields)} WHERE id = ?", (*params, appointment.id))
            except sqlite3.IntegrityError as exc:
                raise AppointmentError("That slot was just taken — please pick another.", 409) from exc
        return self.get(appointment.id)

    def complete(self, appointment: Appointment) -> Appointment:
        if appointment.status != "booked":
            raise AppointmentError("Only booked appointments can be marked completed.", 409)
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE appointments SET status = 'completed' WHERE id = ?", (appointment.id,))
        return self.get(appointment.id)

    def mark_no_show(self, appointment: Appointment, now: datetime | None = None) -> Appointment:
        now = now or self.now()
        if appointment.status != "booked":
            raise AppointmentError("Only booked appointments can be marked as a no-show.", 409)
        if appointment.start > now:
            raise AppointmentError("An appointment can't be a no-show before it starts.", 409)
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE appointments SET status = 'no_show' WHERE id = ?", (appointment.id,))
        return self.get(appointment.id)

    # --- advisor session notes (never returned to students) ------------------------------

    def set_session_note(self, appointment: Appointment, note: str) -> str:
        note = note.strip()
        with closing(self._connect()) as conn, conn:
            if note:
                conn.execute(
                    "INSERT OR REPLACE INTO session_notes (appointment_id, note, updated_at) VALUES (?, ?, ?)",
                    (appointment.id, note, datetime.now(timezone.utc).isoformat()),
                )
            else:
                conn.execute("DELETE FROM session_notes WHERE appointment_id = ?", (appointment.id,))
        return note

    def _session_notes(self) -> dict[int, str]:
        with closing(self._connect()) as conn:
            return {r["appointment_id"]: r["note"] for r in conn.execute("SELECT * FROM session_notes")}

    # --- advisor week view ---------------------------------------------------------------

    def week(self, week_of: date | None = None, now: datetime | None = None) -> WeekSchedule:
        """Monday–Friday advising slots for one week, with each slot's appointment and state."""
        now = now or self.now()
        if week_of is None:  # on a weekend, "this week" means the coming one
            week_of = now.date() + timedelta(days=2 if now.weekday() >= 5 else 0)
        monday = week_of - timedelta(days=week_of.weekday())
        booking_window = set(self._schedule(now))
        notes = self._session_notes()
        by_start: dict[str, list[Appointment]] = {}
        for a in self.list_for(None, upcoming_only=False, now=now):
            by_start.setdefault(a.start.isoformat(), []).append(a)

        def detail(a: Appointment) -> ScheduleAppointment:
            return ScheduleAppointment(**a.model_dump(), session_note=notes.get(a.id, ""))

        days, counts, reasons, modalities = [], Counter(), Counter(), Counter()
        for offset in range(5):
            day = monday + timedelta(days=offset)
            slots, cancelled = [], []
            for t in SLOT_TIMES:
                start = datetime.combine(day, t, tzinfo=self.tz)
                items = by_start.get(start.isoformat(), [])
                cancelled += [detail(a) for a in items if a.status == "cancelled"]
                # A slot can hold one booking plus older finished ones (e.g. completed early); show the booking.
                active = next((a for a in items if a.status == "booked"), None) or next(
                    (a for a in items if a.status != "cancelled"), None
                )
                if active:
                    state = active.status
                    reasons[active.reason] += 1
                    modalities[active.modality] += 1
                else:
                    state = "open" if start in booking_window and start - now >= MIN_NOTICE else "closed"
                counts[state] += 1
                slots.append(ScheduleSlot(
                    start=start, label=_time_label(t), state=state, appointment=detail(active) if active else None,
                ))
            counts["cancelled"] += len(cancelled)
            days.append(ScheduleDay(
                date=day.isoformat(), weekday=f"{day:%a}", label=f"{day:%b} {day.day}", is_today=day == now.date(),
                slots=slots, cancelled=cancelled,
            ))
        friday = monday + timedelta(days=4)
        return WeekSchedule(
            advisor=self.advisor, timezone=str(self.tz), week_start=monday.isoformat(),
            week_label=f"{monday:%b} {monday.day} – {friday:%b} {friday.day}, {friday.year}",
            today=now.date().isoformat(), now=now, days=days,
            summary=ScheduleSummary(
                slots=5 * len(SLOT_TIMES), booked=counts["booked"], completed=counts["completed"],
                no_show=counts["no_show"], cancelled=counts["cancelled"], open=counts["open"],
                by_reason={REASON_LABELS[k]: v for k, v in reasons.most_common()}, by_modality=dict(modalities),
            ),
            rules=ScheduleRules(
                slot_times=[_time_label(t) for t in SLOT_TIMES], duration_minutes=int(DURATION.total_seconds() // 60),
                min_notice_hours=int(MIN_NOTICE.total_seconds() // 3600), booking_window_weekdays=BOOKING_WINDOW_WEEKDAYS,
                modalities=["In person", "Virtual"],
            ),
        )

    def cancel(self, appointment: Appointment) -> Appointment:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appointment.id,))
        return self.get(appointment.id)


def build_brief(
    store: DataStore, profiles: dict[str, CareerProfile], campus_id: str, saved_goal: str | None
) -> AdvisingBrief:
    dashboard = build_dashboard(store, profiles, campus_id)
    audit = build_degree_audit(store, campus_id)
    s = dashboard.student
    top = dashboard.career_matches[0] if dashboard.career_matches else None
    return AdvisingBrief(
        major=s.major, track=s.track, class_level=s.class_level, gpa=s.gpa,
        credits_earned=s.credits_earned, credits_required=s.credits_required,
        academic_standing=s.academic_standing, expected_graduation_term=s.expected_graduation_term,
        remaining_required_courses=[c.course_id for c in audit.remaining_required_courses],
        top_career=top.career if top and top.score > 0 else None,
        top_career_score=top.score if top and top.score > 0 else None,
        saved_goal=saved_goal,
    )
