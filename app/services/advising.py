"""Advisor workflow data the app creates: review notes and meeting requests (SQLite, like appointments)."""

import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.data.loader import DataStore
from app.data.parsing import NEXT_TERM
from app.models.advising import (
    AdvisorDashboard,
    CourseDemand,
    MeetingRequest,
    NameCount,
    Review,
    RisingCareer,
    TrackCount,
)
from app.models.appointments import REASON_LABELS, Appointment
from app.services.caseload import FLAGS, Caseload
from app.services.market import market_career_shifts

TOP_COURSE_DEMAND = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    campus_id TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meeting_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);
"""


class AdvisingError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


class AdvisingStore:
    def __init__(self, db_path: Path, advisor_name: str):
        self.db_path = Path(db_path)
        self.advisor = advisor_name
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- reviews -----------------------------------------------------------------------

    def set_review(self, campus_id: str, note: str) -> Review:
        now = datetime.now(timezone.utc)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO reviews (campus_id, note, reviewed_at) VALUES (?, ?, ?)",
                (campus_id, note.strip(), now.isoformat()),
            )
        return Review(campus_id=campus_id, reviewed_at=now, note=note.strip())

    def clear_review(self, campus_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM reviews WHERE campus_id = ?", (campus_id,))

    def reviews(self) -> dict[str, tuple[datetime, str]]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM reviews").fetchall()
        return {r["campus_id"]: (datetime.fromisoformat(r["reviewed_at"]), r["note"]) for r in rows}

    # --- meeting requests --------------------------------------------------------------

    def _request(self, row: sqlite3.Row) -> MeetingRequest:
        return MeetingRequest(
            id=row["id"], campus_id=row["campus_id"], advisor=self.advisor, reason=row["reason"],
            reason_label=REASON_LABELS[row["reason"]], message=row["message"], status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def create_request(self, campus_id: str, reason: str, message: str) -> MeetingRequest:
        if self.requests(campus_id):
            raise AdvisingError("This student already has an open meeting request.", 409)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO meeting_requests (campus_id, reason, message, created_at) VALUES (?, ?, ?, ?)",
                (campus_id, reason, message.strip(), datetime.now(timezone.utc).isoformat()),
            )
            row = conn.execute("SELECT * FROM meeting_requests WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._request(row)

    def requests(self, campus_id: str | None = None, open_only: bool = True) -> list[MeetingRequest]:
        query, params = "SELECT * FROM meeting_requests WHERE 1=1", []
        if campus_id:
            query += " AND campus_id = ?"
            params.append(campus_id)
        if open_only:
            query += " AND status = 'open'"
        with closing(self._connect()) as conn:
            rows = conn.execute(query + " ORDER BY id DESC", params).fetchall()
        return [self._request(r) for r in rows]

    def get_request(self, request_id: int) -> MeetingRequest:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM meeting_requests WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            raise AdvisingError("Meeting request not found.", 404)
        return self._request(row)

    def set_request_status(self, request_id: int, status: str) -> MeetingRequest:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE meeting_requests SET status = ? WHERE id = ?", (status, request_id))
        return self.get_request(request_id)

    def mark_booked(self, campus_id: str) -> None:
        """A student booking an appointment answers their open meeting requests."""
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE meeting_requests SET status = 'booked' WHERE campus_id = ? AND status = 'open'", (campus_id,))


def build_advisor_dashboard(
    caseload: Caseload,
    store: DataStore,
    advising: AdvisingStore,
    appointments: list[Appointment],
    today: str,
) -> AdvisorDashboard:
    rows = caseload.students
    reviews = advising.reviews()
    flagged = [r for r in rows if r.flags]
    demand = Counter(c for r in rows for c in r.next_required)
    top_careers = Counter(r.top_career for r in rows if r.top_career)
    tracks = Counter((r.major, r.track) for r in rows)

    shifts = market_career_shifts(store)
    rising = None
    if shifts and shifts[0].change_pts > 0:
        rising = RisingCareer(shift=shifts[0], students_top_matching=top_careers.get(shifts[0].career, 0))

    return AdvisorDashboard(
        advisor=advising.advisor,
        total_students=len(rows),
        by_major=dict(Counter(r.major for r in rows)),
        by_class_level={lvl: n for lvl, n in Counter(r.class_level for r in rows).items()},
        standing_counts=dict(Counter(r.academic_standing for r in rows)),
        flag_counts={code: sum(any(f.code == code for f in r.flags) for r in rows) for code in FLAGS},
        flagged_students=len(flagged),
        flagged_unreviewed=sum(1 for r in flagged if r.campus_id not in reviews),
        reviewed_students=len(reviews),
        upcoming_appointments=len(appointments),
        appointments_today=sum(1 for a in appointments if a.start.date().isoformat() == today),
        next_appointment=appointments[0] if appointments else None,
        open_meeting_requests=len(advising.requests()),
        tracks=[TrackCount(major=m, track=t, count=n) for (m, t), n in sorted(tracks.items(), key=lambda kv: (kv[0][0], -kv[1]))],
        top_careers=[NameCount(name=c, count=n) for c, n in top_careers.most_common()],
        course_demand=[
            CourseDemand(course_id=c, title=store.catalog[c].title, students=n)
            for c, n in demand.most_common(TOP_COURSE_DEMAND)
        ],
        rising_career=rising,
        next_term=NEXT_TERM,
    )
