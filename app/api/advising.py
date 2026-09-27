from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status

from app.api.deps import get_current_user, get_store, require_advisor
from app.data.loader import DataStore
from app.models.analytics import PathwayAnalytics
from app.models.advising import (
    AdvisorDashboard,
    MeetingRequest,
    MeetingRequestCreate,
    MeetingRequestList,
    Review,
    ReviewRequest,
)
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.services.advising import AdvisingStore, build_advisor_dashboard
from app.services.student_profile import StudentNotFoundError

router = APIRouter(tags=["advising"])


def get_advising(request: Request) -> AdvisingStore:
    return request.app.state.advising


def _student(store: DataStore, campus_id: str) -> str:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    return campus_id


@router.get("/advisor-dashboard", response_model=AdvisorDashboard)
def advisor_dashboard(
    request: Request,
    store: DataStore = Depends(get_store),
    advising: AdvisingStore = Depends(get_advising),
    _: CurrentUser = Depends(require_advisor),
) -> AdvisorDashboard:
    appointments = request.app.state.appointments
    today = datetime.now(appointments.tz).date().isoformat()
    return build_advisor_dashboard(
        request.app.state.caseload.get(), store, advising, appointments.list_for(None, upcoming_only=True), today
    )


@router.put("/caseload/{campus_id}/review", response_model=Review)
def review_student(
    body: ReviewRequest,
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN),
    store: DataStore = Depends(get_store),
    advising: AdvisingStore = Depends(get_advising),
    _: CurrentUser = Depends(require_advisor),
) -> Review:
    """Mark a student as reviewed, with an optional note (visible to advisors only)."""
    return advising.set_review(_student(store, campus_id), body.note)


@router.delete("/caseload/{campus_id}/review", status_code=204)
def clear_review(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN),
    advising: AdvisingStore = Depends(get_advising),
    _: CurrentUser = Depends(require_advisor),
) -> Response:
    advising.clear_review(campus_id)
    return Response(status_code=204)


@router.post("/meeting-requests", response_model=MeetingRequest, status_code=201)
def request_meeting(
    body: MeetingRequestCreate,
    store: DataStore = Depends(get_store),
    advising: AdvisingStore = Depends(get_advising),
    _: CurrentUser = Depends(require_advisor),
) -> MeetingRequest:
    """Ask a student to book an appointment; they see it on their Appointments page."""
    return advising.create_request(_student(store, body.campus_id), body.reason, body.message)


@router.get("/meeting-requests", response_model=MeetingRequestList)
def list_meeting_requests(
    advising: AdvisingStore = Depends(get_advising),
    user: CurrentUser = Depends(get_current_user),
) -> MeetingRequestList:
    """Students see their own open requests; advisors see all open requests."""
    campus_id = None if user.role == "advisor" else user.campus_id
    return MeetingRequestList(requests=advising.requests(campus_id))


@router.post("/meeting-requests/{request_id}/dismiss", response_model=MeetingRequest)
def dismiss_meeting_request(
    request_id: int,
    advising: AdvisingStore = Depends(get_advising),
    user: CurrentUser = Depends(get_current_user),
) -> MeetingRequest:
    item = advising.get_request(request_id)
    if user.role == "student" and item.campus_id != user.campus_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your request")
    return advising.set_request_status(request_id, "dismissed")


@router.get("/analytics/pathways", response_model=PathwayAnalytics)
def pathway_analytics(request: Request, _: CurrentUser = Depends(require_advisor)) -> PathwayAnalytics:
    """Cohort pathway analytics: KPIs, tracks, class levels, course bottlenecks, career alignment, interventions."""
    return request.app.state.analytics.get()
