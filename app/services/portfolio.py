"""Resume and portfolio storage (app-created data, in the app SQLite database) and the verified portfolio."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app.data.loader import DataStore
from app.data.parsing import term_sort_key
from app.models.resume import Project, ResumeRecord, VerifiedItem
from app.services.resume import PORTFOLIO_EXPERIENCES
from app.services.student_profile import StudentNotFoundError, completed_course_ids

MAX_PROJECTS = 12

SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    campus_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    text TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    link TEXT,
    skills TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class PortfolioError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


class PortfolioStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # --- resume (only the latest version is kept) --------------------------------------

    def save_resume(self, campus_id: str, filename: str, text: str, size_bytes: int) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR REPLACE INTO resumes (campus_id, filename, text, size_bytes, uploaded_at) VALUES (?, ?, ?, ?, ?)",
                (campus_id, filename, text, size_bytes, datetime.now(timezone.utc).isoformat()),
            )

    def get_resume(self, campus_id: str) -> tuple[ResumeRecord, str] | None:
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT * FROM resumes WHERE campus_id = ?", (campus_id,)).fetchone()
        if row is None:
            return None
        record = ResumeRecord(
            filename=row["filename"], uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
            size_bytes=row["size_bytes"], word_count=len(row["text"].split()),
        )
        return record, row["text"]

    def delete_resume(self, campus_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM resumes WHERE campus_id = ?", (campus_id,))

    # --- self-reported projects --------------------------------------------------------

    def _project(self, row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"], title=row["title"], description=row["description"], link=row["link"],
            skills=json.loads(row["skills"]), created_at=datetime.fromisoformat(row["created_at"]),
        )

    def projects(self, campus_id: str) -> list[Project]:
        with closing(self._connect()) as conn:
            rows = conn.execute("SELECT * FROM projects WHERE campus_id = ? ORDER BY id DESC", (campus_id,)).fetchall()
        return [self._project(r) for r in rows]

    def add_project(self, campus_id: str, title: str, description: str, link: str | None, skills: list[str]) -> Project:
        if len(self.projects(campus_id)) >= MAX_PROJECTS:
            raise PortfolioError(f"You can add up to {MAX_PROJECTS} projects.", 409)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO projects (campus_id, title, description, link, skills, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (campus_id, title.strip(), description.strip(), link, json.dumps(skills), datetime.now(timezone.utc).isoformat()),
            )
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._project(row)

    def delete_project(self, campus_id: str, project_id: int) -> None:
        with closing(self._connect()) as conn, conn:
            deleted = conn.execute("DELETE FROM projects WHERE id = ? AND campus_id = ?", (project_id, campus_id)).rowcount
        if not deleted:
            raise PortfolioError("Project not found.", 404)


def verified_portfolio(store: DataStore, campus_id: str) -> list[VerifiedItem]:
    """Portfolio items that come straight from the student's record."""
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    items: list[VerifiedItem] = []
    experiences = store.experiences_for(campus_id)
    for r in experiences.itertuples(index=False):
        if r.experience_type in PORTFOLIO_EXPERIENCES or r.experience_type == "Certification":
            items.append(VerifiedItem(
                kind="experience", category=r.experience_type, title=r.experience_name,
                subtitle=r.organization, term=r.term, outcome=r.outcome, skills=[],
            ))
    transcript = store.transcript_for(campus_id)
    passed = transcript[transcript["course_id"].isin(completed_course_ids(transcript))]
    for r in passed.drop_duplicates("course_id", keep="last").itertuples(index=False):
        course = store.catalog.get(r.course_id)
        if course and course.course_level == "Upper":
            items.append(VerifiedItem(
                kind="coursework", category="Upper-level course", title=f"{course.course_id} · {course.title}",
                subtitle=f"Grade {r.grade} · {course.credits} credits", term=r.term, outcome=None, skills=course.skills,
            ))
    return sorted(items, key=lambda i: term_sort_key(i.term), reverse=True)
