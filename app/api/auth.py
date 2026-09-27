from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_auth, get_current_user, get_store
from app.data.loader import DataStore
from app.models.auth import CurrentUser, LoginRequest, LoginResponse
from app.services.auth import AuthError, AuthService

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    auth: AuthService = Depends(get_auth),
    store: DataStore = Depends(get_store),
) -> LoginResponse:
    try:
        return auth.login(request.username, request.password, store)
    except AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc


@router.get("/auth/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return user
