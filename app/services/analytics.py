"""Degree pathway analytics across all current students, from transcripts, the catalog, and the caseload.

Computed once and cached (it needs a degree audit per student). Nothing here is live registration data:
there are no seat counts or waitlists in the dataset, so demand is measured from students' records.
"""

import threading
from collections import Counter

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import NEXT_TERM, NOT_APPLICABLE
from app.models.analytics import (
    Bottleneck,
    CareerAlignment,
    Intervention,
    InterventionAction,
    InternshipInsight,
    LevelStat,
    PathwayAnalytics,
    PathwayKpis,
    TrackStat,
)
from app.services.career_matching import CareerProfile
from app.services.caseload import CLASS_LEVEL_ORDER, UPPER_CLASS, Caseload, CaseloadCache
from app.services.degree_audit import build_degree_audit
from app.services.market import market_career_shifts
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import completed_course_ids

CAPSTONES = {"Computer Science": "CMSC447", "Information Systems": "IS450"}
MIN_ATTEMPTS = 200
TOP_BOTTLENECKS = 8
FAILING = {"D", "F", "W"}
# D/F/W rate relative to the median course.
HIGH_DFW, MODERATE_DFW = 1.7, 1.4
EMPLOYED = {"Employed Full-Time", "Employed Part-Time"}


def _gpa_band(gpa: float | None) -> str:
    if gpa is None:
        return "First term"
    if gpa >= 3.5:
        return "3.50+"
    if gpa >= 3.0:
        return "3.00–3.49"
    if gpa >= 2.0:
        return "2.00–2.99"
    return "Below 2.00"


def _internship_insight(alumni: pd.DataFrame) -> InternshipInsight:
    responders = alumni[alumni["first_destination"] != "No Response"]
    employed = responders["first_destination"].isin(EMPLOYED)
    with_intern = responders["internship_count"] > 0
    salaried = alumni[alumni["first_job_annual_salary_usd"].astype(str) != NOT_APPLICABLE]
    salary = salaried["first_job_annual_salary_usd"].astype(int)
    has = salaried["internship_count"] > 0
    return InternshipInsight(
        employed_with=round(float(employed[with_intern].mean()), 3),
        employed_without=round(float(employed[~with_intern].mean()), 3),
        median_salary_with=round(float(salary[has].median())),
        median_salary_without=round(float(salary[~has].median())),
        return_offers=int((alumni["first_job_found_via"] == "Return Offer from Internship").sum()),
        responders=len(responders),
    )


def _bottlenecks(store: DataStore, caseload: Caseload) -> tuple[list[Bottleneck], float, dict[str, set[str]]]:
    t = store.transcripts
    completed = t[t["grade"] != "IP"]
    stats = completed.groupby("course_id").agg(
        attempts=("grade", "size"),
        dfw=("grade", lambda g: g.isin(FAILING).mean()),
        repeat=("is_repeat", "mean"),
    )
    stats = stats[stats["attempts"] >= MIN_ATTEMPTS]
    median = float(stats["dfw"].median())

    current = t[t["campus_id"].isin(store.students.index)]
    enrolled = current[current["grade"] == "IP"]["course_id"].value_counts()
    passed = set(zip(*current[current["grade"].isin(["A", "B", "C", "D"])][["campus_id", "course_id"]].T.values))
    retaking = set(zip(*current[current["grade"] == "IP"][["campus_id", "course_id"]].T.values))
    fw = current[current["grade"].isin(["F", "W"])]
    unresolved: dict[str, set[str]] = {}
    for cid, course in zip(fw["campus_id"], fw["course_id"]):
        if (cid, course) not in passed and (cid, course) not in retaking:
            unresolved.setdefault(course, set()).add(cid)
    demand = Counter(c for r in caseload.students for c in r.next_required)

    items = []
    for course_id, row in stats.sort_values("dfw", ascending=False).head(TOP_BOTTLENECKS).iterrows():
        course = store.catalog[course_id]
        risk = "high" if row["dfw"] >= HIGH_DFW * median else "moderate" if row["dfw"] >= MODERATE_DFW * median else "normal"
        items.append(Bottleneck(
            course_id=course_id, title=course.title, course_level=course.course_level,
            required_for=course.required_for_majors, historical_attempts=int(row["attempts"]),
            dfw_rate=round(float(row["dfw"]), 3), repeat_rate=round(float(row["repeat"]), 3),
            currently_enrolled=int(enrolled.get(course_id, 0)), next_term_demand=demand.get(course_id, 0),
            unresolved=sorted(unresolved.get(course_id, set())), risk=risk,
        ))
    return items, round(median, 3), unresolved


