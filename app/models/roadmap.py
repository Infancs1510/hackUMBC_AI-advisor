from typing import Literal

from pydantic import BaseModel, Field

PlanReason = Literal["in_progress", "required", "career", "prerequisite"]


class PlannedCourse(BaseModel):
    course_id: str
    title: str
    credits: int
    reason: PlanReason = Field(description="Why it is in the plan: required for the major, builds career skills, or unlocks one.")
    skills_gained: list[str] = Field(description="Career skills this course adds that the student doesn't have yet.")


class PlannedTerm(BaseModel):
    term: str
    status: Literal["in_progress", "planned"]
    courses: list[PlannedCourse]
    credits: int
    score_after: float = Field(description="Career match score once this term's courses are complete.")
    after_expected_graduation: bool


class Roadmap(BaseModel):
    campus_id: str
    career: str
    expected_graduation_term: str
    score_now: float
    score_after_plan: float
    terms: list[PlannedTerm]
    skills_not_covered: list[str] = Field(description="Career skills no catalog course teaches.")
    unscheduled: list[str] = Field(
        description="Career courses (and their prerequisites) that don't fit before expected graduation."
    )
    skills_after_plan_missing: list[str] = Field(
        description="Career skills still missing after the plan; candidates for certifications, projects, or internships."
    )
    note: str = (
        "Suggested sequence, not an official degree plan. It covers remaining required courses and the fewest "
        "courses that teach this career's missing skills, respecting prerequisites and typical terms offered. "
        "General education and elective credits needed to reach the degree total are not planned here."
    )
