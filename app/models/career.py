from pydantic import BaseModel, Field

SALARY_BASIS = (
    "Nominal USD for the start year of each job spell; not inflation-adjusted. "
    "Figures span multiple start years and are not directly comparable across years."
)


class SalaryStats(BaseModel):
    sample_size: int
    median: int
    p25: int
    p75: int
    min: int
    max: int
    start_year_min: int | None = None
    start_year_max: int | None = None


class YearlySalary(BaseModel):
    start_year: int
    sample_size: int
    median: int


class CareerSalary(BaseModel):
    career: str
    basis: str = SALARY_BASIS
    entry_level: SalaryStats | None
    all_levels: SalaryStats | None
    by_seniority: dict[str, SalaryStats]
    entry_level_by_start_year: list[YearlySalary]


class SkillFrequency(BaseModel):
    skill: str
    share: float = Field(description="Share of entry-level job spells in this career listing the skill (0-1).")
    is_core: bool


class CountShare(BaseModel):
    name: str
    count: int
    share: float


class EmployerStat(CountShare):
    industry: str


class EntryMarket(BaseModel):
    """Where alumni entry-level jobs in this career were (employer names are fictitious)."""

    spell_count: int
    requires_clearance_share: float | None
    remote_share: float | None
    top_employers: list[EmployerStat]
    top_regions: list[CountShare]


class AlumniOutcomes(BaseModel):
    """First-destination statistics for alumni whose first job was in this career."""

    alumni_count: int
    share_with_internship: float | None
    first_job_remote_share: float | None = Field(
        description="Share of these alumni whose first job was fully remote (alumni.first_job_is_remote)."
    )
    found_via: dict[str, int]
    top_certifications: list[CountShare] = Field(
        default_factory=list, description="Certifications held by these alumni; share is of the alumni_count."
    )


class CareerSummary(BaseModel):
    career: str
    job_spell_count: int
    entry_spell_count: int
    core_skills: list[str]
    top_titles: list[str]
    median_entry_salary: int | None


class CareerDetail(CareerSummary):
    skills: list[SkillFrequency]
    skills_by_seniority: dict[str, list[str]]
    salary: CareerSalary
    entry_market: EntryMarket
    alumni_outcomes: AlumniOutcomes


class CareerListResponse(BaseModel):
    careers: list[CareerSummary]
    source: str = "employment_history.csv (alumni job spells)"
