from pydantic import BaseModel, Field

from app.models.career import SALARY_BASIS, SalaryStats, YearlySalary

PERIOD_NOTE = "Trends compare entry-level alumni roles that started 2015–2020 with those that started 2023–2026."


class MarketScope(BaseModel):
    major: str | None = Field(description="Alumni major filter; null means all majors.")
    first_year: int
    last_year: int
    entry_role_count: int
    alumni_count: int


class CareerShift(BaseModel):
    career: str
    early_share: float
    recent_share: float
    change_pts: float = Field(description="recent_share - early_share, in percentage points.")


class SkillDemand(BaseModel):
    skill: str
    share: float = Field(description="Share of entry-level roles (all years) that listed the skill.")
    recent_share: float
    change_pts: float
    status: str = Field(description="have | in_progress | missing (for this student)")
    course: str | None = Field(description="A catalog course not yet taken that teaches the skill.")


class IndustryPlacement(BaseModel):
    industry: str
    share: float
    count: int
    median_salary: int


class RoleExample(BaseModel):
    job_title: str
    job_family: str
    employer: str = Field(description="Fictitious employer name from the synthetic dataset.")
    industry: str
    region: str
    start_year: int
    annual_salary_usd: int
    requires_clearance: bool
    is_remote: bool
    coverage: float = Field(description="Share of this role's listed skills the student already has.")
    matched_skills: list[str]
    missing_skills: list[str]


class MarketInsights(BaseModel):
    campus_id: str
    scope: MarketScope
    period_note: str = PERIOD_NOTE
    salary_basis: str = SALARY_BASIS
    entry_roles_latest_year: int
    first_job_salary: SalaryStats | None
    first_job_salary_by_major: dict[str, int]
    entry_salary_by_start_year: list[YearlySalary]
    clearance_share: float | None
    remote_share: float | None
    career_shifts: list[CareerShift]
    skill_demand: list[SkillDemand]
    rising_skills: list[SkillDemand]
    industries: list[IndustryPlacement]
    placement: dict[str, float] = Field(description="First-destination shares among alumni who responded.")
    response_rate: float
    role_skill_coverage: float = Field(description="Average share of a recent entry role's skills this student has.")
    bridge_skills: list[SkillDemand] = Field(description="Most in-demand skills the student is missing.")
    similar_roles: list[RoleExample]
