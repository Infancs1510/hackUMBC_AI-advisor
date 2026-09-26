"""Alumni view: degree record, first destination, job history, and retrospective skill match."""

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import optional_bool, optional_float, optional_str, split_pipe, term_sort_key
from app.models.alumni import AlumniProfile, AlumniResponse, FirstJob, JobSpell
from app.models.dashboard import Experience
from app.services.career_matching import CareerProfile, match_careers
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import completed_course_ids


class AlumnusNotFoundError(LookupError):
    def __init__(self, campus_id: str, is_student: bool = False):
        self.campus_id = campus_id
        self.is_student = is_student
        if is_student:
            message = f"{campus_id} is a current student; use /api/dashboard/{campus_id}."
        else:
            message = f"No alumnus with campus_id {campus_id}."
        super().__init__(message)


def _first_job(row: pd.Series) -> FirstJob | None:
    salary = optional_float(row["first_job_annual_salary_usd"])
    title = optional_str(row["first_job_title"])
    if salary is None or title is None:
        return None
    return FirstJob(
        title=title,
        job_family=row["first_job_family"],
        employer=row["first_employer"],
        industry=row["first_employer_industry"],
        region=row["first_job_region"],
        annual_salary_usd=int(salary),
        is_remote=optional_bool(row["first_job_is_remote"]),
        found_via=optional_str(row["first_job_found_via"]),
        months_to_first_job=optional_float(row["months_to_first_job"]),
    )


def _job_spells(spells: pd.DataFrame) -> list[JobSpell]:
    items = [
        JobSpell(
            job_id=r.job_id,
            job_title=r.job_title,
            job_family=r.job_family,
            seniority_level=r.seniority_level,
            employer=r.employer,
            employer_industry=r.employer_industry,
            region=r.region,
            is_remote=bool(r.is_remote),
            start_date=r.start_date,
            end_date=optional_str(r.end_date),
            is_current=bool(r.is_current),
            tenure_months=int(r.tenure_months),
            annual_salary_usd=int(r.annual_salary_usd),
            change_type=r.change_type,
            role_skills=split_pipe(r.role_skill_tags),
        )
        for r in spells.itertuples(index=False)
    ]
    return sorted(items, key=lambda j: j.start_date)


def build_alumni_view(store: DataStore, profiles: dict[str, CareerProfile], campus_id: str) -> AlumniResponse:
    if not store.is_alumnus(campus_id):
        raise AlumnusNotFoundError(campus_id, is_student=store.is_student(campus_id))

    row = store.alumnus_row(campus_id)
    skills = extract_skills(completed_course_ids(store.transcript_for(campus_id)), store.catalog)
    matches = match_careers(skill_set(skills), profiles)
    first_job = _first_job(row)
    first_family = first_job.job_family if first_job else None

    experiences = [
        Experience(
            experience_type=r.experience_type,
            name=r.experience_name,
            organization=r.organization,
            term=r.term,
            outcome=r.outcome,
        )
        for r in store.experiences_for(campus_id).itertuples(index=False)
    ]

    return AlumniResponse(
        alumnus=AlumniProfile(
            campus_id=campus_id,
            major=row["major"],
            degree_level=row["degree_level"],
            track=row["track"],
            graduation_term=row["graduation_term"],
            graduation_year=int(row["graduation_year"]),
            entry_type=row["entry_type"],
            time_to_degree_years=float(row["time_to_degree_years"]),
            total_credits_earned=int(row["total_credits_earned"]),
            final_gpa=float(row["final_gpa"]),
            major_gpa=float(row["major_gpa"]),
            holds_prior_umbc_bachelors=bool(optional_bool(row["holds_prior_umbc_bachelors"])),
            internship_count=int(row["internship_count"]),
            credential_count=int(row["credential_count"]),
            engagement_activity_count=int(row["engagement_activity_count"]),
            net_cost_usd=int(row["net_cost_usd"]),
            total_loans_usd=int(row["total_loans_usd"]),
            first_destination=row["first_destination"],
        ),
        first_job=first_job,
        employment_history=_job_spells(store.employment_for(campus_id)),
        experiences=sorted(experiences, key=lambda e: term_sort_key(e.term)),
        skills=skills,
        career_matches=matches,
        first_job_career_match=next((m for m in matches if m.career == first_family), None),
    )
