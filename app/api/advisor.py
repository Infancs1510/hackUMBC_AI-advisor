from fastapi import APIRouter, Depends, Path

from app.ai.backboard import BackboardError, BackboardMemory, BackboardNotConfiguredError
from app.ai.gemini import GeminiClient
from app.api.deps import ensure_is_student, get_current_user, get_gemini, get_memory, get_profiles, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN, AdvisorRequest, AdvisorResponse, MemoryListResponse
from app.models.auth import CurrentUser
from app.services.advisor import run_advisor
from app.services.career_matching import CareerProfile
from app.services.student_profile import StudentNotFoundError

router = APIRouter(tags=["advisor"])


@router.post("/advisor", response_model=AdvisorResponse)
async def advisor(
    request: AdvisorRequest,
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    gemini: GeminiClient = Depends(get_gemini),
    memory: BackboardMemory = Depends(get_memory),
    user: CurrentUser = Depends(get_current_user),
) -> AdvisorResponse:
    ensure_is_student(user, request.campus_id)
    return await run_advisor(request, store, profiles, gemini, memory)


@router.get("/advisor/{campus_id}/memories", response_model=MemoryListResponse)
async def list_memories(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN),
    store: DataStore = Depends(get_store),
    memory: BackboardMemory = Depends(get_memory),
    user: CurrentUser = Depends(get_current_user),
) -> MemoryListResponse:
    """What the advisor remembers about a student (interests, goals, preferences)."""
    ensure_is_student(user, campus_id)
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    try:
        return MemoryListResponse(campus_id=campus_id, memories=await memory.list(campus_id), backboard="ok")
    except BackboardNotConfiguredError:
        return MemoryListResponse(campus_id=campus_id, memories=[], backboard="not_configured")
    except BackboardError:
        return MemoryListResponse(campus_id=campus_id, memories=[], backboard="error")
