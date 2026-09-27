from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.appointments import Appointment, Reason
from app.models.market import CareerShift

RequestStatus = Literal["open", "booked", "dismissed"]


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=500)


class Review(BaseModel):
    campus_id: str
    reviewed_at: datetime
    note: str


class MeetingRequestCreate(BaseModel):
    campus_id: str = Field(pattern=CAMPUS_ID_PATTERN)
    reason: Reason
    message: str = Field(default="", max_length=500)


class MeetingRequest(BaseModel):
    id: int
    campus_id: str
    advisor: str
    reason: Reason
    reason_label: str
    message: str
    status: RequestStatus
    created_at: datetime


class MeetingRequestList(BaseModel):
    requests: list[MeetingRequest]


class NameCount(BaseModel):
    name: str
    count: int


class TrackCount(BaseModel):
    major: str
    track: str
    count: int


class CourseDemand(BaseModel):
    course_id: str
    title: str
    students: int = Field(description="Students for whom this is a remaining required course they can take next term.")


class RisingCareer(BaseModel):
    shift: CareerShift
    students_top_matching: int


class AdvisorDashboard(BaseModel):
    advisor: str
    total_students: int
    by_major: dict[str, int]
    by_class_level: dict[str, int]
    standing_counts: dict[str, int]
    flag_counts: dict[str, int]
    flagged_students: int
    flagged_unreviewed: int
    reviewed_students: int
    upcoming_appointments: int
    appointments_today: int
    next_appointment: Appointment | None
    open_meeting_requests: int
    tracks: list[TrackCount]
    top_careers: list[NameCount]
    course_demand: list[CourseDemand]
    rising_career: RisingCareer | None
    next_term: str
