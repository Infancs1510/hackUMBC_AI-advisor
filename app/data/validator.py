"""Schema checks for the supplied CSVs, based on the per-file .md documentation."""

import pandas as pd

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "students": {
        "campus_id", "entry_term", "entry_type", "major", "track", "second_major", "minor",
        "class_level", "credits_earned", "credits_required", "cumulative_gpa", "major_gpa",
        "academic_standing", "expected_graduation_term", "internship_count",
        "credential_count", "engagement_activity_count",
    },
    "alumni": {
        "campus_id", "major", "first_destination", "first_job_family",
        "first_job_annual_salary_usd", "first_job_found_via", "first_job_is_remote", "internship_count",
    },
    "transcripts": {
        "campus_id", "term", "course_id", "course_title", "credits_attempted",
        "credits_earned", "grade", "grade_points", "is_repeat", "requirement_category",
    },
    "courses": {
        "course_id", "course_title", "credits", "course_level", "course_type",
        "required_for_majors", "prerequisite_ids", "skill_tags", "difficulty_index",
        "typical_terms_offered",
    },
    "experiences": {
        "record_id", "campus_id", "experience_type", "experience_name", "organization",
        "term", "outcome",
    },
    "employment": {
        "job_id", "campus_id", "job_title", "job_family", "seniority_level", "start_date",
        "end_date", "is_current", "annual_salary_usd", "role_skill_tags",
    },
}


class DataValidationError(RuntimeError):
    pass


def validate_frames(frames: dict[str, pd.DataFrame]) -> None:
    problems: list[str] = []
    for name, required in REQUIRED_COLUMNS.items():
        frame = frames.get(name)
        if frame is None:
            problems.append(f"{name}: file not loaded")
            continue
        missing = required - set(frame.columns)
        if missing:
            problems.append(f"{name}: missing columns {sorted(missing)}")

    employment = frames.get("employment")
    if employment is not None and not problems:
        # Documented invariant: end_date is blank if and only if is_current is TRUE.
        blank = employment["end_date"].isna()
        if not (blank == employment["is_current"].astype(bool)).all():
            problems.append("employment: end_date blank does not match is_current")

    if problems:
        raise DataValidationError("; ".join(problems))
