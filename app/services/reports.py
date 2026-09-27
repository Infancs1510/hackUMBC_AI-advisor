"""Advisor reports: tabular exports built from the CSVs, the caseload and the app's own records.

Every report is a list of columns plus rows. Generating one saves a snapshot (SQLite) so it can be
downloaded again later exactly as it was.
"""

import json
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Callable

import pandas as pd

from app.data.loader import DataStore
from app.data.parsing import CURRENT_TERM, NEXT_TERM
from app.models.reports import (
    Cell,
    DataSnapshot,
    ReportCatalog,
    ReportChartBar,
    ReportInfo,
    ReportMetric,
    ReportRun,
    ReportRunSummary,
)
from app.services.advising import AdvisingStore
from app.services.appointments import AppointmentService
from app.services.caseload import AT_RISK_STANDINGS, Caseload
from app.services.plans import PlanStore

RECORDS_AS_OF = "2026-09-15"
KEEP_RUNS = 30
PASSING = {"A", "B", "C"}
DFW = {"D", "F", "W"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    columns TEXT NOT NULL,
    rows TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    generated_by TEXT NOT NULL
);
"""


class ReportError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


@dataclass
class ReportContext:
    store: DataStore
    caseload: Caseload
    appointments: AppointmentService
    advising: AdvisingStore
    plans: PlanStore


Table = tuple[list[str], list[list[Cell]]]


def _pct(part: float, whole: float) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _flags(row) -> str:
    return "; ".join(f.label for f in row.flags)


# --- report builders ---------------------------------------------------------------------

def caseload_progress(ctx: ReportContext) -> Table:
    required = ctx.store.students["credits_required"].astype(int)
    cols = ["campus_id", "major", "track", "class_level", "gpa", "academic_standing", "credits_earned",
            "credits_required", "credits_pct", "remaining_required_courses", "next_term_required",
            "expected_graduation_term", "top_career_match", "flags"]
    rows = [[
        s.campus_id, s.major, s.track, s.class_level, s.gpa, s.academic_standing, s.credits_earned,
        int(required[s.campus_id]), _pct(min(s.credits_earned, required[s.campus_id]), required[s.campus_id]),
        s.remaining_required_count, " ".join(s.next_required), s.expected_graduation_term, s.top_career or "", _flags(s),
    ] for s in ctx.caseload.students]
    return cols, rows


def attention_roster(ctx: ReportContext) -> Table:
    reviews = ctx.advising.reviews()
    upcoming = {a.campus_id: a for a in ctx.appointments.list_for(None, upcoming_only=True)}
    requested = {r.campus_id for r in ctx.advising.requests()}
    cols = ["campus_id", "class_level", "major", "track", "gpa", "academic_standing", "graduation_risk",
            "expected_graduation_term", "remaining_required_courses", "reviewed_on", "review_note",
            "meeting_requested", "next_appointment"]
    rows = []
    for s in ctx.caseload.students:
        risk = any(f.code == "graduation_risk" for f in s.flags)
        if s.academic_standing not in AT_RISK_STANDINGS and not risk:
            continue
        review = reviews.get(s.campus_id)
        appt = upcoming.get(s.campus_id)
        rows.append([
            s.campus_id, s.class_level, s.major, s.track, s.gpa, s.academic_standing, "Yes" if risk else "No",
            s.expected_graduation_term, s.remaining_required_count,
            review[0].date().isoformat() if review else "", review[1] if review else "",
            "Yes" if s.campus_id in requested else "No", appt.start.isoformat() if appt else "",
        ])
    rows.sort(key=lambda r: (r[5] != "Academic Probation", r[5] != "Academic Warning", r[4] if r[4] is not None else 5))
    return cols, rows


def _gateway_courses(store: DataStore) -> list[str]:
    return sorted(c.course_id for c in store.catalog.values() if c.course_level == "Lower" and c.course_type == "Core")


def gateway_outcomes(ctx: ReportContext) -> Table:
    t = ctx.store.transcripts
    t = t[t["course_id"].isin(_gateway_courses(ctx.store)) & (t["grade"] != "IP")]
    cols = ["course_id", "title", "graded_attempts", "students", "pass_rate_pct", "dfw_rate_pct", "d", "f", "w",
            "repeat_attempts", "students_with_2plus_attempts"]
    rows = []
    for cid, g in t.groupby("course_id"):
        grades = Counter(g["grade"])
        attempts = len(g)
        per_student = g.groupby("campus_id").size()
        rows.append([
            cid, ctx.store.catalog[cid].title, attempts, int(per_student.size),
            _pct(sum(grades[x] for x in PASSING), attempts), _pct(sum(grades[x] for x in DFW), attempts),
            grades["D"], grades["F"], grades["W"], int(g["is_repeat"].astype(str).str.upper().eq("TRUE").sum()),
            int((per_student >= 2).sum()),
        ])
    rows.sort(key=lambda r: -(r[5] or 0))
    return cols, rows


def course_demand(ctx: ReportContext) -> Table:
    demand: dict[str, Counter] = defaultdict(Counter)
    for s in ctx.caseload.students:
        for cid in s.next_required:
            demand[cid][s.class_level] += 1
    levels = ["Freshman", "Sophomore", "Junior", "Senior"]
    cols = ["course_id", "title", "credits", "students_needing_next_term", *[f"{lvl.lower()}s" for lvl in levels],
            "usually_offered"]
    rows = [[
        cid, ctx.store.catalog[cid].title, ctx.store.catalog[cid].credits, sum(c.values()), *[c[lvl] for lvl in levels],
        "/".join(ctx.store.catalog[cid].terms_offered),
    ] for cid, c in demand.items()]
    rows.sort(key=lambda r: -r[3])
    return cols, rows


def career_alignment(ctx: ReportContext) -> Table:
    groups: dict[tuple, list[float]] = defaultdict(list)
    totals = Counter((s.major, s.track) for s in ctx.caseload.students)
    for s in ctx.caseload.students:
        groups[(s.major, s.track, s.top_career or "No match yet")].append(s.top_career_score)
    cols = ["major", "track", "top_career_match", "students", "share_of_track_pct", "median_match_score"]
    rows = [[major, track, career, len(scores), _pct(len(scores), totals[(major, track)]), round(median(scores), 1)]
            for (major, track, career), scores in groups.items()]
    rows.sort(key=lambda r: (r[0], r[1], -r[3]))
    return cols, rows


def alumni_outcomes(ctx: ReportContext) -> Table:
    a = ctx.store.alumni
    employed = a[a["first_destination"].isin(["Employed Full-Time", "Employed Part-Time"])]
    salary = pd.to_numeric(employed["first_job_annual_salary_usd"], errors="coerce")
    months = pd.to_numeric(employed["months_to_first_job"], errors="coerce")
    interns = pd.to_numeric(employed["internship_count"], errors="coerce")
    cols = ["first_job_family", "alumni", "median_first_salary_usd_nominal", "salary_sample", "median_months_to_first_job",
            "share_with_internship_pct", "top_employer"]
    rows = []
    for family, idx in employed.groupby("first_job_family").groups.items():
        s, m, i = salary[idx].dropna(), months[idx].dropna(), interns[idx].dropna()
        rows.append([
            family, len(idx), int(s.median()) if len(s) else None, len(s), round(float(m.median()), 1) if len(m) else None,
            _pct(int((i > 0).sum()), len(i)), employed.loc[idx, "first_employer"].value_counts().index[0],
        ])
    rows.sort(key=lambda r: -r[1])
    return cols, rows


def advising_activity(ctx: ReportContext) -> Table:
    cols = ["date", "type", "campus_id", "status", "detail"]
    rows: list[list[Cell]] = []
    for a in ctx.appointments.list_for(None, upcoming_only=False):
        rows.append([a.start.isoformat(), "Appointment", a.campus_id, a.status,
                     f"{a.reason_label} ({'virtual' if a.modality == 'virtual' else 'in person'})"])
    for r in ctx.advising.requests(open_only=False):
        rows.append([r.created_at.isoformat(), "Meeting request", r.campus_id, r.status, r.reason_label])
    for p in ctx.plans.all():
        rows.append([(p["decided_at"] or p["submitted_at"]).isoformat(), "Course plan", p["campus_id"], p["status"],
                     f"{p['term']}: {' '.join(p['courses'])}"])
    for cid, (when, note) in ctx.advising.reviews().items():
        rows.append([when.isoformat(), "Caseload review", cid, "reviewed", note])
    rows.sort(key=lambda r: r[0], reverse=True)
    return cols, rows


# --- catalog -----------------------------------------------------------------------------

@dataclass
class ReportSpec:
    key: str
    title: str
    category: str
    description: str
    build: Callable[[ReportContext], Table]
    metric: Callable[[list[str], list[list[Cell]]], ReportMetric]
    chart: Callable[[list[list[Cell]]], list[ReportChartBar]] | None = None


def _progress_metric(cols, rows):
    values = [r[cols.index("credits_pct")] for r in rows]
    return ReportMetric(label="Average share of degree credits earned", value=f"{sum(values) / len(values):.1f}%")


def _count_metric(label: str, empty: str = "None"):
    return lambda cols, rows: ReportMetric(label=label, value=f"{len(rows):,}" if rows else empty)


def _top_metric(label: str, name_col: str, value_col: str, fmt: str):
    def metric(cols, rows):
        if not rows:
            return ReportMetric(label=label, value="—")
        r = rows[0]
        return ReportMetric(label=label, value=fmt.format(name=r[cols.index(name_col)], value=r[cols.index(value_col)]))
    return metric


def _bars(name_idx: int, value_idx: int, n: int = 6):
    return lambda rows: [ReportChartBar(label=str(r[name_idx]), value=int(r[value_idx])) for r in rows[:n]]


def _activity_metric(cols, rows):
    counts = Counter(r[1] for r in rows)
    return ReportMetric(label="Records", value=f"{counts['Appointment']} appts · {counts['Meeting request']} requests · {counts['Course plan']} plans")


def _alignment_metric(cols, rows):
    counts = Counter()
    for r in rows:
        if r[2] != "No match yet":
            counts[r[2]] += r[3]
    top = counts.most_common(1)
    return ReportMetric(label="Most common top match", value=f"{top[0][0]} ({top[0][1]:,} students)" if top else "—")


REPORTS: list[ReportSpec] = [
    ReportSpec("caseload_progress", "Caseload degree progress", "Advising",
               "Every current student: credits earned vs. required, remaining required courses, what they can take next term, expected graduation, top career match and attention flags.",
               caseload_progress, _progress_metric),
    ReportSpec("attention_roster", "Standing & graduation-risk roster", "Triage",
               "Students on academic warning or probation, or whose remaining required courses can't all fit before expected graduation — with your review notes, meeting requests and booked appointments.",
               attention_roster, _count_metric("Students needing attention")),
    ReportSpec("gateway_outcomes", "Gateway course outcomes", "Curriculum",
               "Lower-level core courses across every transcript in the dataset (current students and alumni): graded attempts, pass rate (A–C), D/F/W rate and repeats. In-progress grades are excluded.",
               gateway_outcomes, _top_metric("Highest D/F/W rate", "course_id", "dfw_rate_pct", "{name}: {value}%")),
    ReportSpec("career_alignment", "Career alignment by track", "Careers",
               "For each major and track, which career each student's completed courses match best, and how strongly.",
               career_alignment, _alignment_metric),
    ReportSpec("alumni_outcomes", "Alumni first-job outcomes", "Careers",
               "Employed alumni by first job family: median first salary (nominal dollars, not inflation-adjusted), months to first job, internship share and most common employer.",
               alumni_outcomes, _top_metric("Largest first-job family", "first_job_family", "alumni", "{name} ({value:,})")),
    ReportSpec("advising_activity", "Advising activity log", "Activity",
               "Everything recorded in this app: appointments, meeting requests, course plan submissions and decisions, and caseload reviews, newest first.",
               advising_activity, _activity_metric),
    ReportSpec("course_demand", f"{NEXT_TERM} required-course demand", "Curriculum",
               f"Remaining required courses each student can take in {NEXT_TERM} (prerequisites met or in progress, course offered that term), counted by class level. Use it to anticipate seat demand — it is not registration data.",
               course_demand, _top_metric("Highest demand", "course_id", "students_needing_next_term", "{name}: {value:,} students"),
               _bars(0, 3)),
]
SPECS = {r.key: r for r in REPORTS}


def build_report(ctx: ReportContext, key: str) -> Table:
    spec = SPECS.get(key)
    if spec is None:
        raise ReportError(f"Unknown report: {key}", 404)
    return spec.build(ctx)


def report_catalog(ctx: ReportContext) -> ReportCatalog:
    infos = []
    for spec in REPORTS:
        cols, rows = spec.build(ctx)
        infos.append(ReportInfo(
            key=spec.key, title=spec.title, category=spec.category, description=spec.description, columns=cols,
            metric=spec.metric(cols, rows), chart=spec.chart(rows) if spec.chart else [],
        ))
    s = ctx.store
    return ReportCatalog(reports=infos, snapshot=DataSnapshot(
        records_as_of=RECORDS_AS_OF, current_term=CURRENT_TERM, next_term=NEXT_TERM,
        students=len(s.students), alumni=len(s.alumni), transcript_rows=len(s.transcripts), employment_rows=len(s.employment),
        appointments=len(ctx.appointments.list_for(None, upcoming_only=False)),
        meeting_requests=len(ctx.advising.requests(open_only=False)), plans=len(ctx.plans.all()),
        reviews=len(ctx.advising.reviews()),
    ))


# --- saved runs ---------------------------------------------------------------------------

class ReportStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _summary(row: sqlite3.Row) -> ReportRunSummary:
        return ReportRunSummary(
            id=row["id"], key=row["key"], title=row["title"], category=row["category"],
            row_count=row["row_count"], generated_at=datetime.fromisoformat(row["generated_at"]),
            generated_by=row["generated_by"],
        )

    def save(self, spec_key: str, table: Table, generated_by: str) -> ReportRun:
        spec = SPECS[spec_key]
        cols, rows = table
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO report_runs (key, title, category, columns, rows, row_count, generated_at, generated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (spec.key, spec.title, spec.category, json.dumps(cols), json.dumps(rows), len(rows),
                 datetime.now(timezone.utc).isoformat(), generated_by),
            )
            new_id = cur.lastrowid
            conn.execute(
                "DELETE FROM report_runs WHERE id NOT IN (SELECT id FROM report_runs ORDER BY id DESC LIMIT ?)", (KEEP_RUNS,)
            )
        return self.get(new_id)

    def get(self, run_id: int) -> ReportRun:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM report_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise ReportError("Report not found — older reports are removed after the most recent 30.", 404)
        return ReportRun(**self._summary(row).model_dump(), columns=json.loads(row["columns"]), rows=json.loads(row["rows"]))

    def history(self) -> list[ReportRunSummary]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, key, title, category, row_count, generated_at, generated_by FROM report_runs ORDER BY id DESC"
            ).fetchall()
        return [self._summary(r) for r in rows]

    def delete(self, run_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            if conn.execute("DELETE FROM report_runs WHERE id = ?", (run_id,)).rowcount == 0:
                raise ReportError("Report not found.", 404)
