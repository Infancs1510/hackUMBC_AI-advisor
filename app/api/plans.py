from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from app.api.deps import ensure_can_view_student, ensure_is_student, get_current_user, get_profiles, get_store, require_advisor
from app.data.loader import DataStore
from app.data.parsing import NEXT_TERM
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.plans import (
    BatchResult,
    PlanDecision,
    PlanQueue,
    PlanQueueItem,
    PlanRequest,
    PlanValidation,
    RegistrationPlan,
    StudentPlanView,
)
from app.services.career_matching import CareerProfile
from app.services.plans import PlanError, PlanStore, to_model, validate_plan
from app.services.roadmap import build_roadmap

router = APIRouter(tags=["registration plans"])
CID = Path(pattern=CAMPUS_ID_PATTERN)


def get_plans(request: Request) -> PlanStore:
    return request.app.state.plans


def _context(request: Request, campus_id: str) -> tuple[list[str], list[str], object]:
    """Meeting reasons and next-term required courses, from the cached caseload row."""
    row = next((r for r in request.app.state.caseload.get().students if r.campus_id == campus_id), None)
    if row is None:
        return [], [], None
    reasons = []
    if row.academic_standing != "Good Standing":
        reasons.append(f"{row.academic_standing} — talk before approving")
    if any(f.code == "graduation_risk" for f in row.flags):
        reasons.append("Required courses may not fit before expected graduation")
    return reasons, row.next_required, row


def _validated(request: Request, store: DataStore, plan: dict) -> RegistrationPlan:
    reasons, next_required, _ = _context(request, plan["campus_id"])
    return to_model(plan, validate_plan(store, plan["campus_id"], plan["courses"], reasons, next_required))


@router.get("/plans/{campus_id}", response_model=StudentPlanView)
def get_student_plan(
    request: Request,
    campus_id: str = CID,
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    plans: PlanStore = Depends(get_plans),
    user: CurrentUser = Depends(get_current_user),
) -> StudentPlanView:
    """The student's next-term plan (if any) plus roadmap suggestions."""
    ensure_can_view_student(user, campus_id)
    roadmap = build_roadmap(store, profiles, campus_id)
    next_term = next((t for t in roadmap.terms if t.term == NEXT_TERM), None)
    plan = plans.for_student(campus_id)
    return StudentPlanView(
        campus_id=campus_id, term=NEXT_TERM,
        plan=_validated(request, store, plan) if plan else None,
        suggested=[c.course_id for c in next_term.courses] if next_term else [],
    )


@router.post("/plans/{campus_id}/validate", response_model=PlanValidation)
def validate(
    body: PlanRequest,
    request: Request,
    campus_id: str = CID,
    store: DataStore = Depends(get_store),
    user: CurrentUser = Depends(get_current_user),
) -> PlanValidation:
    """Check a draft plan without saving it."""
    ensure_can_view_student(user, campus_id)
    reasons, next_required, _ = _context(request, campus_id)
    return validate_plan(store, campus_id, body.courses, reasons, next_required)


@router.put("/plans/{campus_id}", response_model=RegistrationPlan)
def submit_plan(
    body: PlanRequest,
    request: Request,
    campus_id: str = CID,
    store: DataStore = Depends(get_store),
    plans: PlanStore = Depends(get_plans),
    user: CurrentUser = Depends(get_current_user),
) -> RegistrationPlan:
    """Submit (or resubmit) the plan for advisor review. Resubmitting clears the previous decision."""
    ensure_is_student(user, campus_id)
    courses = list(dict.fromkeys(c.strip().upper() for c in body.courses if c.strip()))
    return _validated(request, store, plans.submit(campus_id, courses, body.note))


@router.delete("/plans/{campus_id}", status_code=204)
def withdraw_plan(
    campus_id: str = CID,
    plans: PlanStore = Depends(get_plans),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    ensure_is_student(user, campus_id)
    plans.withdraw(campus_id)
    return Response(status_code=204)


@router.get("/plans", response_model=PlanQueue)
def plan_queue(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", description="submitted | approved | changes_requested"),
    category: str | None = Query(default=None, description="ready | prereq | meeting"),
    store: DataStore = Depends(get_store),
    plans: PlanStore = Depends(get_plans),
    _: CurrentUser = Depends(require_advisor),
) -> PlanQueue:
    """Advisor review queue: every plan for next term with its validation and the student's summary."""
    items = []
    for plan in plans.all():
        model = _validated(request, store, plan)
        _, _, row = _context(request, plan["campus_id"])
        items.append(PlanQueueItem(
            **model.model_dump(), class_level=row.class_level, major=row.major, track=row.track, gpa=row.gpa,
            academic_standing=row.academic_standing, credits_earned=row.credits_earned,
            credits_required=int(store.student_row(plan["campus_id"])["credits_required"]),
            flags=[f.code for f in row.flags],
        ))
    submitted = [p for p in items if p.status == "submitted"]
    counts = {
        "submitted": len(submitted),
        **{c: sum(1 for p in submitted if p.validation.category == c) for c in ["ready", "prereq", "meeting"]},
        "approved": sum(1 for p in items if p.status == "approved"),
        "changes_requested": sum(1 for p in items if p.status == "changes_requested"),
    }
    if status_filter:
        items = [p for p in items if p.status == status_filter]
    if category:
        items = [p for p in items if p.validation.category == category]
    order = {"meeting": 0, "prereq": 1, "ready": 2}
    items.sort(key=lambda p: (p.status != "submitted", order[p.validation.category], p.submitted_at))
    return PlanQueue(plans=items, counts=counts)


@router.post("/plans/{plan_id}/approve", response_model=RegistrationPlan)
def approve(
    plan_id: int,
    body: PlanDecision,
    request: Request,
    store: DataStore = Depends(get_store),
    plans: PlanStore = Depends(get_plans),
    _: CurrentUser = Depends(require_advisor),
) -> RegistrationPlan:
    plan = _validated(request, store, plans.get(plan_id))
    if plan.validation.blocked:
        raise HTTPException(status.HTTP_409_CONFLICT, "This plan has blocked courses — request changes instead.")
    return _validated(request, store, plans.decide(plan_id, "approved", body.note))


@router.post("/plans/{plan_id}/request-changes", response_model=RegistrationPlan)
def request_changes(
    plan_id: int,
    body: PlanDecision,
    request: Request,
    store: DataStore = Depends(get_store),
    plans: PlanStore = Depends(get_plans),
    _: CurrentUser = Depends(require_advisor),
) -> RegistrationPlan:
    if not body.note.strip():
        raise HTTPException(422, "Tell the student what to change.")
    return _validated(request, store, plans.decide(plan_id, "changes_requested", body.note))


@router.post("/plans-approve-ready", response_model=BatchResult)
def approve_ready(
    request: Request,
    store: DataStore = Depends(get_store),
    plans: PlanStore = Depends(get_plans),
    _: CurrentUser = Depends(require_advisor),
) -> BatchResult:
    """Approve every submitted plan whose checks all pass and that doesn't need a meeting first."""
    approved = []
    for plan in plans.all():
        if plan["status"] != "submitted":
            continue
        if _validated(request, store, plan).validation.category == "ready":
            plans.decide(plan["id"], "approved", "")
            approved.append(plan["id"])
    return BatchResult(approved=approved)
