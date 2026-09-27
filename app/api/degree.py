from fastapi import APIRouter, Depends, Path

from app.api.deps import ensure_can_view_student, get_current_user, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.degree import DegreeAudit
from app.services.degree_audit import build_degree_audit

router = APIRouter(tags=["degree"])


@router.get("/degree/{campus_id}", response_model=DegreeAudit)
def get_degree_audit(
    campus_id: str = Path(pattern=CAMPUS_ID_PATTERN, examples=["CID-116490"]),
    store: DataStore = Depends(get_store),
    user: CurrentUser = Depends(get_current_user),
) -> DegreeAudit:
    """Transcript by requirement category, remaining required courses, and credit summary."""
    ensure_can_view_student(user, campus_id)
    return build_degree_audit(store, campus_id)
