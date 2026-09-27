from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PlanStatus = Literal["submitted", "approved", "changes_requested"]
PlanCategory = Literal["ready", "prereq", "meeting"]
CourseCheck = Literal["ok", "warning", "blocked"]

PLAN_NOTE = "Plans and approvals are recorded in this app only; they don't register students or change university holds."


class PlanCourse(BaseModel):
    course_id: str
    title: str
    credits: int
    required: bool = Field(description="Required for the student's major.")
    status: CourseCheck
    notes: list[str]


class PlanValidation(BaseModel):
    term: str
    courses: list[PlanCourse]
    total_credits: int
    issues: list[str] = Field(description="Plan-level warnings, e.g. credit load.")
    blocked: bool = Field(description="True if any course fails a hard check (prerequisites, already taken, unknown).")
    category: PlanCategory = Field(description="ready | prereq (a check failed) | meeting (standing or graduation risk)")
    meeting_reasons: list[str]
    missing_required: list[str] = Field(description="Remaining required courses the student could take next term but didn't plan.")


class PlanRequest(BaseModel):
    courses: list[str] = Field(min_length=1, max_length=8)
    note: str = Field(default="", max_length=500)


class PlanDecision(BaseModel):
    note: str = Field(default="", max_length=500)


class RegistrationPlan(BaseModel):
    id: int
    campus_id: str
    term: str
    courses: list[str]
    note: str
    status: PlanStatus
    advisor_note: str
    submitted_at: datetime
    decided_at: datetime | None
    validation: PlanValidation


class StudentPlanView(BaseModel):
    campus_id: str
    term: str
    plan: RegistrationPlan | None
    suggested: list[str] = Field(description="Next-term courses from the student's roadmap.")
    notice: str = PLAN_NOTE


class PlanQueueItem(RegistrationPlan):
    class_level: str
    major: str
    track: str
    gpa: float | None
    academic_standing: str
    credits_earned: int
    credits_required: int
    flags: list[str]


class PlanQueue(BaseModel):
    plans: list[PlanQueueItem]
    counts: dict[str, int] = Field(description="Submitted plans per category, plus decided totals.")
    notice: str = PLAN_NOTE


class BatchResult(BaseModel):
    approved: list[int]
