"""Degree audit: transcript grouped by requirement category, and required courses still to take."""

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import NEXT_TERM, NEXT_TERM_SEASON, term_sort_key
from app.models.degree import AuditCourse, CreditSummary, DegreeAudit, RemainingCourse, RequirementGroup
from app.services.pathway import implied_prerequisites, prerequisite_status
from app.services.student_profile import (
    IN_PROGRESS_GRADE,
    PASSING_GRADES,
    StudentNotFoundError,
    completed_course_ids,
    in_progress_course_ids,
)

CATEGORY_ORDER = ["Major Core", "Major Elective", "Supporting Coursework", "General Education", "Free Elective"]
UNSUCCESSFUL_GRADES = {"F", "W"}


def _audit_courses(rows: pd.DataFrame, store: DataStore) -> list[AuditCourse]:
    items = [
        AuditCourse(
            course_id=r.course_id,
            title=r.course_title,
            term=r.term,
            credits=int(r.credits_attempted),
            grade=r.grade,
            skills=store.catalog[r.course_id].skills if r.course_id in store.catalog else [],
        )
        for r in rows.itertuples(index=False)
    ]
    return sorted(items, key=lambda c: (term_sort_key(c.term), c.course_id))


def _latest_passing(transcript: pd.DataFrame) -> pd.DataFrame:
    passed = transcript[transcript["grade"].isin(PASSING_GRADES)]
    if passed.empty:
        return passed
    order = passed["term"].map(term_sort_key)
    return passed.loc[order.sort_values().index].drop_duplicates("course_id", keep="last")


def build_degree_audit(store: DataStore, campus_id: str) -> DegreeAudit:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))

    row = store.student_row(campus_id)
    transcript = store.transcript_for(campus_id)
    passed = _latest_passing(transcript)
    in_progress = transcript[transcript["grade"] == IN_PROGRESS_GRADE]

    categories = set(passed["requirement_category"]) | set(in_progress["requirement_category"])
    ordered = [c for c in CATEGORY_ORDER if c in categories] + sorted(categories - set(CATEGORY_ORDER))
    groups = []
    for category in ordered:
        done = passed[passed["requirement_category"] == category]
        current = in_progress[in_progress["requirement_category"] == category]
        groups.append(
            RequirementGroup(
                category=category,
                completed_credits=int(done["credits_earned"].sum()),
                in_progress_credits=int(current["credits_attempted"].sum()),
                completed=_audit_courses(done, store),
                in_progress=_audit_courses(current, store),
            )
        )

    completed = completed_course_ids(transcript)
    current_ids = in_progress_course_ids(transcript)
    implied = implied_prerequisites(completed, store.catalog)
    satisfied = completed | implied

    major = row["major"]
    required = [c for c in store.catalog.values() if major in c.required_for_majors]
    remaining = []
    for course in required:
        if course.course_id in satisfied or course.course_id in current_ids:
            continue
        status, missing = prerequisite_status(course, satisfied, current_ids)
        remaining.append(
            RemainingCourse(
                course_id=course.course_id,
                title=course.title,
                credits=course.credits,
                course_level=course.course_level,
                skills=course.skills,
                terms_offered=course.terms_offered,
                offered_next_term=NEXT_TERM_SEASON in course.terms_offered,
                status=status,
                missing_prerequisites=missing,
            )
        )
    status_rank = {"eligible": 0, "eligible_after_current_term": 1, "needs_prerequisites": 2}
    remaining.sort(key=lambda c: (status_rank[c.status], c.course_id))

    upper = sum(
        int(r.credits_earned)
        for r in passed.itertuples(index=False)
        if r.course_id in store.catalog and store.catalog[r.course_id].course_level == "Upper"
    )
    earned, needed = int(row["credits_earned"]), int(row["credits_required"])
    in_progress_credits = int(in_progress["credits_attempted"].sum())

    return DegreeAudit(
        campus_id=campus_id,
        major=major,
        track=row["track"],
        next_term=NEXT_TERM,
        credits=CreditSummary(
            earned=earned,
            required=needed,
            in_progress=in_progress_credits,
            remaining_after_current_term=max(0, needed - earned - in_progress_credits),
            upper_division_completed=upper,
            transfer_credits=max(0, earned - int(transcript["credits_earned"].sum())),
        ),
        requirement_groups=groups,
        remaining_required_courses=remaining,
        satisfied_by_prior_credit=sorted(c.course_id for c in required if c.course_id in implied),
        unsuccessful_attempts=_audit_courses(transcript[transcript["grade"].isin(UNSUCCESSFUL_GRADES)], store),
    )
