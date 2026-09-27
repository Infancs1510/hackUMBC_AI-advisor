"""FastAPI dependencies. Tests override the AI ones to inject fakes."""

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.ai.backboard import BackboardMemory
from app.ai.gemini import GeminiClient
from app.data.loader import DataStore
from app.models.auth import CurrentUser
from app.services.auth import AuthError, AuthService
from app.services.career_matching import CareerProfile

_bearer = HTTPBearer(auto_error=False)


def get_store(request: Request) -> DataStore:
    return request.app.state.store


def get_profiles(request: Request) -> dict[str, CareerProfile]:
    return request.app.state.career_profiles


def get_gemini(request: Request) -> GeminiClient:
    return request.app.state.gemini


def get_memory(request: Request) -> BackboardMemory:
    return request.app.state.memory


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"})
    try:
        return auth.verify(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc


def require_advisor(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "advisor":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Advisor access required")
    return user


def ensure_can_view_student(user: CurrentUser, campus_id: str) -> None:
    """Advisors can view any student; students only themselves."""
    if user.role == "advisor":
        return
    if user.campus_id != campus_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Students can only view their own records")


def ensure_is_student(user: CurrentUser, campus_id: str) -> None:
    """The student themselves only (AI chat and memory are personal)."""
    if user.role != "student" or user.campus_id != campus_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the student can use their advisor chat, memory, and career goal")
