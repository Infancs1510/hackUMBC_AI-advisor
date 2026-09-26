"""Prompt text and structured-context building for the AI advisor.

Gemini only ever sees the compact context built here -- never raw CSV rows.
"""

import json
import re

from app.data.parsing import CURRENT_TERM, NEXT_TERM
from app.models.advisor import MemoryItem
from app.models.career import SALARY_BASIS
from app.models.dashboard import MATCH_SCORE_NOTE, DashboardResponse

TOP_MATCHES_IN_CONTEXT = 4

ADVISOR_SYSTEM_PROMPT = f"""You are a career advisor for UMBC Computer Science and Information Systems students.

You receive a JSON context computed by the university backend from official records, then the student's message.

Rules:
- The "facts" section is authoritative. Use only the GPA, credits, courses, skills, career matches, salaries, and alumni statistics it contains. Never invent or estimate academic records, courses, salaries, or career statistics.
- Only recommend courses listed in the context (recommended_courses or prerequisite_steps), by course_id and title. If the student asks about a course not in the context, say you can only speak to courses in the catalog data you were given.
- "student_memory" holds things the student said in earlier conversations (interests, goals, preferences). Use it to personalise advice. It is not authoritative: if it conflicts with "facts", the facts win, and you may point out the discrepancy politely.
- If the student states a different GPA, grade, or credit count than the facts, gently note what the records show.
- Match scores are skill overlap, not the probability of getting a job. Salaries are nominal dollars of each job's start year and are not inflation-adjusted; say so when quoting them.
- There is no tuition, debt, or ROI data for current students in the context; do not estimate it.
- If the answer is not supported by the context, say so plainly.
- The current term is {CURRENT_TERM}; "next semester" means {NEXT_TERM}.
- Be concise, warm, and specific: short paragraphs or a brief list, under about 250 words."""

MEMORY_EXTRACTION_SYSTEM_PROMPT = """You extract durable memories about a student from one chat message, for a career advisor.

Keep only:
- career_interest: careers, roles, industries, or fields the student is interested in or not interested in
- goal: concrete goals (e.g. get an internship by junior year, work in cybersecurity for the federal government)
- preference: preferences about courses, workload, schedule, location, remote work, or learning style
- context: stable personal context the student volunteers that matters for career advice (e.g. works 20 hours a week)

Never keep GPA, grades, credits, courses taken, major, graduation dates, salaries, or any other academic record -- the university database is the source of truth for those.
Do not record questions the student asks unless they reveal an interest or goal.
Write each memory as a short third-person sentence, e.g. "Interested in data engineering roles."

Return JSON: {"memories": [{"category": "career_interest|goal|preference|context", "content": "..."}]}. Return {"memories": []} if nothing qualifies."""

# Any memory mentioning academic-record facts is dropped; the dataset owns those.
_FACT_PATTERN = re.compile(
    r"\b(gpa|grade[sd]?|credits?|transcript|salar(y|ies)|graduation (term|year|date)|cumulative|"
    r"academic standing)\b|\$\s?\d|\b\d\.\d{1,2}\b",
    re.IGNORECASE,
)
MEMORY_CATEGORIES = {"career_interest", "goal", "preference", "context"}
MAX_MEMORY_LENGTH = 300

_HEURISTIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(i'?m|i am) (really )?(interested in|passionate about|curious about)\b", re.I), "career_interest"),
    (re.compile(r"\bi (want|would like|'d like|hope|plan) to (become|be|work|get|land|pursue)\b", re.I), "goal"),
    (re.compile(r"\bmy (goal|dream|plan) is\b", re.I), "goal"),
    (re.compile(r"\bi (prefer|like|love|enjoy|dislike|hate|don'?t like|want to avoid)\b", re.I), "preference"),
]


def is_allowed_memory(item: MemoryItem) -> bool:
    content = item.content.strip()
    return (
        bool(content)
        and len(content) <= MAX_MEMORY_LENGTH
        and item.category in MEMORY_CATEGORIES
        and not _FACT_PATTERN.search(content)
    )


def parse_extracted_memories(raw: str) -> list[MemoryItem]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    entries = payload.get("memories", []) if isinstance(payload, dict) else []
    items = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("content"), str):
            item = MemoryItem(content=entry["content"].strip(), category=entry.get("category"))
            if is_allowed_memory(item):
                items.append(item)
    return items


def heuristic_memories(message: str) -> list[MemoryItem]:
    """Fallback when Gemini is unavailable: keep sentences that clearly state an interest/goal/preference."""
    items = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", message):
        sentence = sentence.strip()
        for pattern, category in _HEURISTIC_PATTERNS:
            if pattern.search(sentence):
                item = MemoryItem(content=f'Student said: "{sentence}"', category=category)
                if is_allowed_memory(item):
                    items.append(item)
                break
    return items


