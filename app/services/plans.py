"""Next-term registration plans: catalog validation and an in-app review workflow (SQLite)."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.data.loader import DataStore
from app.data.parsing import NEXT_TERM, NEXT_TERM_SEASON
from app.models.plans import PlanCourse, PlanValidation, RegistrationPlan
from app.services.pathway import implied_prerequisites, unmet_prerequisites
from app.services.student_profile import StudentNotFoundError, completed_course_ids, in_progress_course_ids

FULL_TIME_CREDITS = 12
OVERLOAD_CREDITS = 18

SCHEMA = """
CREATE TABLE IF NOT EXISTS registration_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    term TEXT NOT NULL,
    courses TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'submitted',
    advisor_note TEXT NOT NULL DEFAULT '',
    submitted_at TEXT NOT NULL,
    decided_at TEXT,
    UNIQUE (campus_id, term)
);
"""


class PlanError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


def validate_plan(
    store: DataStore, campus_id: str, course_ids: list[str], meeting_reasons: list[str], next_required: list[str]
) -> PlanValidation:
    """Check a plan against the catalog and the student's record for next term."""
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    transcript = store.transcript_for(campus_id)
    completed = completed_course_ids(transcript)
    satisfied = completed | implied_prerequisites(completed, store.catalog)
    in_progress = in_progress_course_ids(transcript)
    major = store.student_row(campus_id)["major"]

    courses: list[PlanCourse] = []
    seen: set[str] = set()
    for raw in course_ids:
        cid = raw.strip().upper()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        course = store.catalog.get(cid)
        if course is None:
            courses.append(PlanCourse(course_id=cid, title="Not in the course catalog", credits=0, required=False,
                                      status="blocked", notes=["Not in the course catalog"]))
            continue
        notes, status = [], "ok"
        if cid in satisfied:
            notes.append("Already completed")
            status = "blocked"
        elif cid in in_progress:
            notes.append(f"In progress this term")
            status = "blocked"
        else:
            missing = unmet_prerequisites(course, satisfied | in_progress)
            if missing:
                notes.append(f"Needs {', '.join(missing)}")
                status = "blocked"
            elif unmet_prerequisites(course, satisfied):
                notes.append("Prerequisite finishing this term")
        if NEXT_TERM_SEASON not in course.terms_offered:
            notes.append(f"Usually offered {'/'.join(course.terms_offered)}, not {NEXT_TERM_SEASON}")
            if status == "ok":
                status = "warning"
        courses.append(PlanCourse(
            course_id=cid, title=course.title, credits=course.credits, required=major in course.required_for_majors,
            status=status, notes=notes or ["Prerequisites met"],
        ))

    total = sum(c.credits for c in courses)
    issues = []
    if total < FULL_TIME_CREDITS:
        issues.append(f"{total} credits — below full-time ({FULL_TIME_CREDITS}). Fine if intentional; add general education or electives otherwise.")
    elif total > OVERLOAD_CREDITS:
        issues.append(f"{total} credits — above {OVERLOAD_CREDITS}, a heavy load.")
    blocked = any(c.status == "blocked" for c in courses)
    warned = any(c.status == "warning" for c in courses)
    category = "meeting" if meeting_reasons else "prereq" if blocked or warned else "ready"
    return PlanValidation(
        term=NEXT_TERM, courses=courses, total_credits=total, issues=issues, blocked=blocked, category=category,
        meeting_reasons=meeting_reasons, missing_required=[c for c in next_required if c not in seen],
    )


class PlanStore:
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
    def _row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "campus_id": row["campus_id"], "term": row["term"], "courses": json.loads(row["courses"]),
            "note": row["note"], "status": row["status"], "advisor_note": row["advisor_note"],
            "submitted_at": datetime.fromisoformat(row["submitted_at"]),
            "decided_at": datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
        }

    def submit(self, campus_id: str, courses: list[str], note: str) -> dict:
        """Create or replace the student's plan for next term; resubmitting clears any decision."""
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn, conn:
            conn.execute(
                """INSERT INTO registration_plans (campus_id, term, courses, note, status, advisor_note, submitted_at, decided_at)
                   VALUES (?, ?, ?, ?, 'submitted', '', ?, NULL)
                   ON CONFLICT (campus_id, term) DO UPDATE SET courses = excluded.courses, note = excluded.note,
                   status = 'submitted', advisor_note = '', submitted_at = excluded.submitted_at, decided_at = NULL""",
                (campus_id, NEXT_TERM, json.dumps(courses), note.strip(), now),
            )
        return self.for_student(campus_id)

    def for_student(self, campus_id: str) -> dict | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM registration_plans WHERE campus_id = ? AND term = ?", (campus_id, NEXT_TERM)).fetchone()
        return self._row(row) if row else None

    def get(self, plan_id: int) -> dict:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM registration_plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise PlanError("Plan not found.", 404)
        return self._row(row)

    def all(self) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM registration_plans WHERE term = ? ORDER BY submitted_at", (NEXT_TERM,)).fetchall()
        return [self._row(r) for r in rows]

    def withdraw(self, campus_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM registration_plans WHERE campus_id = ? AND term = ?", (campus_id, NEXT_TERM))

    def decide(self, plan_id: int, status: str, note: str) -> dict:
        plan = self.get(plan_id)
        if plan["status"] != "submitted":
            raise PlanError("Only submitted plans can be decided.", 409)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE registration_plans SET status = ?, advisor_note = ?, decided_at = ? WHERE id = ?",
                (status, note.strip(), datetime.now(timezone.utc).isoformat(), plan_id),
            )
        return self.get(plan_id)


def to_model(plan: dict, validation: PlanValidation) -> RegistrationPlan:
    return RegistrationPlan(**plan, validation=validation)
