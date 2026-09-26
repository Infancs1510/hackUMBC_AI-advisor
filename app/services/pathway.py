"""Course pathways: missing career skills -> catalog courses that teach them."""

from app.data.loader import Course
from app.data.parsing import NEXT_TERM, NEXT_TERM_SEASON
from app.models.career import AlumniOutcomes
from app.models.dashboard import CareerMatch, CourseRecommendation, Pathway, PrerequisiteStep

MAX_RECOMMENDATIONS = 6
MAX_PREREQ_DEPTH = 6

STATUS_ELIGIBLE = "eligible"
STATUS_AFTER_CURRENT_TERM = "eligible_after_current_term"
STATUS_NEEDS_PREREQS = "needs_prerequisites"
_STATUS_RANK = {STATUS_ELIGIBLE: 0, STATUS_AFTER_CURRENT_TERM: 1, STATUS_NEEDS_PREREQS: 2}


def implied_prerequisites(completed: set[str], catalog: dict[str, Course]) -> set[str]:
    """Courses that must have been satisfied for the student to have passed what they passed.

    Transfer credit never appears in transcripts, so a transfer student may have passed CMSC202
    with no CMSC201 row. Single-course prerequisite groups are followed transitively; ' or '
    groups are ambiguous and are not inferred.
    """
    implied: set[str] = set()
    stack = list(completed)
    while stack:
        course = catalog.get(stack.pop())
        if course is None:
            continue
        for group in course.prerequisites:
            if len(group) == 1 and group[0] not in implied and group[0] not in completed:
                implied.add(group[0])
                stack.append(group[0])
    return implied


def unmet_prerequisites(course: Course, satisfied: set[str]) -> list[str]:
    """Prerequisite groups not met by `satisfied`; alternatives are joined with ' or '."""
    return [
        " or ".join(group)
        for group in course.prerequisites
        if not any(alt in satisfied for alt in group)
    ]


def prerequisite_status(course: Course, satisfied: set[str], in_progress: set[str]) -> tuple[str, list[str]]:
    missing = unmet_prerequisites(course, satisfied)
    if not missing:
        return STATUS_ELIGIBLE, []
    after_term = unmet_prerequisites(course, satisfied | in_progress)
    if not after_term:
        return STATUS_AFTER_CURRENT_TERM, missing
    return STATUS_NEEDS_PREREQS, after_term


def recommend_courses(
    match: CareerMatch,
    weights: dict[str, float],
    catalog: dict[str, Course],
    satisfied: set[str],
    in_progress: set[str],
    limit: int = MAX_RECOMMENDATIONS,
) -> list[CourseRecommendation]:
    missing = set(match.missing_skills)
    candidates: list[tuple[tuple, CourseRecommendation]] = []
    for course in catalog.values():
        if course.course_id in satisfied or course.course_id in in_progress:
            continue
        gained = [s for s in course.skills if s in missing]
        if not gained:
            continue
        status, missing_prereqs = prerequisite_status(course, satisfied, in_progress)
        offered_next = NEXT_TERM_SEASON in course.terms_offered
        rec = CourseRecommendation(
            course_id=course.course_id,
            title=course.title,
            credits=course.credits,
            course_level=course.course_level,
            course_type=course.course_type,
            difficulty_index=course.difficulty_index,
            terms_offered=course.terms_offered,
            offered_next_term=offered_next,
            skills_gained=gained,
            status=status,
            missing_prerequisites=missing_prereqs,
        )
        coverage = sum(weights.get(s, 0.0) for s in gained)
        key = (_STATUS_RANK[status], -round(coverage, 3), not offered_next, course.difficulty_index, course.course_id)
        candidates.append((key, rec))
    candidates.sort(key=lambda kv: kv[0])
    return [rec for _, rec in candidates[:limit]]


def prerequisite_steps(
    recommendations: list[CourseRecommendation],
    catalog: dict[str, Course],
    satisfied: set[str],
    in_progress: set[str],
) -> list[PrerequisiteStep]:
    """Takeable courses that lead toward recommendations still blocked by prerequisites."""
    unlocks: dict[str, set[str]] = {}

    def walk(course_id: str, target: str, depth: int) -> None:
        course = catalog.get(course_id)
        if course is None or depth > MAX_PREREQ_DEPTH:
            return
        status, _ = prerequisite_status(course, satisfied, in_progress)
        if status != STATUS_NEEDS_PREREQS:
            unlocks.setdefault(course_id, set()).add(target)
            return
        for group in course.prerequisites:
            if any(alt in satisfied or alt in in_progress for alt in group):
                continue
            # Prefer an alternative that can be taken now; otherwise follow the first one.
            ready = [
                alt for alt in group
                if alt in catalog and prerequisite_status(catalog[alt], satisfied, in_progress)[0] != STATUS_NEEDS_PREREQS
            ]
            walk((ready or group)[0], target, depth + 1)

    for rec in recommendations:
        if rec.status == STATUS_NEEDS_PREREQS:
            walk(rec.course_id, rec.course_id, 0)

    steps = []
    for course_id, targets in unlocks.items():
        course = catalog[course_id]
        status, _ = prerequisite_status(course, satisfied, in_progress)
        steps.append(
            PrerequisiteStep(
                course_id=course_id,
                title=course.title,
                status=status,
                offered_next_term=NEXT_TERM_SEASON in course.terms_offered,
                unlocks=sorted(targets),
            )
        )
    return sorted(steps, key=lambda s: (_STATUS_RANK[s.status], -len(s.unlocks), s.course_id))


def build_pathway(
    match: CareerMatch,
    weights: dict[str, float],
    catalog: dict[str, Course],
    completed: set[str],
    in_progress: set[str],
    outcomes: AlumniOutcomes,
) -> Pathway:
    satisfied = completed | implied_prerequisites(completed, catalog)
    recommendations = recommend_courses(match, weights, catalog, satisfied, in_progress)
    taught = {skill for course in catalog.values() for skill in course.skills}
    return Pathway(
        career=match.career,
        next_term=NEXT_TERM,
        current_skills_matched=match.matched_skills,
        missing_skills=match.missing_skills,
        recommended_courses=recommendations,
        prerequisite_steps=prerequisite_steps(recommendations, catalog, satisfied, in_progress),
        skills_not_covered_by_catalog=[s for s in match.missing_skills if s not in taught],
        alumni_outcomes=outcomes,
    )
