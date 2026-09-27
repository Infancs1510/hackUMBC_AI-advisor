from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.ai.backboard import BackboardError, BackboardMemory
from app.api.deps import get_current_user, get_memory, get_profiles, get_store, require_advisor
from app.data.loader import DataStore
from app.models.appointments import (
    Appointment,
    AppointmentList,
    BookingRequest,
    RescheduleRequest,
    SessionNoteRequest,
    SlotsResponse,
    WeekSchedule,
)
from app.models.auth import CurrentUser
from app.services.appointments import AppointmentService, build_brief
from app.services.career_matching import CareerProfile

router = APIRouter(tags=["appointments"])


def get_appointments(request: Request) -> AppointmentService:
    return request.app.state.appointments


def _require_student(user: CurrentUser) -> str:
    if user.role != "student" or not user.campus_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students can book appointments")
    return user.campus_id


def _owned(service: AppointmentService, appointment_id: int, user: CurrentUser, advisor_ok: bool) -> Appointment:
    appointment = service.get(appointment_id)
    if user.role == "advisor" and advisor_ok:
        return appointment
    if user.role != "student" or appointment.campus_id != user.campus_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your appointment")
    return appointment


@router.get("/appointments/slots", response_model=SlotsResponse)
def slots(
    service: AppointmentService = Depends(get_appointments),
    _: CurrentUser = Depends(get_current_user),
) -> SlotsResponse:
    """Advising slots for the next two working weeks, with availability."""
    return service.slots()


@router.get("/appointments/schedule", response_model=WeekSchedule)
def week_schedule(
    week: date | None = Query(default=None, description="Any date in the week to show (defaults to this week)."),
    service: AppointmentService = Depends(get_appointments),
    _: CurrentUser = Depends(require_advisor),
) -> WeekSchedule:
    """Advisor week view: every advising slot Monday–Friday with its appointment, session notes and totals."""
    return service.week(week)


@router.get("/appointments", response_model=AppointmentList)
def list_appointments(
    include_past: bool = Query(default=False, description="Include past and cancelled appointments."),
    service: AppointmentService = Depends(get_appointments),
    user: CurrentUser = Depends(get_current_user),
) -> AppointmentList:
    """Students see their own appointments; advisors see everyone's."""
    campus_id = None if user.role == "advisor" else user.campus_id
    return AppointmentList(appointments=service.list_for(campus_id, upcoming_only=not include_past))


@router.post("/appointments", response_model=Appointment, status_code=201)
async def book(
    request: BookingRequest,
    http_request: Request,
    service: AppointmentService = Depends(get_appointments),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    memory: BackboardMemory = Depends(get_memory),
    user: CurrentUser = Depends(get_current_user),
) -> Appointment:
    campus_id = _require_student(user)
    try:
        goal = await memory.get_career_goal(campus_id)
    except BackboardError:
        goal = None
    brief = build_brief(store, profiles, campus_id, goal)
    appointment = service.book(campus_id, request.reason, request.modality, request.start, request.notes, brief)
    http_request.app.state.advising.mark_booked(campus_id)
    return appointment


@router.patch("/appointments/{appointment_id}", response_model=Appointment)
def reschedule(
    appointment_id: int,
    request: RescheduleRequest,
    service: AppointmentService = Depends(get_appointments),
    user: CurrentUser = Depends(get_current_user),
) -> Appointment:
    appointment = _owned(service, appointment_id, user, advisor_ok=False)
    return service.update(appointment, request.start, request.modality, request.notes)


@router.post("/appointments/{appointment_id}/cancel", response_model=Appointment)
def cancel(
    appointment_id: int,
    service: AppointmentService = Depends(get_appointments),
    user: CurrentUser = Depends(get_current_user),
) -> Appointment:
    return service.cancel(_owned(service, appointment_id, user, advisor_ok=True))


@router.post("/appointments/{appointment_id}/complete", response_model=Appointment)
def complete(
    appointment_id: int,
    service: AppointmentService = Depends(get_appointments),
    _: CurrentUser = Depends(require_advisor),
) -> Appointment:
    """Advisor marks a booked appointment as completed."""
    return service.complete(service.get(appointment_id))


@router.post("/appointments/{appointment_id}/no-show", response_model=Appointment)
def no_show(
    appointment_id: int,
    service: AppointmentService = Depends(get_appointments),
    _: CurrentUser = Depends(require_advisor),
) -> Appointment:
    """Advisor marks a booked appointment that has started as a no-show."""
    return service.mark_no_show(service.get(appointment_id))


@router.put("/appointments/{appointment_id}/session-note", response_model=SessionNoteRequest)
def session_note(
    appointment_id: int,
    body: SessionNoteRequest,
    service: AppointmentService = Depends(get_appointments),
    _: CurrentUser = Depends(require_advisor),
) -> SessionNoteRequest:
    """Save the advisor's private notes for an appointment (empty clears them). Students never see these."""
    return SessionNoteRequest(note=service.set_session_note(service.get(appointment_id), body.note))
