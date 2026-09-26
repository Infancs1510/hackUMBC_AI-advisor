from pydantic import BaseModel, Field

from app.models.career import AlumniOutcomes, CareerSalary

MATCH_SCORE_NOTE = (
    "Match score is weighted skill overlap between completed-course skills and the skills "
    "alumni entry-level roles in this career listed. It is not a probability of employment."
)


class CourseRecord(BaseModel):
    course_id: str
    title: str
    term: str
    credits: int
    grade: str


class Experience(BaseModel):
    experience_type: str
    name: str
    organization: str
    term: str
    outcome: str


class StudentProfile(BaseModel):
    campus_id: str
    major: str
    track: str
    second_major: str | None
    minor: str | None
    class_level: str
    entry_term: str
    entry_type: str
    expected_graduation_term: str
    academic_standing: str
    gpa: float | None = Field(description="cumulative_gpa from students_current.csv; null for first-term students.")
    major_gpa: float | None
    calculated_gpa: float | None = Field(
        description="GPA recomputed from transcripts (credit-weighted, W/IP excluded)."
    )
    credits_earned: int = Field(description="Includes transfer credits, which have no transcript rows.")
    credits_required: int
    credits_in_progress: int
    internship_count: int
    credential_count: int
    engagement_activity_count: int
    completed_courses: list[CourseRecord]
    in_progress_courses: list[CourseRecord]
    internships: list[Experience]
    credentials: list[Experience]
    activities: list[Experience]


class SkillItem(BaseModel):
    skill: str
    courses: list[str]


class CareerMatch(BaseModel):
    career: str
    score: float = Field(description="0-100 weighted skill overlap; not a probability.")
    projected_score: float = Field(description="Score if current in-progress courses are completed.")
    matched_skills: list[str]
    missing_skills: list[str]
    missing_core_skills: list[str]


class CourseRecommendation(BaseModel):
    course_id: str
    title: str
    credits: int
    course_level: str
    course_type: str
    difficulty_index: float
    terms_offered: list[str]
    offered_next_term: bool
    skills_gained: list[str]
    status: str = Field(description="eligible | eligible_after_current_term | needs_prerequisites")
    missing_prerequisites: list[str]


class PrerequisiteStep(BaseModel):
    course_id: str
    title: str
    status: str
    offered_next_term: bool
    unlocks: list[str] = Field(description="Recommended courses this step leads toward.")


class Pathway(BaseModel):
    career: str
    next_term: str
    current_skills_matched: list[str]
    missing_skills: list[str]
    recommended_courses: list[CourseRecommendation]
    prerequisite_steps: list[PrerequisiteStep] = Field(
        description="Courses to take first when recommended courses still need prerequisites."
    )
    skills_not_covered_by_catalog: list[str]
    alumni_outcomes: AlumniOutcomes


class DashboardResponse(BaseModel):
    student: StudentProfile
    skills: list[SkillItem]
    in_progress_skills: list[SkillItem]
    career_matches: list[CareerMatch]
    match_score_note: str = MATCH_SCORE_NOTE
    selected_career: str | None
    pathway: Pathway | None
    salary: CareerSalary | None
