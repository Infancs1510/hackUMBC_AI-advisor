from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Reason = Literal["course_planning", "career_planning", "degree_check", "internship_planning"]
Modality = Literal["in_person", "virtual"]
AppointmentStatus = Literal["booked", "cancelled", "completed", "no_show"]

REASON_LABELS: dict[str, str] = {
    "course_planning": "Course planning for next term",
    "career_planning": "Career planning & track electives",
    "degree_check": "Degree progress check",
    "internship_planning": "Internship & experience planning",
}


class Slot(BaseModel):
    start: datetime
    label: str = Field(examples=["10:00 AM"])
    available: bool


class SlotDay(BaseModel):
    date: str = Field(examples=["2026-09-29"])
    weekday: str = Field(examples=["Tue"])
    label: str = Field(examples=["Sep 29"])
    slots: list[Slot]


class SlotsResponse(BaseModel):
    advisor: str
    timezone: str
    duration_minutes: int
    days: list[SlotDay]


class AdvisingBrief(BaseModel):
    """Snapshot of the student's record at booking time, for the advisor."""

    major: str
    track: str
    class_level: str
    gpa: float | None
    credits_earned: int
    credits_required: int
    academic_standing: str
    expected_graduation_term: str
    remaining_required_courses: list[str]
    top_career: str | None
    top_career_score: float | None
    saved_goal: str | None


class Appointment(BaseModel):
    id: int
    campus_id: str
    advisor: str
    reason: Reason
    reason_label: str
    modality: Modality
    start: datetime
    end: datetime
    notes: str
    status: AppointmentStatus
    created_at: datetime
    brief: AdvisingBrief


class BookingRequest(BaseModel):
    reason: Reason
    modality: Modality
    start: datetime
    notes: str = Field(default="", max_length=1000)


class RescheduleRequest(BaseModel):
    start: datetime | None = None
    modality: Modality | None = None
    notes: str | None = Field(default=None, max_length=1000)


class AppointmentList(BaseModel):
    appointments: list[Appointment]


class SessionNoteRequest(BaseModel):
    note: str = Field(max_length=2000)


class ScheduleAppointment(Appointment):
    session_note: str = Field(default="", description="Advisor-only notes from the session; never shown to students.")


class ScheduleSlot(BaseModel):
    start: datetime
    label: str
    state: Literal["open", "closed", "booked", "completed", "no_show"] = Field(
        description="open = bookable; closed = unbooked and too soon or past; otherwise the appointment's status."
    )
    appointment: ScheduleAppointment | None


class ScheduleDay(BaseModel):
    date: str
    weekday: str
    label: str
    is_today: bool
    slots: list[ScheduleSlot]
    cancelled: list[ScheduleAppointment]


class ScheduleSummary(BaseModel):
    slots: int
    booked: int
    completed: int
    no_show: int
    cancelled: int
    open: int
    by_reason: dict[str, int]
    by_modality: dict[str, int]


class ScheduleRules(BaseModel):
    slot_times: list[str]
    duration_minutes: int
    min_notice_hours: int
    booking_window_weekdays: int
    modalities: list[str]


class WeekSchedule(BaseModel):
    advisor: str
    timezone: str
    week_start: str
    week_label: str
    today: str
    now: datetime
    days: list[ScheduleDay]
    summary: ScheduleSummary
    rules: ScheduleRules
