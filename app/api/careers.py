from fastapi import APIRouter, Depends

from app.api.deps import get_profiles, get_store
from app.data.loader import DataStore
from app.models.career import CareerDetail, CareerListResponse
from app.services.career_matching import CareerProfile, career_detail, career_summary, resolve_career
from app.services.dashboard import UnknownCareerError

router = APIRouter(tags=["careers"])


@router.get("/careers", response_model=CareerListResponse)
def list_careers(
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
) -> CareerListResponse:
    summaries = [career_summary(p, store.employment) for p in profiles.values()]
    return CareerListResponse(careers=sorted(summaries, key=lambda s: -s.job_spell_count))


@router.get("/careers/{career}", response_model=CareerDetail)
def get_career(
    career: str,
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
) -> CareerDetail:
    name = resolve_career(career, profiles)
    if name is None:
        raise UnknownCareerError(career)
    return career_detail(profiles[name], store.employment, store.alumni)
