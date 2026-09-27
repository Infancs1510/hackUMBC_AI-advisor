"""Assembles the dashboard payload from the profile, skill, career, salary, and pathway services."""

from app.data.loader import DataStore
from app.models.dashboard import DashboardResponse
from app.services.career_matching import CareerProfile, alumni_outcomes, match_careers, resolve_career
from app.services.pathway import build_pathway
from app.services.salary import career_salary
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import build_profile, completed_course_ids, in_progress_course_ids


class UnknownCareerError(LookupError):
    def __init__(self, career: str):
        self.career = career
        super().__init__(f"Unknown career: {career}")


def build_dashboard(
    store: DataStore,
    profiles: dict[str, CareerProfile],
    campus_id: str,
    career: str | None = None,
) -> DashboardResponse:
    profile = build_profile(store, campus_id)
    transcript = store.transcript_for(campus_id)
    completed = completed_course_ids(transcript)
    in_progress = in_progress_course_ids(transcript)

    skills = extract_skills(completed, store.catalog)
    in_progress_skills = [
        s for s in extract_skills(in_progress, store.catalog) if s.skill not in skill_set(skills)
    ]
    matches = match_careers(skill_set(skills), profiles, skill_set(in_progress_skills))

    if career is not None:
        selected = resolve_career(career, profiles)
        if selected is None:
            raise UnknownCareerError(career)
    else:
        selected = matches[0].career if matches else None

    pathway = salary = None
    if selected is not None:
        match = next(m for m in matches if m.career == selected)
        pathway = build_pathway(
            match,
            profiles[selected].skill_weights,
            store.catalog,
            completed,
            in_progress,
            alumni_outcomes(store.alumni, selected, store.experiences),
        )
        salary = career_salary(store.employment, selected)

    return DashboardResponse(
        student=profile,
        skills=skills,
        in_progress_skills=in_progress_skills,
        career_matches=matches,
        selected_career=selected,
        pathway=pathway,
        salary=salary,
    )
