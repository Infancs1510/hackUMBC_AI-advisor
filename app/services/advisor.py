"""AI advisor orchestration.

student data -> Python analytics -> Backboard memory -> structured context -> Gemini
-> response -> save useful memory
"""

import asyncio
import logging
import re

from app.ai.backboard import BackboardError, BackboardMemory, BackboardNotConfiguredError
from app.ai.gemini import GeminiClient, GeminiError, GeminiNotConfiguredError
from app.ai.prompts import (
    ADVISOR_SYSTEM_PROMPT,
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    build_advisor_context,
    fallback_reply,
    heuristic_memories,
    parse_extracted_memories,
    render_advisor_prompt,
)
from app.data.loader import DataStore
from app.models.advisor import AdvisorRequest, AdvisorResponse, MemoryItem, ServiceState, ServiceStatus
from app.services.career_matching import CareerProfile, resolve_career
from app.services.dashboard import build_dashboard
from app.services.student_profile import StudentNotFoundError

logger = logging.getLogger(__name__)

MEMORY_SEARCH_LIMIT = 8


def _state_for(exc: Exception) -> ServiceState:
    if isinstance(exc, (GeminiNotConfiguredError, BackboardNotConfiguredError)):
        return "not_configured"
    return "error"


def named_career(text: str, profiles: dict[str, CareerProfile]) -> str | None:
    """Career named in free text, by full name or an '&'-separated part as whole words.

    e.g. "machine learning" -> "Machine Learning & AI". The longest match wins.
    """
    best: tuple[int, str] | None = None
    for career in profiles:
        for phrase in [career, *career.split("&")]:
            phrase = phrase.strip()
            if phrase and re.search(rf"\b{re.escape(phrase)}\b", text, re.IGNORECASE):
                if best is None or len(phrase) > best[0]:
                    best = (len(phrase), career)
    return best[1] if best else None


def pick_focus_career(
    request: AdvisorRequest,
    message: str,
    profiles: dict[str, CareerProfile],
    memories: list[MemoryItem] = (),
) -> str | None:
    """Explicit request > career named in the message > remembered interest > top match (None).

    A remembered interest only chooses which career to discuss; it never changes any fact.
    """
    if request.career:
        return resolve_career(request.career, profiles)
    from_message = named_career(message, profiles)
    if from_message:
        return from_message
    for item in memories:
        if item.category in (None, "career_interest", "goal"):
            remembered = named_career(item.content, profiles)
            if remembered:
                return remembered
    return None


async def _extract_memories(gemini: GeminiClient, message: str, known: list[MemoryItem]) -> list[MemoryItem]:
    if gemini.configured:
        prompt = message
        if known:
            listed = "\n".join(f"- {m.content}" for m in known)
            prompt = f"ALREADY REMEMBERED (do not repeat or rephrase these):\n{listed}\n\nMESSAGE:\n{message}"
        try:
            raw = await gemini.generate(
                MEMORY_EXTRACTION_SYSTEM_PROMPT, prompt, json_output=True, temperature=0.0
            )
            return parse_extracted_memories(raw)
        except GeminiError as exc:
            logger.warning("Memory extraction via Gemini failed: %s", exc)
    return heuristic_memories(message)


async def run_advisor(
    request: AdvisorRequest,
    store: DataStore,
    profiles: dict[str, CareerProfile],
    gemini: GeminiClient,
    memory: BackboardMemory,
) -> AdvisorResponse:
    campus_id = request.campus_id
    message = request.message.strip()

    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))

    # Conversational memory (never authoritative).
    backboard_state: ServiceState = "ok"
    memories: list[MemoryItem] = []
    try:
        memories = await memory.search(campus_id, message, limit=MEMORY_SEARCH_LIMIT)
    except BackboardError as exc:
        backboard_state = _state_for(exc)
        if backboard_state == "error":
            logger.warning("Backboard memory search failed: %s", exc)

    # Facts and analytics from the dataset. Raises UnknownCareerError for a bad request.career.
    focus = pick_focus_career(request, message, profiles, memories)
    dashboard = build_dashboard(store, profiles, campus_id, career=focus or request.career)
    focus = dashboard.selected_career

    # Structured context -> Gemini, with memory extraction in parallel.
    context = build_advisor_context(dashboard, memories, focus)
    gemini_state: ServiceState = "ok"

    async def generate_reply() -> str:
        nonlocal gemini_state
        try:
            return await gemini.generate(ADVISOR_SYSTEM_PROMPT, render_advisor_prompt(context, message))
        except GeminiError as exc:
            gemini_state = _state_for(exc)
            if gemini_state == "error":
                logger.warning("Gemini advisor call failed: %s", exc)
            return fallback_reply(dashboard, focus)

    reply, extracted = await asyncio.gather(generate_reply(), _extract_memories(gemini, message, memories))

    # Save new, non-duplicate memories.
    saved: list[MemoryItem] = []
    if backboard_state == "ok":
        known = {m.content.strip().casefold() for m in memories}
        for item in extracted:
            key = item.content.strip().casefold()
            if key in known:
                continue
            try:
                await memory.add(campus_id, item)
            except BackboardError as exc:
                backboard_state = _state_for(exc)
                logger.warning("Backboard memory save failed: %s", exc)
                break
            known.add(key)
            saved.append(item)

    return AdvisorResponse(
        campus_id=campus_id,
        reply=reply,
        focus_career=focus,
        recommended_course_ids=[c.course_id for c in dashboard.pathway.recommended_courses] if dashboard.pathway else [],
        memories_used=memories,
        memories_saved=saved,
        services=ServiceStatus(gemini=gemini_state, backboard=backboard_state),
    )
