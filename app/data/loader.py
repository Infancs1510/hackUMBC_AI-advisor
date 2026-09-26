"""Loads the HackUMBC CSVs into an in-memory store. The CSVs are the source of truth."""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from app.data.parsing import parse_prerequisites, split_pipe
from app.data.validator import validate_frames

logger = logging.getLogger(__name__)

FILES = {
    "students": "students_current.csv",
    "alumni": "alumni.csv",
    "transcripts": "transcripts.csv",
    "courses": "course_catalog.csv",
    "experiences": "student_experience.csv",
    "employment": "employment_history.csv",
}


@dataclass(frozen=True)
class Course:
    course_id: str
    title: str
    subject: str
    credits: int
    course_level: str
    course_type: str
    required_for_majors: list[str]
    prerequisites: list[list[str]]
    skills: list[str]
    difficulty_index: float
    terms_offered: list[str]


@dataclass
class DataStore:
    students: pd.DataFrame
    alumni: pd.DataFrame
    transcripts: pd.DataFrame
    courses: pd.DataFrame
    experiences: pd.DataFrame
    employment: pd.DataFrame
    catalog: dict[str, Course] = field(default_factory=dict)
    _transcripts_by_person: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _experiences_by_person: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)
    _employment_by_person: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.students = self.students.set_index("campus_id", drop=False)
        self.alumni = self.alumni.set_index("campus_id", drop=False)
        self.catalog = {
            row.course_id: Course(
                course_id=row.course_id,
                title=row.course_title,
                subject=row.subject,
                credits=int(row.credits),
                course_level=row.course_level,
                course_type=row.course_type,
                required_for_majors=split_pipe(row.required_for_majors),
                prerequisites=parse_prerequisites(row.prerequisite_ids),
                skills=split_pipe(row.skill_tags),
                difficulty_index=float(row.difficulty_index),
                terms_offered=split_pipe(row.typical_terms_offered),
            )
            for row in self.courses.itertuples(index=False)
        }
        self._transcripts_by_person = dict(tuple(self.transcripts.groupby("campus_id")))
        self._experiences_by_person = dict(tuple(self.experiences.groupby("campus_id")))
        self._employment_by_person = dict(tuple(self.employment.groupby("campus_id")))

    def is_student(self, campus_id: str) -> bool:
        return campus_id in self.students.index

    def is_alumnus(self, campus_id: str) -> bool:
        return campus_id in self.alumni.index

    def student_row(self, campus_id: str) -> pd.Series:
        return self.students.loc[campus_id]

    def transcript_for(self, campus_id: str) -> pd.DataFrame:
        return self._transcripts_by_person.get(campus_id, self.transcripts.iloc[0:0])

    def experiences_for(self, campus_id: str) -> pd.DataFrame:
        return self._experiences_by_person.get(campus_id, self.experiences.iloc[0:0])

    def alumnus_row(self, campus_id: str) -> pd.Series:
        return self.alumni.loc[campus_id]

    def employment_for(self, campus_id: str) -> pd.DataFrame:
        return self._employment_by_person.get(campus_id, self.employment.iloc[0:0])


def read_csv(path: Path) -> pd.DataFrame:
    # Only true blanks become NaN. pandas' default NA list would silently turn
    # strings such as "N/A" or "NA" into NaN; "Not Applicable" stays literal text.
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def load_data(data_dir: Path) -> DataStore:
    frames: dict[str, pd.DataFrame] = {}
    for key, filename in FILES.items():
        path = data_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Dataset file not found: {path}")
        frames[key] = read_csv(path)
    validate_frames(frames)
    store = DataStore(**frames)
    logger.info(
        "Loaded dataset from %s: %d students, %d alumni, %d transcript rows, %d courses",
        data_dir, len(store.students), len(store.alumni), len(store.transcripts), len(store.catalog),
    )
    return store
