"""Career profiles and matching.

A career is a `job_family` in employment_history.csv. Its skill profile is how often each
skill appears in `role_skill_tags` across entry-level spells (what a graduating student would
be hired into). Matching is weighted overlap with the student's completed-course skills; the
two vocabularies are the same, so no mapping is needed.
"""

from collections import Counter
from dataclasses import dataclass

import pandas as pd

from app.data.parsing import NOT_APPLICABLE, split_pipe
from app.models.career import (
    AlumniOutcomes,
    CareerDetail,
    CareerSummary,
    CountShare,
    EmployerStat,
    EntryMarket,
    SkillFrequency,
)
from app.models.dashboard import CareerMatch
from app.services.salary import SENIORITY_ORDER, career_salary

# Skills listed by fewer than this share of entry-level spells are treated as noise.
MIN_SKILL_SHARE = 0.15
# Skills listed by at least this share of entry-level spells are the career's core skills.
CORE_SKILL_SHARE = 0.9
ENTRY_LEVEL = "Entry"
TOP_N = 6


@dataclass(frozen=True)
class CareerProfile:
    name: str
    job_spell_count: int
    entry_spell_count: int
    skill_weights: dict[str, float]  # skill -> share of entry-level spells, >= MIN_SKILL_SHARE
    top_titles: list[str]

    @property
    def core_skills(self) -> list[str]:
        return [s for s, w in self.skill_weights.items() if w >= CORE_SKILL_SHARE]


def _skill_shares(spells: pd.DataFrame) -> dict[str, float]:
    if spells.empty:
        return {}
    counts: Counter[str] = Counter()
    for tags in spells["role_skill_tags"]:
        counts.update(set(split_pipe(tags)))
    total = len(spells)
    return {skill: count / total for skill, count in counts.items()}


def build_career_profiles(employment: pd.DataFrame) -> dict[str, CareerProfile]:
    profiles: dict[str, CareerProfile] = {}
    for career, spells in employment.groupby("job_family"):
        entry = spells[spells["seniority_level"] == ENTRY_LEVEL]
        basis = entry if not entry.empty else spells
        shares = _skill_shares(basis)
        weights = {
            s: round(w, 3)
            for s, w in sorted(shares.items(), key=lambda kv: (-kv[1], kv[0]))
            if w >= MIN_SKILL_SHARE
        }
        profiles[str(career)] = CareerProfile(
            name=str(career),
            job_spell_count=len(spells),
            entry_spell_count=len(entry),
            skill_weights=weights,
            top_titles=basis["job_title"].value_counts().head(5).index.tolist(),
        )
    return profiles


def _weighted_overlap(skills: set[str], weights: dict[str, float]) -> float:
    total = sum(weights.values())
    return round(100 * sum(w for s, w in weights.items() if s in skills) / total, 1) if total else 0.0


def match_career(
    student_skills: set[str], profile: CareerProfile, in_progress_skills: set[str] = frozenset()
) -> CareerMatch:
    weights = profile.skill_weights
    return CareerMatch(
        career=profile.name,
        score=_weighted_overlap(student_skills, weights),
        projected_score=_weighted_overlap(student_skills | in_progress_skills, weights),
        matched_skills=[s for s in weights if s in student_skills],
        missing_skills=[s for s in weights if s not in student_skills],
        missing_core_skills=[s for s in profile.core_skills if s not in student_skills],
    )


def match_careers(
    student_skills: set[str],
    profiles: dict[str, CareerProfile],
    in_progress_skills: set[str] = frozenset(),
) -> list[CareerMatch]:
    """Rank careers by score; ties (e.g. first-term students at 0) break on projected score."""
    matches = [match_career(student_skills, p, in_progress_skills) for p in profiles.values()]
    return sorted(matches, key=lambda m: (-m.score, -m.projected_score, m.career))


def resolve_career(name: str, profiles: dict[str, CareerProfile]) -> str | None:
    """Case-insensitive lookup of a career name."""
    wanted = name.strip().casefold()
    return next((c for c in profiles if c.casefold() == wanted), None)


