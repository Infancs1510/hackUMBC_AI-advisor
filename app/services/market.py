"""Market insights from alumni outcomes (not live job postings).

Entry-level spells in employment_history.csv stand in for "the market": what roles UMBC alumni
were hired into, what skills those roles listed, where, and at what nominal salary.
"""

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import NOT_APPLICABLE, split_pipe
from app.models.career import YearlySalary
from app.models.market import CareerShift, IndustryPlacement, MarketInsights, MarketScope, RoleExample, SkillDemand
from app.services.pathway import implied_prerequisites, prerequisite_status
from app.services.salary import salary_stats
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import StudentNotFoundError, completed_course_ids, in_progress_course_ids

EARLY_YEARS = (2015, 2020)
RECENT_YEARS = (2023, 2026)
TOP_SKILLS = 12
TOP_RISING = 4
TOP_BRIDGES = 3
TOP_INDUSTRIES = 7
SIMILAR_ROLES = 5
_STATUS_RANK = {"eligible": 0, "eligible_after_current_term": 1, "needs_prerequisites": 2}


def _entry_roles(store: DataStore, major: str | None) -> pd.DataFrame:
    roles = store.employment[store.employment["seniority_level"] == "Entry"].copy()
    if major:
        majors = store.alumni["major"]
        roles = roles[roles["campus_id"].map(majors) == major]
    roles["start_year"] = roles["start_date"].str[:4].astype(int)
    roles["skills"] = roles["role_skill_tags"].map(lambda v: frozenset(split_pipe(v)))
    return roles


