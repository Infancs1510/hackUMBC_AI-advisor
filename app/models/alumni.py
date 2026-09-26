from pydantic import BaseModel, Field

from app.models.career import SALARY_BASIS
from app.models.dashboard import MATCH_SCORE_NOTE, CareerMatch, Experience, SkillItem


class FirstJob(BaseModel):
    title: str
    job_family: str
    employer: str
    industry: str
    region: str
    annual_salary_usd: int = Field(description="Nominal dollars of the job's start year.")
    is_remote: bool | None
    found_via: str | None
    months_to_first_job: float | None


class JobSpell(BaseModel):
    job_id: str
    job_title: str
    job_family: str
    seniority_level: str
    employer: str
    employer_industry: str
    region: str
    is_remote: bool
    start_date: str
    end_date: str | None = Field(description="Null if and only if this is the current job.")
    is_current: bool
    tenure_months: int
    annual_salary_usd: int = Field(description="Nominal dollars of the spell's start year.")
    change_type: str
    role_skills: list[str]


class AlumniProfile(BaseModel):
    campus_id: str
    major: str
    degree_level: str
    track: str
    graduation_term: str
    graduation_year: int
    entry_type: str
    time_to_degree_years: float
    total_credits_earned: int
    final_gpa: float
    major_gpa: float
    holds_prior_umbc_bachelors: bool
    internship_count: int
    credential_count: int
    engagement_activity_count: int
    net_cost_usd: int = Field(description="Tuition and fees after grant/scholarship aid, from alumni.csv.")
    total_loans_usd: int
    first_destination: str


class AlumniResponse(BaseModel):
    alumnus: AlumniProfile
    first_job: FirstJob | None = Field(description="Null when first_destination is not an employed category.")
    employment_history: list[JobSpell] = Field(
        description="Empty for alumni who went to graduate school, the military, were seeking, or did not respond."
    )
    experiences: list[Experience]
    skills: list[SkillItem]
    career_matches: list[CareerMatch] = Field(
        description="How this alum's coursework overlaps each career's entry-level skill profile."
    )
    first_job_career_match: CareerMatch | None = Field(
        description="The match entry for the career family of the first job, if any."
    )
    match_score_note: str = MATCH_SCORE_NOTE
    salary_basis: str = SALARY_BASIS
