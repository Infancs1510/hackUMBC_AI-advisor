from typing import Literal

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import ensure_can_view_student, get_current_user, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.market import MarketInsights
from app.services.market import build_market_insights

router = APIRouter(tags=["market"])


@router.get("/market/{campus_id}", response_model=MarketInsights)
def get_market_insights(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN, examples=["CID-116490"]),
    major: Literal["Computer Science", "Information Systems"] | None = Query(
        default=None, description="Limit to alumni of one major; omit for all majors."
    ),
    store: DataStore = Depends(get_store),
    user: CurrentUser = Depends(get_current_user),
) -> MarketInsights:
    """Alumni-outcome market view personalized to the student's skills (not live job postings)."""
    ensure_can_view_student(user, campus_id)
    return build_market_insights(store, campus_id, major)
