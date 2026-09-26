from fastapi import APIRouter, Depends, Path

from app.api.deps import get_profiles, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.alumni import AlumniResponse
from app.services.alumni_profile import build_alumni_view
from app.services.career_matching import CareerProfile

router = APIRouter(tags=["alumni"])


@router.get("/alumni/{campus_id}", response_model=AlumniResponse)
def get_alumnus(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN, examples=["CID-655977"]),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
) -> AlumniResponse:
    return build_alumni_view(store, profiles, campus_id)
