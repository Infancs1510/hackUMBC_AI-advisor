from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models.appointments import AdvisingBrief
from app.services.appointments import SLOT_TIMES, AppointmentError, AppointmentService
from tests.conftest import FIRST_TERM, IS_FRESHMAN, TRANSFER_JUNIOR, FakeMemory

TZ = ZoneInfo("America/New_York")


def open_slots(client, n=2):
    days = client.get("/api/appointments/slots").json()["days"]
    return [s["start"] for d in days for s in d["slots"] if s["available"]][:n]


def book(client, start, reason="course_planning", notes=""):
    return client.post("/api/appointments", json={"reason": reason, "modality": "virtual", "start": start, "notes": notes})


def test_slots_cover_two_working_weeks(student_client):
    body = student_client(TRANSFER_JUNIOR).get("/api/appointments/slots").json()
    assert len(body["days"]) == 10
    assert all(d["weekday"] in {"Mon", "Tue", "Wed", "Thu", "Fri"} for d in body["days"])
    assert all(len(d["slots"]) == len(SLOT_TIMES) for d in body["days"])
    now = datetime.now(TZ)
    assert all(datetime.fromisoformat(s["start"]) > now for d in body["days"] for s in d["slots"])


def test_booking_lifecycle(make_client, advisor_client):
    student = make_client(memory=FakeMemory(), as_student=TRANSFER_JUNIOR)
    first, second = open_slots(student)
    booked = book(student, first, notes="CMSC426 vs CMSC487?")
    assert booked.status_code == 201, booked.text
    appt = booked.json()
    brief = appt["brief"]
    assert brief["gpa"] == 3.0 and brief["credits_earned"] == 76
    assert set(brief["remaining_required_courses"]) == {"CMSC411", "CMSC421", "CMSC441", "CMSC447"}
    assert appt["reason_label"] and appt["notes"] == "CMSC426 vs CMSC487?"

    # One upcoming appointment per student; the slot is no longer offered.
    assert book(student, second).status_code == 409
    assert first not in open_slots(student, 100)

    # Someone else can't take the slot, see, change, or cancel the appointment.
    other = make_client(as_student=FIRST_TERM)
    assert book(other, first).status_code == 409
    assert other.get("/api/appointments").json()["appointments"] == []
    assert other.patch(f"/api/appointments/{appt['id']}", json={"notes": "x"}).status_code == 403
    assert other.post(f"/api/appointments/{appt['id']}/cancel").status_code == 403

    # Reschedule frees the old slot.
    moved = student.patch(f"/api/appointments/{appt['id']}", json={"start": second, "modality": "in_person"}).json()
    assert moved["start"] == second and moved["modality"] == "in_person"
    assert first in open_slots(student, 100)

    # The advisor sees it with the brief, and can cancel it.
    listed = advisor_client.get("/api/appointments").json()["appointments"]
    assert [a["id"] for a in listed if a["campus_id"] == TRANSFER_JUNIOR] == [appt["id"]]
    assert advisor_client.post(f"/api/appointments/{appt['id']}/cancel").json()["status"] == "cancelled"
    assert student.get("/api/appointments").json()["appointments"] == []
    history = student.get("/api/appointments", params={"include_past": True}).json()["appointments"]
    assert history[0]["status"] == "cancelled"


def test_booking_validation(make_client, advisor_client):
    student = make_client(as_student=IS_FRESHMAN)
    start = datetime.fromisoformat(open_slots(student, 1)[0])
    off_grid = (start + timedelta(minutes=7)).isoformat()
    assert book(student, off_grid).status_code == 400
    assert student.post("/api/appointments", json={"reason": "gossip", "modality": "virtual", "start": start.isoformat()}).status_code == 422
    assert advisor_client.post("/api/appointments", json={"reason": "degree_check", "modality": "virtual", "start": start.isoformat()}).status_code == 403
    assert student.post("/api/appointments/99999/cancel").status_code == 404