def _in_years(roles: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    return roles[roles["start_year"].between(*years)]


def _skill_shares(roles: pd.DataFrame) -> pd.Series:
    if roles.empty:
        return pd.Series(dtype=float)
    return roles["skills"].explode().value_counts() / len(roles)


def _share(mask: pd.Series) -> float | None:
    return round(float(mask.astype(bool).mean()), 3) if len(mask) else None


def career_share_shifts(early: pd.DataFrame, recent: pd.DataFrame) -> list[CareerShift]:
    """Change in each career's share of entry-level roles between two periods, largest rise first."""
    family_early = early["job_family"].value_counts(normalize=True)
    family_recent = recent["job_family"].value_counts(normalize=True)
    shifts = [
        CareerShift(
            career=str(f),
            early_share=round(float(family_early.get(f, 0.0)), 3),
            recent_share=round(float(family_recent.get(f, 0.0)), 3),
            change_pts=round(100 * float(family_recent.get(f, 0.0) - family_early.get(f, 0.0)), 1),
        )
        for f in sorted(set(family_early.index) | set(family_recent.index))
    ]
    return sorted(shifts, key=lambda s: -s.change_pts)


def market_career_shifts(store: DataStore, major: str | None = None) -> list[CareerShift]:
    roles = _entry_roles(store, major)
    return career_share_shifts(_in_years(roles, EARLY_YEARS), _in_years(roles, RECENT_YEARS))


def build_market_insights(store: DataStore, campus_id: str, major: str | None = None) -> MarketInsights:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))

    # Student context.
    transcript = store.transcript_for(campus_id)
    completed = completed_course_ids(transcript)
    in_progress = in_progress_course_ids(transcript)
    satisfied = completed | implied_prerequisites(completed, store.catalog)
    have = skill_set(extract_skills(completed, store.catalog))
    learning = skill_set(extract_skills(in_progress, store.catalog)) - have

    def status(skill: str) -> str:
        return "have" if skill in have else "in_progress" if skill in learning else "missing"

    def course_for(skill: str) -> str | None:
        options = [
            c for c in store.catalog.values()
            if skill in c.skills and c.course_id not in satisfied and c.course_id not in in_progress
        ]
        options.sort(key=lambda c: (_STATUS_RANK[prerequisite_status(c, satisfied, in_progress)[0]], c.difficulty_index, c.course_id))
        return options[0].course_id if options else None

    # Market data.
    roles = _entry_roles(store, major)
    early, recent = _in_years(roles, EARLY_YEARS), _in_years(roles, RECENT_YEARS)
    alumni = store.alumni if not major else store.alumni[store.alumni["major"] == major]

    shifts = career_share_shifts(early, recent)

    all_shares, early_shares, recent_shares = _skill_shares(roles), _skill_shares(early), _skill_shares(recent)

    def demand(skill: str) -> SkillDemand:
        return SkillDemand(
            skill=skill,
            share=round(float(all_shares.get(skill, 0.0)), 3),
            recent_share=round(float(recent_shares.get(skill, 0.0)), 3),
            change_pts=round(100 * float(recent_shares.get(skill, 0.0) - early_shares.get(skill, 0.0)), 1),
            status=status(skill),
            course=None if skill in have else course_for(skill),
        )

    top = [demand(s) for s in all_shares.index[:TOP_SKILLS]]
    changes = (recent_shares - early_shares.reindex(recent_shares.index, fill_value=0.0)).sort_values(ascending=False)
    rising = [demand(s) for s in changes.index[:TOP_RISING] if changes[s] > 0]
    missing_ranked = [s for s in all_shares.index if s not in have and s not in learning]
    bridges = [demand(s) for s in missing_ranked[:TOP_BRIDGES]]

    # First destinations and first-job salaries (alumni.csv).
    responded = alumni[alumni["first_destination"] != "No Response"]
    placement = {str(k): round(float(v), 3) for k, v in responded["first_destination"].value_counts(normalize=True).items()}
    employed = alumni[alumni["first_job_annual_salary_usd"].astype(str) != NOT_APPLICABLE].copy()
    employed["salary"] = employed["first_job_annual_salary_usd"].astype(int)
    by_industry = employed.groupby("first_employer_industry")["salary"].agg(["count", "median"]).sort_values("count", ascending=False)
    industries = [
        IndustryPlacement(industry=str(name), share=round(row["count"] / len(employed), 3), count=int(row["count"]), median_salary=round(row["median"]))
        for name, row in by_industry.head(TOP_INDUSTRIES).iterrows()
    ]
    first_by_major = {str(m): round(float(g["salary"].median())) for m, g in employed.groupby("major")}

    by_year = roles.groupby("start_year")["annual_salary_usd"].agg(["count", "median"])
    salary_trend = [YearlySalary(start_year=int(y), sample_size=int(r["count"]), median=round(r["median"])) for y, r in by_year.iterrows()]

    # Personal fit against recent roles.
    if recent.empty:
        coverage_mean, similar = 0.0, []
    else:
        coverage = recent["skills"].map(lambda s: len(s & have) / len(s) if s else 0.0)
        coverage_mean = round(float(coverage.mean()), 3)
        ranked = recent.assign(coverage=coverage).sort_values(
            ["coverage", "start_year", "annual_salary_usd"], ascending=[False, False, False]
        ).drop_duplicates(["job_title", "employer"])
        similar = [
            RoleExample(
                job_title=r.job_title, job_family=r.job_family, employer=r.employer, industry=r.employer_industry,
                region=r.region, start_year=int(r.start_year), annual_salary_usd=int(r.annual_salary_usd),
                requires_clearance=bool(r.requires_clearance), is_remote=bool(r.is_remote),
                coverage=round(float(r.coverage), 3),
                matched_skills=sorted(r.skills & have), missing_skills=sorted(r.skills - have),
            )
            for r in ranked[ranked["coverage"] > 0].head(SIMILAR_ROLES).itertuples(index=False)
        ]

    years = roles["start_year"]
    return MarketInsights(
        campus_id=campus_id,
        scope=MarketScope(
            major=major,
            first_year=int(years.min()) if len(years) else EARLY_YEARS[0],
            last_year=int(years.max()) if len(years) else RECENT_YEARS[1],
            entry_role_count=len(roles),
            alumni_count=len(alumni),
        ),
        entry_roles_latest_year=int((years == years.max()).sum()) if len(years) else 0,
        first_job_salary=salary_stats(employed["salary"]) if len(employed) else None,
        first_job_salary_by_major=first_by_major,
        entry_salary_by_start_year=salary_trend,
        clearance_share=_share(roles["requires_clearance"]),
        remote_share=_share(roles["is_remote"]),
        career_shifts=shifts,
        skill_demand=top,
        rising_skills=rising,
        industries=industries,
        placement=placement,
        response_rate=round(len(responded) / len(alumni), 3) if len(alumni) else 0.0,
        role_skill_coverage=coverage_mean,
        bridge_skills=bridges,
        similar_roles=similar,
    )
