"""Student profile facts: GPA, credits, courses, and experiences."""

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import NOT_APPLICABLE, optional_float, optional_str, term_sort_key
from app.models.dashboard import CourseRecord, Experience, StudentProfile

PASSING_GRADES = {"A", "B", "C", "D"}
EXCLUDED_FROM_GPA = {"W", "IP"}
IN_PROGRESS_GRADE = "IP"
INTERNSHIP_TYPES = {"Internship", "Co-op"}
CREDENTIAL_TYPES = {"Certification"}


class StudentNotFoundError(LookupError):
    def __init__(self, campus_id: str, is_alumnus: bool = False):
        self.campus_id = campus_id
        self.is_alumnus = is_alumnus
        if is_alumnus:
            message = f"{campus_id} is an alumnus; use /api/alumni/{campus_id}."
        else:
            message = f"No current student with campus_id {campus_id}."
        super().__init__(message)


def calculate_gpa(transcript: pd.DataFrame) -> float | None:
    """Credit-weighted GPA over graded attempts, excluding W and IP.

    Returns None (not 0.0) when there is no graded coursework, e.g. first-term students.
    """
    graded = transcript[~transcript["grade"].isin(EXCLUDED_FROM_GPA)]
    graded = graded[graded["grade_points"].astype(str) != NOT_APPLICABLE]
    if graded.empty:
        return None
    credits = graded["credits_attempted"].astype(float)
    total_credits = credits.sum()
    if total_credits == 0:
        return None
    points = graded["grade_points"].astype(float)
    return round(float((points * credits).sum() / total_credits), 2)


def completed_course_ids(transcript: pd.DataFrame) -> set[str]:
    return set(transcript.loc[transcript["grade"].isin(PASSING_GRADES), "course_id"])


def in_progress_course_ids(transcript: pd.DataFrame) -> set[str]:
    return set(transcript.loc[transcript["grade"] == IN_PROGRESS_GRADE, "course_id"])


def _course_records(rows: pd.DataFrame) -> list[CourseRecord]:
    records = [
        CourseRecord(
            course_id=r.course_id,
            title=r.course_title,
            term=r.term,
            credits=int(r.credits_attempted),
            grade=r.grade,
        )
        for r in rows.itertuples(index=False)
    ]
    return sorted(records, key=lambda c: (term_sort_key(c.term), c.course_id))


def _latest_passing_attempts(transcript: pd.DataFrame) -> pd.DataFrame:
    passed = transcript[transcript["grade"].isin(PASSING_GRADES)].copy()
    if passed.empty:
        return passed
    passed["_term_key"] = passed["term"].map(term_sort_key)
    return passed.sort_values("_term_key").drop_duplicates("course_id", keep="last").drop(columns="_term_key")


def _experiences(rows: pd.DataFrame) -> list[Experience]:
    items = [
        Experience(
            experience_type=r.experience_type,
            name=r.experience_name,
            organization=r.organization,
            term=r.term,
            outcome=r.outcome,
        )
        for r in rows.itertuples(index=False)
    ]
    return sorted(items, key=lambda e: term_sort_key(e.term))


def build_profile(store: DataStore, campus_id: str) -> StudentProfile:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))

    row = store.student_row(campus_id)
    transcript = store.transcript_for(campus_id)
    experiences = store.experiences_for(campus_id)
    in_progress = transcript[transcript["grade"] == IN_PROGRESS_GRADE]
    exp_types = experiences["experience_type"]

    return StudentProfile(
        campus_id=campus_id,
        major=row["major"],
        track=row["track"],
        second_major=optional_str(row["second_major"]),
        minor=optional_str(row["minor"]),
        class_level=row["class_level"],
        entry_term=row["entry_term"],
        entry_type=row["entry_type"],
        expected_graduation_term=row["expected_graduation_term"],
        academic_standing=row["academic_standing"],
        gpa=optional_float(row["cumulative_gpa"]),
        major_gpa=optional_float(row["major_gpa"]),
        calculated_gpa=calculate_gpa(transcript),
        credits_earned=int(row["credits_earned"]),
        credits_required=int(row["credits_required"]),
        credits_in_progress=int(in_progress["credits_attempted"].sum()),
        internship_count=int(row["internship_count"]),
        credential_count=int(row["credential_count"]),
        engagement_activity_count=int(row["engagement_activity_count"]),
        completed_courses=_course_records(_latest_passing_attempts(transcript)),
        in_progress_courses=_course_records(in_progress),
        internships=_experiences(experiences[exp_types.isin(INTERNSHIP_TYPES)]),
        credentials=_experiences(experiences[exp_types.isin(CREDENTIAL_TYPES)]),
        activities=_experiences(experiences[~exp_types.isin(INTERNSHIP_TYPES | CREDENTIAL_TYPES)]),
    )
