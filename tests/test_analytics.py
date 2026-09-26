import pandas as pd
import pytest

from app.data.loader import Course
from app.data.parsing import optional_float, parse_prerequisites, split_pipe, term_sort_key
from app.services.career_matching import CORE_SKILL_SHARE, CareerProfile, match_career, match_careers
from app.services.pathway import build_pathway, implied_prerequisites, prerequisite_status
from app.services.salary import career_salary, salary_stats
from app.services.skills import extract_skills
from app.services.student_profile import StudentNotFoundError, build_profile, calculate_gpa
from app.models.career import AlumniOutcomes
from tests.conftest import ALUMNUS, FIRST_TERM, TRANSFER_JUNIOR


def transcript(rows):
    return pd.DataFrame(rows, columns=["course_id", "grade", "grade_points", "credits_attempted"])


# --- "Not Applicable" and parsing -------------------------------------------------------

def test_not_applicable_is_none_not_zero():
    assert optional_float("Not Applicable") is None
    assert optional_float("0.00") == 0.0
    assert optional_float("3.25") == 3.25


def test_split_pipe_and_prerequisites():
    assert split_pipe("Python|SQL|Data Modeling") == ["Python", "SQL", "Data Modeling"]
    assert split_pipe("Not Applicable") == []
    assert parse_prerequisites("CMSC341|MATH151 or MATH155") == [["CMSC341"], ["MATH151", "MATH155"]]
    assert parse_prerequisites("Not Applicable") == []


def test_term_sort_order():
    terms = ["Fall 2024", "Spring 2025", "Summer 2024", "Spring 2024"]
    assert sorted(terms, key=term_sort_key) == ["Spring 2024", "Summer 2024", "Fall 2024", "Spring 2025"]


# --- GPA ---------------------------------------------------------------------------------

def test_gpa_is_credit_weighted_and_excludes_w_and_ip():
    rows = transcript([
        ("A1", "A", "4.0", 4),
        ("B1", "C", "2.0", 2),
        ("F1", "F", "0.0", 3),
        ("W1", "W", "Not Applicable", 3),
        ("IP1", "IP", "Not Applicable", 4),
    ])
    # (4*4 + 2*2 + 0*3) / (4 + 2 + 3) = 20/9
    assert calculate_gpa(rows) == round(20 / 9, 2)


def test_gpa_none_when_only_in_progress():
    rows = transcript([("IP1", "IP", "Not Applicable", 4), ("W1", "W", "Not Applicable", 3)])
    assert calculate_gpa(rows) is None


def test_recomputed_gpa_matches_dataset(store):
    mismatches = 0
    for campus_id, row in store.students.iterrows():
        recorded = optional_float(row["cumulative_gpa"])
        calculated = calculate_gpa(store.transcript_for(campus_id))
        if recorded is None:
            assert calculated is None
        elif abs(recorded - calculated) > 0.011:
            mismatches += 1
    assert mismatches == 0


def test_first_term_student_has_no_gpa(store):
    profile = build_profile(store, FIRST_TERM)
    assert profile.gpa is None and profile.major_gpa is None and profile.calculated_gpa is None
    assert profile.completed_courses == []
    assert profile.credits_in_progress > 0


def test_transfer_credits_come_from_student_file(store):
    profile = build_profile(store, TRANSFER_JUNIOR)
    transcript_credits = int(store.transcript_for(TRANSFER_JUNIOR)["credits_earned"].sum())
    assert profile.credits_earned == 76
    assert profile.credits_earned > transcript_credits
    assert profile.gpa == 3.00
    assert profile.internship_count == len(profile.internships)
    assert profile.credential_count == len(profile.credentials)


def test_invalid_and_alumni_ids(store):
    with pytest.raises(StudentNotFoundError) as unknown:
        build_profile(store, "CID-000000")
    assert not unknown.value.is_alumnus
    with pytest.raises(StudentNotFoundError) as alum:
        build_profile(store, ALUMNUS)
    assert alum.value.is_alumnus


# --- Skills and matching ---------------------------------------------------------------

def test_skill_extraction_uses_catalog_tags(store):
    skills = {s.skill: s.courses for s in extract_skills({"CMSC341", "CMSC461"}, store.catalog)}
    assert skills["SQL"] == ["CMSC461"]
    assert skills["Data Structures"] == ["CMSC341"]
    assert set(skills) == set(store.catalog["CMSC341"].skills) | set(store.catalog["CMSC461"].skills)


def test_career_profiles_come_from_employment(store, profiles):
    assert set(profiles) == set(store.employment["job_family"].unique())
    assert set(profiles["Data & Analytics"].core_skills) == {"Data Modeling", "SQL", "Statistics"}
    for profile in profiles.values():
        assert all(0 < w <= 1 for w in profile.skill_weights.values())