def _careers(store: DataStore, caseload: Caseload, profiles: dict[str, CareerProfile]) -> list[CareerAlignment]:
    skills_by_student = {
        cid: skill_set(extract_skills(completed_course_ids(store.transcript_for(cid)), store.catalog))
        for cid in store.students.index
    }
    shifts = {s.career: s for s in market_career_shifts(store)}
    top = Counter(r.top_career for r in caseload.students if r.top_career)
    out = []
    for career, profile in profiles.items():
        core = profile.core_skills
        matched = [r.campus_id for r in caseload.students if r.top_career == career]
        missing_by_student = [set(core) - skills_by_student[cid] for cid in matched]
        best, best_n = None, 0
        for course in store.catalog.values():
            n = sum(1 for missing in missing_by_student if missing & set(course.skills))
            if n > best_n:
                best, best_n = course, n
        shift = shifts.get(career)
        out.append(CareerAlignment(
            career=career, students_top_match=top.get(career, 0),
            recent_share=shift.recent_share if shift else 0.0, change_pts=shift.change_pts if shift else 0.0,
            core_skills=core, students_with_all_core=sum(1 for m in missing_by_student if not m),
            bridge_course=best.course_id if best else None, bridge_title=best.title if best else None,
            bridge_students=best_n,
        ))
    return sorted(out, key=lambda c: -c.students_top_match)


