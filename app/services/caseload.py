"""Advisor caseload: one summary row per current student, with data-derived attention flags."""

import threading
from dataclasses import dataclass
from datetime import datetime

from app.data.loader import DataStore
from app.data.parsing import optional_float
from app.models.caseload import CaseloadFacets, CaseloadFlag, CaseloadResponse, CaseloadSort, CaseloadStudent
from app.services.career_matching import CareerProfile, match_careers
from app.services.degree_audit import build_degree_audit
from app.services.roadmap import build_roadmap
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import completed_course_ids

CLASS_LEVEL_ORDER = ["Freshman", "Sophomore", "Junior", "Senior"]
UPPER_CLASS = {"Junior", "Senior"}
AT_RISK_STANDINGS = {"Academic Warning", "Academic Probation"}
# Juniors' median top-match score is 50; below 30 means little overlap with any career yet.
LOW_MATCH_THRESHOLD = 30.0

FLAGS = {
    "academic_standing": "Academic warning or probation",
    "no_internship": "Junior/Senior with no internship or co-op",
    "low_career_match": f"Junior/Senior with top career match below {LOW_MATCH_THRESHOLD:g}",
    "graduation_risk": "Required courses can't all fit before expected graduation",
}
# Used to order the attention queue: standing and graduation risk matter most.
FLAG_SEVERITY = {"academic_standing": 3, "graduation_risk": 3, "no_internship": 1, "low_career_match": 1}


def _flag(code: str) -> CaseloadFlag:
    return CaseloadFlag(code=code, label=FLAGS[code])


def student_flags(
    class_level: str, standing: str, internship_count: int, top_score: float, graduation_risk: bool = False
) -> list[CaseloadFlag]:
    flags = []
    if standing in AT_RISK_STANDINGS:
        flags.append(_flag("academic_standing"))
    if graduation_risk:
        flags.append(_flag("graduation_risk"))
    if class_level in UPPER_CLASS and internship_count == 0:
        flags.append(_flag("no_internship"))
    if class_level in UPPER_CLASS and top_score < LOW_MATCH_THRESHOLD:
        flags.append(_flag("low_career_match"))
    return flags


@dataclass
class Caseload:
    students: list[CaseloadStudent]
    facets: CaseloadFacets


def build_caseload(store: DataStore, profiles: dict[str, CareerProfile]) -> Caseload:
    rows: list[CaseloadStudent] = []
    for campus_id, row in store.students.iterrows():
        skills = skill_set(extract_skills(completed_course_ids(store.transcript_for(campus_id)), store.catalog))
        top = match_careers(skills, profiles)[0] if profiles else None
        top_score = top.score if top else 0.0
        audit = build_degree_audit(store, campus_id)
        # Graduation risk depends only on degree requirements, not on any career target.
        roadmap = build_roadmap(store, profiles, campus_id, top.career if top else None, include_career_courses=False)
        late = any(t.after_expected_graduation for t in roadmap.terms)
        rows.append(
            CaseloadStudent(
                campus_id=campus_id,
                major=row["major"],
                track=row["track"],
                class_level=row["class_level"],
                gpa=optional_float(row["cumulative_gpa"]),
                credits_earned=int(row["credits_earned"]),
                academic_standing=row["academic_standing"],
                expected_graduation_term=row["expected_graduation_term"],
                internship_count=int(row["internship_count"]),
                credential_count=int(row["credential_count"]),
                # With no completed-course skills every score is 0, so there is no real top career.
                top_career=top.career if top and top_score > 0 else None,
                top_career_score=top_score,
                flags=student_flags(
                    row["class_level"], row["academic_standing"], int(row["internship_count"]), top_score, late
                ),
                remaining_required_count=len(audit.remaining_required_courses),
                next_required=[
                    c.course_id for c in audit.remaining_required_courses
                    if c.status != "needs_prerequisites" and c.offered_next_term
                ],
            )
        )

    levels = {r.class_level for r in rows}
    facets = CaseloadFacets(
        majors=sorted({r.major for r in rows}),
        tracks=sorted({r.track for r in rows}),
        class_levels=[c for c in CLASS_LEVEL_ORDER if c in levels] + sorted(levels - set(CLASS_LEVEL_ORDER)),
        standings=sorted({r.academic_standing for r in rows}),
        careers=sorted(profiles),
        flags=[_flag(code) for code in FLAGS],
        flag_counts={code: sum(any(f.code == code for f in r.flags) for r in rows) for code in FLAGS},
    )
    return Caseload(students=rows, facets=facets)


class CaseloadCache:
    """Builds the caseload on first use (a roadmap per student takes a few seconds), then reuses it."""

    def __init__(self, store: DataStore, profiles: dict[str, CareerProfile]):
        self._store, self._profiles = store, profiles
        self._value: Caseload | None = None
        self._lock = threading.Lock()

    def warm_in_background(self) -> None:
        """Start building now so the first advisor request doesn't wait."""
        threading.Thread(target=self.get, name="caseload-warmup", daemon=True).start()

    def get(self) -> Caseload:
        if self._value is None:
            with self._lock:
                if self._value is None:
                    self._value = build_caseload(self._store, self._profiles)
        return self._value


def _sort_key(sort: CaseloadSort):
    missing_last = float("inf")
    return {
        "flags": lambda r: (-sum(FLAG_SEVERITY[f.code] for f in r.flags), -len(r.flags), r.campus_id),
        "campus_id": lambda r: r.campus_id,
        "gpa_asc": lambda r: (r.gpa if r.gpa is not None else missing_last, r.campus_id),
        "gpa_desc": lambda r: (-r.gpa if r.gpa is not None else missing_last, r.campus_id),
        "match_asc": lambda r: (r.top_career_score, r.campus_id),
        "match_desc": lambda r: (-r.top_career_score, r.campus_id),
    }[sort]


def query_caseload(
    caseload: Caseload,
    *,
    q: str | None = None,
    major: str | None = None,
    track: str | None = None,
    class_level: str | None = None,
    standing: str | None = None,
    career: str | None = None,
    flag: str | None = None,
    reviewed: bool | None = None,
    flagged: bool | None = None,
    reviews: dict[str, tuple[datetime, str]] | None = None,
    sort: CaseloadSort = "flags",
    page: int = 1,
    page_size: int = 25,
) -> CaseloadResponse:
    reviews = reviews or {}
    rows = [
        r.model_copy(update={"reviewed_at": reviews[r.campus_id][0], "review_note": reviews[r.campus_id][1]})
        if r.campus_id in reviews else r
        for r in caseload.students
    ]
    if reviewed is not None:
        rows = [r for r in rows if (r.reviewed_at is not None) == reviewed]
    if flagged is not None:
        rows = [r for r in rows if bool(r.flags) == flagged]
    if q:
        needle = q.strip().upper()
        rows = [r for r in rows if needle in r.campus_id]
    if major:
        rows = [r for r in rows if r.major == major]
    if track:
        rows = [r for r in rows if r.track == track]
    if class_level:
        rows = [r for r in rows if r.class_level == class_level]
    if standing:
        rows = [r for r in rows if r.academic_standing == standing]
    if career:
        rows = [r for r in rows if r.top_career == career]
    if flag:
        rows = [r for r in rows if any(f.code == flag for f in r.flags)]
    rows = sorted(rows, key=_sort_key(sort))
    start = (page - 1) * page_size
    return CaseloadResponse(
        total=len(rows),
        page=page,
        page_size=page_size,
        students=rows[start : start + page_size],
        facets=caseload.facets,
    )
