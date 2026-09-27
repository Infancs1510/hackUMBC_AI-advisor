"""Suggested term-by-term plan toward graduation and a target career.

1. Targets: remaining required courses for the major, plus career courses for missing skills chosen
   by a cost-aware greedy set cover: value = weighted skill coverage / (1 + prerequisites it adds),
   within a budget of EXTRA_COURSE_BUDGET courses (career courses plus their prerequisites).
2. Unmet prerequisites of targets are added transitively.
3. Courses are placed Spring/Fall from the next term, when offered that season and once all
   prerequisites are complete in an earlier term, up to MAX_COURSES_PER_TERM per term. Courses the
   degree needs go before career electives; within each group, courses that unlock the longest chains
   of other planned courses go first.
"""

from app.data.loader import Course, DataStore
from app.data.parsing import CURRENT_TERM, NEXT_TERM, term_sort_key
from app.models.roadmap import PlannedCourse, PlannedTerm, Roadmap
from app.services.career_matching import CareerProfile, match_career, match_careers, resolve_career
from app.services.dashboard import UnknownCareerError
from app.services.pathway import implied_prerequisites
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import StudentNotFoundError, completed_course_ids, in_progress_course_ids

MAX_COURSES_PER_TERM = 4
MAX_PLANNED_TERMS = 8
# Roughly the upper-level elective slots a student has; keeps plans within a normal degree.
EXTRA_COURSE_BUDGET = 6
_REASON_RANK = {"required": 0, "prerequisite": 1, "career": 2}


def _next_regular_term(term: str) -> str:
    """Spring -> Fall of the same year, Fall -> Spring of the next (summers are skipped)."""
    season, year = term.split()
    return f"Fall {year}" if season == "Spring" else f"Spring {int(year) + 1}"


def _prereqs_met(course: Course, done: set[str]) -> bool:
    return all(any(alt in done for alt in group) for group in course.prerequisites)


def _unmet_chain(cid: str, catalog: dict[str, Course], have: set[str]) -> set[str]:
    """Courses that must be added so `cid` can be taken, given courses already taken or planned."""
    chain: set[str] = set()
    stack = [cid]
    while stack:
        course = catalog.get(stack.pop())
        if course is None:
            continue
        for group in course.prerequisites:
            if any(alt in have or alt in chain for alt in group):
                continue
            pick = next((alt for alt in group if alt in catalog), None)
            if pick:
                chain.add(pick)
                stack.append(pick)
    return chain


def _cover_missing_skills(
    missing: dict[str, float], catalog: dict[str, Course], planned: set[str], budget: int
) -> list[str]:
    """Cost-aware greedy weighted set cover; returns chosen career courses (prerequisites are added later)."""
    uncovered = dict(missing)
    have = set(planned)
    chosen: list[str] = []
    while uncovered and budget > 0:
        best, best_value, best_cost = None, 0.0, 0
        for course in sorted(catalog.values(), key=lambda c: (c.difficulty_index, c.course_id)):
            if course.course_id in have:
                continue
            gain = sum(uncovered.get(s, 0.0) for s in course.skills)
            if gain <= 0:
                continue
            chain = _unmet_chain(course.course_id, catalog, have)
            cost = 1 + len(chain)
            if cost <= budget and gain / cost > best_value + 1e-9:
                best, best_value, best_cost = course, gain / cost, cost
        if best is None:
            break
        chosen.append(best.course_id)
        have |= {best.course_id} | _unmet_chain(best.course_id, catalog, have)
        budget -= best_cost
        for skill in best.skills:
            uncovered.pop(skill, None)
    return chosen


def _chain_heights(pending: set[str], catalog: dict[str, Course]) -> dict[str, int]:
    """Longest chain of pending courses that depend on each course (0 = nothing waits on it)."""
    dependents = {cid: [d for d in pending if any(cid in g for g in catalog[d].prerequisites)] for cid in pending}
    heights: dict[str, int] = {}

    def height(cid: str, seen: frozenset = frozenset()) -> int:
        if cid not in heights:
            heights[cid] = max((1 + height(d, seen | {cid}) for d in dependents[cid] if d not in seen), default=0)
        return heights[cid]

    for cid in pending:
        height(cid)
    return heights