def test_minimum_notice(tmp_path):
    service = AppointmentService(tmp_path / "a.db", "Advisor", "America/New_York")
    now = datetime(2026, 9, 28, 9, 0, tzinfo=TZ)  # Monday morning
    brief = AdvisingBrief(
        major="Computer Science", track="General", class_level="Junior", gpa=3.0, credits_earned=60,
        credits_required=120, academic_standing="Good Standing", expected_graduation_term="Spring 2028",
        remaining_required_courses=[], top_career=None, top_career_score=None, saved_goal=None,
    )
    days = service.slots(now).days
    assert days[0].date == "2026-09-29"  # booking opens tomorrow
    tomorrow_ten = days[0].slots[0].start
    assert service.book("CID-000001", "degree_check", "virtual", tomorrow_ten, "", brief, now=now).id == 1
    too_soon = tomorrow_ten + timedelta(minutes=30)
    with pytest.raises(AppointmentError):
        service.book("CID-000002", "degree_check", "virtual", too_soon, "", brief, now=too_soon - timedelta(hours=1))


def test_week_schedule_no_show_and_session_notes(tmp_path):
    service = AppointmentService(tmp_path / "a.db", "Advisor", "America/New_York")
    now = datetime(2026, 9, 28, 9, 0, tzinfo=TZ)  # Monday morning
    brief = AdvisingBrief(
        major="Computer Science", track="General", class_level="Junior", gpa=3.0, credits_earned=60,
        credits_required=120, academic_standing="Good Standing", expected_graduation_term="Spring 2028",
        remaining_required_courses=[], top_career=None, top_career_score=None, saved_goal=None,
    )
    tue = service.slots(now).days[0].slots
    kept = service.book("CID-000001", "degree_check", "virtual", tue[0].start, "", brief, now=now)
    dropped = service.book("CID-000002", "course_planning", "in_person", tue[1].start, "", brief, now=now)
    service.cancel(dropped)

    # Not before it starts; after, the no-show sticks and notes stay private to the week view.
    with pytest.raises(AppointmentError):
        service.mark_no_show(kept, now=now)
    later = tue[0].start + timedelta(minutes=10)
    assert service.mark_no_show(kept, now=later).status == "no_show"
    service.set_session_note(kept, "  Called, no answer.  ")

    week = service.week(now=now)
    assert week.week_start == "2026-09-28" and [d.weekday for d in week.days] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    assert week.days[0].is_today and all(s.state == "closed" for s in week.days[0].slots)  # booking opens tomorrow
    first, second = week.days[1].slots[:2]
    assert first.state == "no_show" and first.appointment.session_note == "Called, no answer."
    assert second.state == "open" and second.appointment is None  # a cancellation frees the slot
    assert [a.campus_id for a in week.days[1].cancelled] == ["CID-000002"]
    s = week.summary
    assert (s.slots, s.no_show, s.cancelled, s.booked) == (5 * len(SLOT_TIMES), 1, 1, 0)
    assert s.open == 4 * len(SLOT_TIMES) - 1

    service.set_session_note(kept, "")
    assert service.week(now=now).days[1].slots[0].appointment.session_note == ""
    # Any date in a week resolves to its Monday.
    assert service.week(datetime(2026, 10, 8).date(), now=now).week_start == "2026-10-05"
    assert service.week(now=datetime(2026, 10, 3, 12, 0, tzinfo=TZ)).week_start == "2026-10-05"  # Saturday


def test_schedule_endpoints_are_advisor_only(make_client, advisor_client):
    student = make_client(as_student=TRANSFER_JUNIOR)
    start = open_slots(student, 1)[0]
    appt = book(student, start).json()
    assert student.get("/api/appointments/schedule").status_code == 403
    assert student.put(f"/api/appointments/{appt['id']}/session-note", json={"note": "x"}).status_code == 403
    assert student.post(f"/api/appointments/{appt['id']}/no-show").status_code == 403

    assert advisor_client.put(f"/api/appointments/{appt['id']}/session-note", json={"note": "Bring transcript"}).json() == {"note": "Bring transcript"}
    week = advisor_client.get("/api/appointments/schedule", params={"week": start[:10]}).json()
    slot = next(s for d in week["days"] for s in d["slots"] if s["start"] == start)
    assert slot["state"] == "booked" and slot["appointment"]["session_note"] == "Bring transcript"
    assert "session_note" not in student.get("/api/appointments").json()["appointments"][0]
    # Upcoming appointments can't be no-shows yet.
    assert advisor_client.post(f"/api/appointments/{appt['id']}/no-show").status_code == 409