def build_advisor_context(
    dashboard: DashboardResponse, memories: list[MemoryItem], focus_career: str | None
) -> dict:
    student = dashboard.student
    focus_match = next((m for m in dashboard.career_matches if m.career == focus_career), None)
    pathway = dashboard.pathway if dashboard.pathway and dashboard.pathway.career == focus_career else None
    salary = dashboard.salary if dashboard.salary and dashboard.salary.career == focus_career else None

    focus: dict | None = None
    if focus_match is not None:
        focus = {
            "career": focus_match.career,
            "match_score": focus_match.score,
            "projected_score_after_current_term": focus_match.projected_score,
            "matched_skills": focus_match.matched_skills,
            "missing_skills": focus_match.missing_skills,
            "missing_core_skills": focus_match.missing_core_skills,
        }
        if salary is not None:
            focus["alumni_salary"] = {
                "basis": SALARY_BASIS,
                "entry_level": salary.entry_level.model_dump() if salary.entry_level else None,
                "all_levels_median": salary.all_levels.median if salary.all_levels else None,
            }
        if pathway is not None:
            focus["alumni_first_job_outcomes"] = pathway.alumni_outcomes.model_dump()
            focus["recommended_courses"] = [
                c.model_dump(include={"course_id", "title", "credits", "status", "missing_prerequisites",
                                      "skills_gained", "offered_next_term", "difficulty_index"})
                for c in pathway.recommended_courses
            ]
            focus["prerequisite_steps"] = [s.model_dump() for s in pathway.prerequisite_steps]

    return {
        "facts": {
            "data_as_of": f"2026-09-15 ({CURRENT_TERM} in progress; next term {NEXT_TERM})",
            "student": {
                "major": student.major,
                "track": student.track,
                "second_major": student.second_major,
                "minor": student.minor,
                "class_level": student.class_level,
                "entry_type": student.entry_type,
                "gpa": student.gpa if student.gpa is not None else "none yet (first term)",
                "major_gpa": student.major_gpa,
                "credits_earned": student.credits_earned,
                "credits_required": student.credits_required,
                "credits_in_progress": student.credits_in_progress,
                "academic_standing": student.academic_standing,
                "expected_graduation_term": student.expected_graduation_term,
                "completed_courses": [f"{c.course_id} {c.title}" for c in student.completed_courses],
                "in_progress_courses": [f"{c.course_id} {c.title}" for c in student.in_progress_courses],
                "internships": [f"{e.name} at {e.organization} ({e.term}, {e.outcome})" for e in student.internships],
                "credentials": [f"{e.name} ({e.term}, {e.outcome})" for e in student.credentials],
                "other_activity_count": student.engagement_activity_count,
            },
            "skills_from_completed_courses": [s.skill for s in dashboard.skills],
            "skills_from_in_progress_courses": [s.skill for s in dashboard.in_progress_skills],
            "top_career_matches": [
                {"career": m.career, "score": m.score, "projected_score": m.projected_score,
                 "missing_core_skills": m.missing_core_skills}
                for m in dashboard.career_matches[:TOP_MATCHES_IN_CONTEXT]
            ],
            "focus_career": focus,
            "notes": [MATCH_SCORE_NOTE, "No tuition, debt, or ROI data is provided."],
        },
        "student_memory": [{"category": m.category, "content": m.content} for m in memories],
    }


def render_advisor_prompt(context: dict, message: str) -> str:
    return (
        "CONTEXT (JSON):\n"
        f"{json.dumps(context, indent=1, default=str)}\n\n"
        "STUDENT MESSAGE:\n"
        f"{message}"
    )


def fallback_reply(dashboard: DashboardResponse, focus_career: str | None) -> str:
    """Deterministic answer from computed data, used when Gemini is unavailable."""
    lines = ["The AI advisor is unavailable right now, so here is a summary straight from your records."]
    match = next((m for m in dashboard.career_matches if m.career == focus_career), None)
    if match is not None:
        lines.append(f"Career focus: {match.career} (skill-overlap score {match.score}/100, not a job probability).")
        if match.missing_core_skills:
            lines.append(f"Core skills still missing: {', '.join(match.missing_core_skills)}.")
    pathway = dashboard.pathway
    if pathway is not None and pathway.career == focus_career and pathway.recommended_courses:
        courses = "; ".join(
            f"{c.course_id} {c.title} ({c.status.replace('_', ' ')})" for c in pathway.recommended_courses[:4]
        )
        lines.append(f"Courses from the catalog that build those skills: {courses}.")
        if pathway.prerequisite_steps:
            steps = ", ".join(s.course_id for s in pathway.prerequisite_steps[:4])
            lines.append(f"Prerequisites to plan for {pathway.next_term}: {steps}.")
    return " ".join(lines)