def build_roadmap(
    store: DataStore,
    profiles: dict[str, CareerProfile],
    campus_id: str,
    career: str | None = None,
    include_career_courses: bool = True,
) -> Roadmap:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    row = store.student_row(campus_id)
    catalog = store.catalog
    transcript = store.transcript_for(campus_id)
    completed = completed_course_ids(transcript)
    in_progress = in_progress_course_ids(transcript)
    satisfied = completed | implied_prerequisites(completed, catalog)
    have = skill_set(extract_skills(completed, catalog))
    in_progress_skills = skill_set(extract_skills(in_progress, catalog))

    if career is None:
        career = match_careers(have, profiles, in_progress_skills)[0].career
    else:
        resolved = resolve_career(career, profiles)
        if resolved is None:
            raise UnknownCareerError(career)
        career = resolved
    profile = profiles[career]
    weights = profile.skill_weights

    # 1. Targets.
    taken = satisfied | in_progress
    reasons: dict[str, str] = {
        c.course_id: "required"
        for c in catalog.values()
        if row["major"] in c.required_for_majors and c.course_id not in taken
    }
    after_current = have | in_progress_skills
    required_skills = {s for cid in reasons for s in catalog[cid].skills}
    missing = {s: w for s, w in weights.items() if s not in after_current and s not in required_skills}
    required_ids = set(reasons)
    if include_career_courses:
        for cid in _cover_missing_skills(missing, catalog, taken | set(reasons), EXTRA_COURSE_BUDGET):
            reasons[cid] = "career"

    # 2. Prerequisite closure.
    stack = list(reasons)
    while stack:
        course = catalog[stack.pop()]
        for group in course.prerequisites:
            if any(alt in taken or alt in reasons for alt in group):
                continue
            pick = next((alt for alt in group if alt in catalog), None)
            if pick:
                reasons[pick] = "prerequisite"
                stack.append(pick)

    # 3. Schedule.
    def planned(cid: str, reason: str, known: set[str]) -> PlannedCourse:
        course = catalog[cid]
        return PlannedCourse(
            course_id=cid, title=course.title, credits=course.credits, reason=reason,
            skills_gained=[s for s in course.skills if s in weights and s not in known],
        )

    grad = row["expected_graduation_term"]
    known = set(have)
    terms: list[PlannedTerm] = []
    current = [planned(cid, "in_progress", known) for cid in sorted(in_progress) if cid in catalog]
    known |= in_progress_skills
    terms.append(PlannedTerm(
        term=CURRENT_TERM, status="in_progress", courses=current, credits=sum(c.credits for c in current),
        score_after=match_career(known, profile).score, after_expected_graduation=False,
    ))

    done = set(taken)
    pending = dict(reasons)
    heights = _chain_heights(set(pending), catalog)
    # Courses the degree needs (required ones and everything they depend on) are never displaced by electives.
    degree_critical = set(required_ids)
    for cid in required_ids:
        degree_critical |= _unmet_chain(cid, catalog, taken)
    term = NEXT_TERM
    for _ in range(MAX_PLANNED_TERMS):
        if not pending:
            break
        season = term.split()[0]
        late = term_sort_key(term) > term_sort_key(grad)
        ready = [
            cid for cid in pending
            if season in catalog[cid].terms_offered and _prereqs_met(catalog[cid], done)
            # After expected graduation only degree requirements are still worth planning.
            and (not late or pending[cid] == "required")
        ]
        ready.sort(key=lambda cid: (
            cid not in degree_critical, -heights[cid], _REASON_RANK[pending[cid]], catalog[cid].course_level != "Lower", cid,
        ))
        picked = ready[:MAX_COURSES_PER_TERM]
        if picked:
            courses = [planned(cid, pending[cid], known) for cid in picked]
            for cid in picked:
                known |= set(catalog[cid].skills)
                pending.pop(cid)
            done |= set(picked)
            terms.append(PlannedTerm(
                term=term, status="planned", courses=courses, credits=sum(c.credits for c in courses),
                score_after=match_career(known, profile).score,
                after_expected_graduation=late,
            ))
        term = _next_regular_term(term)
        if late and not any(r == "required" for r in pending.values()):
            break

    taught = {s for c in catalog.values() for s in c.skills}
    unplaced_skills = [s for s in weights if s not in known and s in taught]
    return Roadmap(
        campus_id=campus_id,
        career=career,
        expected_graduation_term=grad,
        score_now=match_career(have, profile).score,
        score_after_plan=match_career(known, profile).score,
        terms=terms,
        skills_not_covered=[s for s in weights if s not in taught],
        unscheduled=sorted(pending),
        skills_after_plan_missing=unplaced_skills,
    )