def build_pathway_analytics(store: DataStore, profiles: dict[str, CareerProfile], caseload: Caseload) -> PathwayAnalytics:
    rows = caseload.students
    risk = {r.campus_id for r in rows if any(f.code == "graduation_risk" for f in r.flags)}

    # Per-student degree audits: lower-division requirements and capstone readiness.
    foundation_done: set[str] = set()
    capstone_ready: set[str] = set()
    for r in rows:
        audit = build_degree_audit(store, r.campus_id)
        remaining = audit.remaining_required_courses
        if not any(c.course_level == "Lower" for c in remaining):
            foundation_done.add(r.campus_id)
        capstone = CAPSTONES.get(r.major)
        cap = next((c for c in remaining if c.course_id == capstone), None)
        if cap is None or cap.status != "needs_prerequisites":
            capstone_ready.add(r.campus_id)

    # Major Core average grade across current students' completed attempts.
    t = store.transcripts
    core = t[t["campus_id"].isin(store.students.index) & (t["requirement_category"] == "Major Core") & ~t["grade"].isin(["W", "IP"])]
    core = core[core["grade_points"].astype(str) != NOT_APPLICABLE]
    credits = core["credits_attempted"].astype(float)
    core_avg = round(float((core["grade_points"].astype(float) * credits).sum() / credits.sum()), 2) if len(core) else None

    upper = [r for r in rows if r.class_level in UPPER_CLASS]
    eligible = [r for r in rows if r.class_level != "Freshman"]
    kpis = PathwayKpis(
        total_students=len(rows), on_pace=len(rows) - len(risk), on_pace_share=round(1 - len(risk) / len(rows), 3),
        major_core_average=core_avg,
        gpa_bands=dict(Counter(_gpa_band(r.gpa) for r in rows)),
        foundation_eligible=len(eligible), foundation_complete=sum(1 for r in eligible if r.campus_id in foundation_done),
        upper_class=len(upper), upper_class_with_internship=sum(1 for r in upper if r.internship_count > 0),
    )

    tracks = []
    for major, track in sorted({(r.major, r.track) for r in rows}):
        members = [r for r in rows if r.major == major and r.track == track]
        gpas = [r.gpa for r in members if r.gpa is not None]
        up = [r for r in members if r.class_level in UPPER_CLASS]
        tracks.append(TrackStat(
            major=major, track=track, students=len(members),
            average_gpa=round(sum(gpas) / len(gpas), 2) if gpas else None,
            upper_class_internship_share=round(sum(1 for r in up if r.internship_count > 0) / len(up), 3) if up else None,
            capstone_course=CAPSTONES.get(major, ""), capstone_ready=sum(1 for r in up if r.campus_id in capstone_ready),
            upper_class=len(up), top_careers=Counter(r.top_career for r in members if r.top_career).most_common(2),
        ))
    tracks.sort(key=lambda t: (t.major, -t.students))

    levels = []
    for lvl in reversed(CLASS_LEVEL_ORDER):
        group = [r for r in rows if r.class_level == lvl]
        levels.append(LevelStat(
            class_level=lvl, students=len(group),
            on_pace=sum(1 for r in group if r.campus_id not in risk),
            graduation_risk=sum(1 for r in group if r.campus_id in risk),
            with_internship=sum(1 for r in group if r.internship_count > 0),
            standing_issues=sum(1 for r in group if r.academic_standing != "Good Standing"),
        ))

    insight = _internship_insight(store.alumni)
    bottlenecks, dfw_median, unresolved_by_course = _bottlenecks(store, caseload)
    careers = _careers(store, caseload, profiles)

    # Interventions: rules over the analytics above, each tied to a real action.
    interventions: list[Intervention] = []
    hardest = next((b for b in bottlenecks if b.currently_enrolled), None)
    if hardest:
        interventions.append(Intervention(
            icon="school", title=f"Check in with students in {hardest.course_id}",
            detail=f"{hardest.course_id} ({hardest.title}) has a {hardest.dfw_rate:.1%} historical D/F/W rate, versus a "
                   f"{dfw_median:.1%} median, and {hardest.currently_enrolled} current students are taking it now.",
            action=None,
        ))
    all_unresolved = sorted({cid for ids in unresolved_by_course.values() for cid in ids})
    if all_unresolved:
        top_courses = sorted(unresolved_by_course, key=lambda c: -len(unresolved_by_course[c]))[:3]
        interventions.append(Intervention(
            icon="replay", title="Follow up on unfinished courses",
            detail=f"{len(all_unresolved)} students have an F or W they haven't passed or retaken yet "
                   f"(most often {', '.join(top_courses)}).",
            action=InterventionAction(type="meetings", reason="degree_check", campus_ids=all_unresolved, label="Request meetings"),
        ))
    demand = Counter(c for r in rows for c in r.next_required).most_common(1)
    if demand:
        course, n = demand[0]
        interventions.append(Intervention(
            icon="event_seat", title=f"Plan {NEXT_TERM} capacity for {course}",
            detail=f"{n} students can take {course} ({store.catalog[course].title}) next term as a remaining requirement — "
                   f"the highest demand in the caseload. The dataset has no seat counts, so compare with section plans.",
            action=None,
        ))
    no_intern = kpis.upper_class - kpis.upper_class_with_internship
    if no_intern:
        interventions.append(Intervention(
            icon="work", title="Push internship planning for juniors and seniors",
            detail=f"{no_intern} juniors and seniors have no internship. Alumni with one were employed at "
                   f"{insight.employed_with:.0%} vs {insight.employed_without:.0%}, with a median first salary of "
                   f"${insight.median_salary_with:,} vs ${insight.median_salary_without:,} (correlation, not causation).",
            action=InterventionAction(type="roster", roster_query="flag=no_internship&reviewed=false", label="Open in roster"),
        ))
    if risk:
        interventions.append(Intervention(
            icon="event_busy", title="Review graduation timelines",
            detail=f"{len(risk)} students can't fit their remaining required courses before their expected graduation term.",
            action=InterventionAction(type="roster", roster_query="flag=graduation_risk", label="Open in roster"),
        ))

    return PathwayAnalytics(
        next_term=NEXT_TERM,
        period_note="Career trends compare alumni entry-level roles that started 2015–2020 with 2023–2026.",
        dfw_median=dfw_median, kpis=kpis, tracks=tracks, levels=levels, internship_insight=insight,
        bottlenecks=bottlenecks, careers=careers, interventions=interventions,
    )


class AnalyticsCache:
    """Pathway analytics are expensive and the dataset is static, so compute once."""

    def __init__(self, store: DataStore, profiles: dict[str, CareerProfile], caseload: CaseloadCache):
        self._store, self._profiles, self._caseload = store, profiles, caseload
        self._value: PathwayAnalytics | None = None
        self._lock = threading.Lock()

    def warm_in_background(self) -> None:
        """Build caseload then analytics at startup so advisor pages don't wait."""
        threading.Thread(target=self.get, name="analytics-warmup", daemon=True).start()

    def get(self) -> PathwayAnalytics:
        if self._value is None:
            with self._lock:
                if self._value is None:
                    self._value = build_pathway_analytics(self._store, self._profiles, self._caseload.get())
        return self._value
