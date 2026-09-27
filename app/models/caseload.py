from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CaseloadSort = Literal["flags", "campus_id", "gpa_asc", "gpa_desc", "match_asc", "match_desc"]


class CaseloadFlag(BaseModel):
    code: str
    label: str


class CaseloadStudent(BaseModel):
    campus_id: str
    major: str
    track: str
    class_level: str
    gpa: float | None
    credits_earned: int
    academic_standing: str
    expected_graduation_term: str
    internship_count: int
    credential_count: int
    top_career: str | None
    top_career_score: float
    flags: list[CaseloadFlag]
    remaining_required_count: int
    next_required: list[str] = Field(description="Remaining required courses the student can take next term.")
    reviewed_at: datetime | None = None
    review_note: str | None = None


class CaseloadFacets(BaseModel):
    majors: list[str]
    tracks: list[str]
    class_levels: list[str]
    standings: list[str]
    careers: list[str]
    flags: list[CaseloadFlag]
    flag_counts: dict[str, int] = Field(description="Students with each flag across the whole caseload.")


class CaseloadResponse(BaseModel):
    total: int = Field(description="Students matching the filters.")
    page: int
    page_size: int
    students: list[CaseloadStudent]
    facets: CaseloadFacets
