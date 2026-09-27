"""Prompt for optional AI resume suggestions. Grounded in the rubric findings; never invents facts."""

import json

from app.models.resume import ResumeAnalysis

MAX_RESUME_CHARS = 6000

RESUME_SYSTEM_PROMPT = """You are a resume coach for a UMBC computing student.

You receive the student's resume text and findings computed by the university backend from their official record.

Rules:
- Suggest 4-6 specific improvements, most valuable first, as a short markdown list. Each item: what to change and a rewritten example line.
- Only suggest adding skills, courses, or experiences that appear in the findings (they come from the student's record) or already appear on the resume.
- Never invent numbers, employers, results, or technologies. When a metric would help, use a placeholder like [X users] or [N%] and tell the student to fill in their real figure.
- Tailor wording to the target career. Keep it under about 250 words."""


def render_resume_prompt(analysis: ResumeAnalysis, resume_text: str) -> str:
    findings = [
        {"title": f.title, "detail": f.detail, "items": f.items} for f in analysis.findings
    ]
    context = {
        "target_career": analysis.target_career,
        "career_skills_on_resume": analysis.career_skills_found,
        "career_skills_missing": analysis.career_skills_missing,
        "verified_skills_not_listed": [f"{s.skill} ({', '.join(s.courses)})" for s in analysis.verified_skills_missing],
        "record_experiences_not_mentioned": analysis.experiences_missing,
        "findings": findings,
    }
    return (
        f"FINDINGS (JSON):\n{json.dumps(context, indent=1)}\n\n"
        f"RESUME TEXT:\n{resume_text[:MAX_RESUME_CHARS]}"
    )
