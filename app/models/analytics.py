from typing import Literal

from pydantic import BaseModel, Field

from app.models.appointments import Reason


class PathwayKpis(BaseModel):
    total_students: int
    on_pace: int = Field(description="Students whose degree-only plan fits before expected graduation.")
    on_pace_share: float
    major_core_average: float | None = Field(description="Credit-weighted grade points in Major Core courses (W/IP excluded).")
    gpa_bands: dict[str, int]
    foundation_eligible: int = Field(description="Sophomores and above.")
    foundation_complete: int = Field(description="Of those, students with no lower-division required courses left.")
    upper_class: int
    upper_class_with_internship: int


class TrackStat(BaseModel):
    major: str
    track: str
    students: int
    average_gpa: float | None
    upper_class_internship_share: float | None
    capstone_course: str
    capstone_ready: int = Field(description="Juniors/seniors who finished, are taking, or can take the capstone next term.")
    upper_class: int
    top_careers: list[tuple[str, int]]


class LevelStat(BaseModel):
    class_level: str
    students: int
    on_pace: int
    graduation_risk: int
    with_internship: int
    standing_issues: int


class InternshipInsight(BaseModel):
    employed_with: float
    employed_without: float
    median_salary_with: int
    median_salary_without: int
    return_offers: int
    responders: int


class Bottleneck(BaseModel):
    course_id: str
    title: str
    course_level: str
    required_for: list[str]
    historical_attempts: int
    dfw_rate: float = Field(description="Share of completed attempts (all students and alumni) graded D, F, or W.")
    repeat_rate: float
    currently_enrolled: int
    next_term_demand: int = Field(description="Current students for whom it's a remaining required course they can take next term.")
    unresolved: list[str] = Field(description="Current students whose latest attempt is F/W, not passed or being retaken.")
    risk: Literal["high", "moderate", "normal"]


class CareerAlignment(BaseModel):
    career: str
    students_top_match: int
    recent_share: float
    change_pts: float
    core_skills: list[str]
    students_with_all_core: int = Field(description="Of the students who top-match this career.")
    bridge_course: str | None = Field(description="Catalog course that gives the most top-matching students a missing core skill.")
    bridge_title: str | None
    bridge_students: int = Field(description="Top-matching students who'd gain at least one missing core skill from it.")


class InterventionAction(BaseModel):
    type: Literal["meetings", "roster"]
    reason: Reason | None = None
    campus_ids: list[str] = []
    roster_query: str | None = None
    label: str


class Intervention(BaseModel):
    icon: str
    title: str
    detail: str
    action: InterventionAction | None


class PathwayAnalytics(BaseModel):
    next_term: str
    period_note: str
    dfw_median: float
    kpis: PathwayKpis
    tracks: list[TrackStat]
    levels: list[LevelStat]
    internship_insight: InternshipInsight
    bottlenecks: list[Bottleneck]
    careers: list[CareerAlignment]
    interventions: list[Intervention]
