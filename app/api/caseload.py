from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_advisor
from app.models.caseload import CaseloadResponse, CaseloadSort
from app.services.caseload import query_caseload

router = APIRouter(tags=["caseload"], dependencies=[Depends(require_advisor)])


@router.get("/caseload", response_model=CaseloadResponse)
def caseload(
    request: Request,
    q: str | None = Query(default=None, max_length=20, description="Campus ID search (substring)."),
    major: str | None = None,
    track: str | None = None,
    class_level: str | None = None,
    standing: str | None = None,
    career: str | None = Query(default=None, description="Filter by top career match."),
    flag: str | None = Query(default=None, description="academic_standing | graduation_risk | no_internship | low_career_match"),
    reviewed: bool | None = Query(default=None, description="true = only reviewed, false = only not yet reviewed"),
    flagged: bool | None = Query(default=None, description="true = only students with at least one flag"),
    sort: CaseloadSort = "flags",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
) -> CaseloadResponse:
    """Advisor view of all current students with attention flags."""
    return query_caseload(
        request.app.state.caseload.get(),
        q=q, major=major, track=track, class_level=class_level, standing=standing, career=career, flag=flag,
        reviewed=reviewed, flagged=flagged, reviews=request.app.state.advising.reviews(), sort=sort, page=page, page_size=page_size,
    )