def alumni_outcomes(alumni: pd.DataFrame, career: str, experiences: pd.DataFrame | None = None) -> AlumniOutcomes:
    cohort = alumni[alumni["first_job_family"] == career]
    # first_job_is_remote mixes TRUE/FALSE with "Not Applicable", so it loads as text.
    remote = cohort.loc[cohort["first_job_is_remote"].astype(str) != NOT_APPLICABLE, "first_job_is_remote"]
    found_via = cohort.loc[cohort["first_job_found_via"] != NOT_APPLICABLE, "first_job_found_via"]

    certifications: list[CountShare] = []
    if experiences is not None and len(cohort):
        certs = experiences[
            (experiences["experience_type"] == "Certification") & experiences["campus_id"].isin(cohort["campus_id"])
        ]
        holders = certs.drop_duplicates(["campus_id", "experience_name"])["experience_name"].value_counts()
        certifications = [
            CountShare(name=str(name), count=int(n), share=round(n / len(cohort), 3))
            for name, n in holders.head(TOP_N).items()
        ]

    return AlumniOutcomes(
        alumni_count=len(cohort),
        share_with_internship=(
            round(float((cohort["internship_count"] > 0).mean()), 3) if len(cohort) else None
        ),
        first_job_remote_share=round(float((remote.astype(str) == "TRUE").mean()), 3) if len(remote) else None,
        found_via={str(k): int(v) for k, v in found_via.value_counts().items()},
        top_certifications=certifications,
    )


def entry_market(employment: pd.DataFrame, career: str) -> EntryMarket:
    entry = employment[(employment["job_family"] == career) & (employment["seniority_level"] == ENTRY_LEVEL)]
    n = len(entry)
    employers = [
        EmployerStat(
            name=str(name),
            count=len(group),
            share=round(len(group) / n, 3),
            industry=str(group["employer_industry"].mode().iloc[0]),
        )
        for name, group in sorted(entry.groupby("employer"), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_N]
    ]
    regions = [
        CountShare(name=str(name), count=int(c), share=round(c / n, 3))
        for name, c in entry["region"].value_counts().head(TOP_N).items()
    ]
    return EntryMarket(
        spell_count=n,
        requires_clearance_share=round(float(entry["requires_clearance"].astype(bool).mean()), 3) if n else None,
        remote_share=round(float(entry["is_remote"].astype(bool).mean()), 3) if n else None,
        top_employers=employers,
        top_regions=regions,
    )


def career_summary(profile: CareerProfile, employment: pd.DataFrame) -> CareerSummary:
    entry = employment[
        (employment["job_family"] == profile.name) & (employment["seniority_level"] == ENTRY_LEVEL)
    ]
    median = entry["annual_salary_usd"].median() if not entry.empty else None
    return CareerSummary(
        career=profile.name,
        job_spell_count=profile.job_spell_count,
        entry_spell_count=profile.entry_spell_count,
        core_skills=profile.core_skills,
        top_titles=profile.top_titles,
        median_entry_salary=round(float(median)) if median is not None else None,
    )


def career_detail(
    profile: CareerProfile,
    employment: pd.DataFrame,
    alumni: pd.DataFrame,
    experiences: pd.DataFrame | None = None,
) -> CareerDetail:
    spells = employment[employment["job_family"] == profile.name]
    by_seniority: dict[str, list[str]] = {}
    for level in SENIORITY_ORDER:
        shares = _skill_shares(spells[spells["seniority_level"] == level])
        if shares:
            by_seniority[level] = [
                s for s, w in sorted(shares.items(), key=lambda kv: (-kv[1], kv[0])) if w >= MIN_SKILL_SHARE
            ]
    summary = career_summary(profile, employment)
    return CareerDetail(
        **summary.model_dump(),
        skills=[
            SkillFrequency(skill=s, share=w, is_core=w >= CORE_SKILL_SHARE)
            for s, w in profile.skill_weights.items()
        ],
        skills_by_seniority=by_seniority,
        salary=career_salary(employment, profile.name),
        entry_market=entry_market(employment, profile.name),
        alumni_outcomes=alumni_outcomes(alumni, profile.name, experiences),
    )
