from pydantic import BaseModel, Field


class AuditCourse(BaseModel):
    course_id: str
    title: str
    term: str
    credits: int
    grade: str
    skills: list[str] = Field(description="Catalog skill_tags for the course.")


class RequirementGroup(BaseModel):
    category: str = Field(description="transcripts.requirement_category")
    completed_credits: int
    in_progress_credits: int
    completed: list[AuditCourse]
    in_progress: list[AuditCourse]


class RemainingCourse(BaseModel):
    course_id: str
    title: str
    credits: int
    course_level: str
    skills: list[str]
    terms_offered: list[str]
    offered_next_term: bool
    status: str = Field(description="eligible | eligible_after_current_term | needs_prerequisites")
    missing_prerequisites: list[str]


class CreditSummary(BaseModel):
    earned: int = Field(description="students_current.credits_earned (includes transfer credit).")
    required: int
    in_progress: int
    remaining_after_current_term: int
    upper_division_completed: int = Field(description="Completed credits in 300-400 level catalog courses.")
    transfer_credits: int = Field(description="Credits earned minus UMBC transcript credits (transfer entrants only have these).")


class DegreeAudit(BaseModel):
    campus_id: str
    major: str
    track: str
    next_term: str
    credits: CreditSummary
    requirement_groups: list[RequirementGroup]
    remaining_required_courses: list[RemainingCourse] = Field(
        description="Catalog courses required for the major that are not completed, in progress, or implied by transfer credit."
    )
    satisfied_by_prior_credit: list[str] = Field(
        description="Required courses with no transcript row that are prerequisites of courses the student passed (transfer credit)."
    )
    unsuccessful_attempts: list[AuditCourse] = Field(description="F and W attempts.")
