from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

RUBRIC_NOTE = (
    "Readiness score from this app's published rubric: target-career keyword coverage 35%, verified skills "
    "listed 25%, quantified bullets 20%, structure 20%. It is not an applicant-tracking-system (ATS) score."
)


class ScoreComponent(BaseModel):
    key: str
    label: str
    weight: float
    score: float | None = Field(description="0-100; null when it doesn't apply (e.g. no verified skills yet).")
    detail: str


class SkillWithCourses(BaseModel):
    skill: str
    courses: list[str]


class ResumeFinding(BaseModel):
    kind: Literal[
        "verified_skill_missing", "experience_missing", "quantify", "section_missing",
        "career_gap", "unverified_claim", "length", "contact",
    ]
    priority: Literal["high", "medium", "low"]
    title: str
    detail: str
    items: list[str] = []


class ResumeAnalysis(BaseModel):
    target_career: str
    score: int
    rubric_note: str = RUBRIC_NOTE
    components: list[ScoreComponent]
    skills_found: list[str]
    career_skills_found: list[str]
    career_skills_missing: list[str]
    verified_skills_listed: list[str]
    verified_skills_missing: list[SkillWithCourses]
    unverified_skills: list[str] = Field(description="Skills on the resume that no completed course verifies.")
    experiences_missing: list[str]
    bullets_total: int
    bullets_quantified: int
    sections_found: list[str]
    word_count: int
    findings: list[ResumeFinding]


class ResumeRecord(BaseModel):
    filename: str
    uploaded_at: datetime
    size_bytes: int
    word_count: int


class ResumeResponse(BaseModel):
    campus_id: str
    resume: ResumeRecord | None
    analysis: ResumeAnalysis | None


class AIFeedbackResponse(BaseModel):
    suggestions: str
    gemini: Literal["ok", "not_configured", "error"]


class Project(BaseModel):
    id: int
    title: str
    description: str
    link: str | None
    skills: list[str]
    created_at: datetime


class ProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    link: HttpUrl | None = None
    skills: list[str] = Field(default_factory=list, max_length=12)


class VerifiedItem(BaseModel):
    kind: Literal["experience", "coursework"]
    category: str = Field(description="experience_type, or 'Upper-level course'.")
    title: str
    subtitle: str
    term: str
    outcome: str | None
    skills: list[str]


class PortfolioResponse(BaseModel):
    campus_id: str
    verified: list[VerifiedItem]
    projects: list[Project]
