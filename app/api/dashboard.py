from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import ensure_can_view_student, get_current_user, get_profiles, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.dashboard import DashboardResponse
from app.services.career_matching import CareerProfile
from app.services.dashboard import build_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/{campus_id}", response_model=DashboardResponse)
def get_dashboard(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN, examples=["CID-116490"]),
    career: str | None = Query(default=None, description="Career to build the pathway for; defaults to the top match."),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    user: CurrentUser = Depends(get_current_user),
) -> DashboardResponse:
    ensure_can_view_student(user, campus_id)
    return build_dashboard(store, profiles, campus_id, career=career)
