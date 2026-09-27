from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel

from app.ai.backboard import BackboardError, BackboardMemory, BackboardNotConfiguredError
from app.api.deps import ensure_is_student, get_current_user, get_memory, get_profiles
from app.models.advisor import CAMPUS_ID_PATTERN, ServiceState
from app.models.auth import CurrentUser
from app.services.career_matching import CareerProfile, resolve_career
from app.services.dashboard import UnknownCareerError

router = APIRouter(tags=["career goal"])


class CareerGoalRequest(BaseModel):
    career: str


class CareerGoalResponse(BaseModel):
    campus_id: str
    career: str | None
    backboard: ServiceState


def _state(exc: BackboardError) -> ServiceState:
    return "not_configured" if isinstance(exc, BackboardNotConfiguredError) else "error"


@router.get("/students/{campus_id}/career-goal", response_model=CareerGoalResponse)
async def get_career_goal(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN),
    memory: BackboardMemory = Depends(get_memory),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    user: CurrentUser = Depends(get_current_user),
) -> CareerGoalResponse:
    """The career the student saved as their goal (stored in Backboard memory)."""
    ensure_is_student(user, campus_id)
    try:
        saved = await memory.get_career_goal(campus_id)
    except BackboardError as exc:
        return CareerGoalResponse(campus_id=campus_id, career=None, backboard=_state(exc))
    return CareerGoalResponse(campus_id=campus_id, career=resolve_career(saved, profiles) if saved else None, backboard="ok")


@router.put("/students/{campus_id}/career-goal", response_model=CareerGoalResponse)
async def set_career_goal(
    request: CareerGoalRequest,
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN),
    memory: BackboardMemory = Depends(get_memory),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    user: CurrentUser = Depends(get_current_user),
) -> CareerGoalResponse:
    """Save a career goal to Backboard so the AI advisor focuses on it. Replaces any previous goal."""
    ensure_is_student(user, campus_id)
    career = resolve_career(request.career, profiles)
    if career is None:
        raise UnknownCareerError(request.career)
    try:
        await memory.set_career_goal(campus_id, career)
    except BackboardError as exc:
        return CareerGoalResponse(campus_id=campus_id, career=None, backboard=_state(exc))
    return CareerGoalResponse(campus_id=campus_id, career=career, backboard="ok")
