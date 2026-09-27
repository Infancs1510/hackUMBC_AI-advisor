from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import ensure_can_view_student, get_current_user, get_profiles, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.roadmap import Roadmap
from app.services.career_matching import CareerProfile
from app.services.roadmap import build_roadmap

router = APIRouter(tags=["roadmap"])


@router.get("/roadmap/{campus_id}", response_model=Roadmap)
def get_roadmap(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN, examples=["CID-116490"]),
    career: str | None = Query(default=None, description="Target career; defaults to the top match."),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    user: CurrentUser = Depends(get_current_user),
) -> Roadmap:
    """Suggested term-by-term plan toward graduation and a target career."""
    ensure_can_view_student(user, campus_id)
    return build_roadmap(store, profiles, campus_id, career)