def test_match_score_and_missing_skills():
    profile = CareerProfile("Data Engineer", 10, 10, {"SQL": 1.0, "Python": 1.0, "ETL": 0.5, "Cloud": 0.5}, [])
    match = match_career({"Python", "SQL", "Statistics"}, profile)
    assert match.score == round(100 * 2 / 3, 1)
    assert match.matched_skills == ["SQL", "Python"]
    assert match.missing_skills == ["ETL", "Cloud"]
    assert match.missing_core_skills == []
    assert match_career(set(), profile).score == 0.0


def test_ties_break_on_projected_score():
    a = CareerProfile("A", 1, 1, {"X": 1.0}, [])
    b = CareerProfile("B", 1, 1, {"Y": 1.0}, [])
    ranked = match_careers(set(), {"A": a, "B": b}, in_progress_skills={"Y"})
    assert [m.career for m in ranked] == ["B", "A"]
    assert ranked[0].score == 0.0 and ranked[0].projected_score == 100.0


# --- Salary ------------------------------------------------------------------------------

def test_salary_stats_values():
    stats = salary_stats(pd.Series([50000, 60000, 70000, 80000]))
    assert (stats.sample_size, stats.median, stats.min, stats.max) == (4, 65000, 50000, 80000)
    assert (stats.p25, stats.p75) == (57500, 72500)
    assert salary_stats(pd.Series([], dtype=float)) is None


def test_career_salary_is_nominal(store):
    result = career_salary(store.employment, "Cybersecurity")
    entry = store.employment[
        (store.employment["job_family"] == "Cybersecurity") & (store.employment["seniority_level"] == "Entry")
    ]
    assert result.entry_level.median == round(entry["annual_salary_usd"].median())
    assert result.entry_level.sample_size == len(entry)
    assert "not inflation-adjusted" in result.basis
    assert sum(y.sample_size for y in result.entry_level_by_start_year) == len(entry)


# --- Pathways ----------------------------------------------------------------------------

def _course(course_id, prereqs=(), skills=(), terms=("Fall", "Spring")):
    return Course(course_id, course_id, "X", 3, "Upper", "Elective", [], [list(g) for g in prereqs],
                  list(skills), 3.0, list(terms))


def test_or_prerequisites():
    course = _course("STAT355", prereqs=[["MATH151", "MATH155"]])
    assert prerequisite_status(course, {"MATH155"}, set())[0] == "eligible"
    assert prerequisite_status(course, set(), {"MATH151"})[0] == "eligible_after_current_term"
    status, missing = prerequisite_status(course, set(), set())
    assert status == "needs_prerequisites" and missing == ["MATH151 or MATH155"]


def test_implied_prerequisites_cover_transfer_credit(store):
    implied = implied_prerequisites({"CMSC341"}, store.catalog)
    assert {"CMSC202", "CMSC203", "CMSC201"} <= implied


def test_pathway_recommends_only_new_catalog_courses(store, profiles):
    completed = {"CMSC201", "CMSC202", "CMSC203", "CMSC341"}
    match = match_career({"Python", "Data Structures"}, profiles["Data & Analytics"])
    pathway = build_pathway(match, profiles["Data & Analytics"].skill_weights, store.catalog,
                            completed, set(), AlumniOutcomes(alumni_count=0, share_with_internship=None, first_job_remote_share=None, found_via={}))
    assert pathway.recommended_courses
    for rec in pathway.recommended_courses:
        assert rec.course_id in store.catalog
        assert rec.course_id not in completed
        assert set(rec.skills_gained) <= set(match.missing_skills)
    ids = [r.course_id for r in pathway.recommended_courses]
    assert "CMSC461" in ids  # SQL + Data Modeling, eligible after CMSC341
    statuses = [r.status for r in pathway.recommended_courses]
    assert statuses == sorted(statuses, key=["eligible", "eligible_after_current_term", "needs_prerequisites"].index)


def test_pathway_prerequisite_steps_for_first_term(store, profiles):
    from app.services.dashboard import build_dashboard

    dashboard = build_dashboard(store, profiles, FIRST_TERM)
    steps = dashboard.pathway.prerequisite_steps
    assert steps, "a first-term student should get takeable prerequisite steps"
    for step in steps:
        assert step.course_id in store.catalog
        assert step.status in {"eligible", "eligible_after_current_term"}


def test_alumni_remote_share(store):
    from app.services.career_matching import alumni_outcomes

    outcomes = alumni_outcomes(store.alumni, "Machine Learning & AI")
    cohort = store.alumni[store.alumni["first_job_family"] == "Machine Learning & AI"]
    assert outcomes.alumni_count == len(cohort)
    assert outcomes.first_job_remote_share == round(float((cohort["first_job_is_remote"] == "TRUE").mean()), 3)


def test_every_alumnus_and_student_builds(store, profiles):
    from app.services.alumni_profile import build_alumni_view
    from app.services.dashboard import build_dashboard

    for campus_id in store.alumni.index:
        view = build_alumni_view(store, profiles, campus_id)
        employed = view.alumnus.first_destination in {"Employed Full-Time", "Employed Part-Time"}
        assert (view.first_job is not None) == employed
    for campus_id in store.students.index:
        build_dashboard(store, profiles, campus_id)
