from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Request, Response, UploadFile, status

from app.ai.backboard import BackboardError, BackboardMemory
from app.ai.gemini import GeminiClient, GeminiError, GeminiNotConfiguredError
from app.ai.resume_prompts import RESUME_SYSTEM_PROMPT, render_resume_prompt
from app.api.deps import ensure_can_view_student, ensure_is_student, get_current_user, get_gemini, get_memory, get_profiles, get_store
from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser
from app.models.resume import AIFeedbackResponse, PortfolioResponse, Project, ProjectRequest, ResumeResponse
from app.services.career_matching import CareerProfile
from app.services.portfolio import PortfolioStore, verified_portfolio
from app.services.resume import ResumeError, analyze_resume, extract_text, target_career

router = APIRouter(tags=["resume & portfolio"])
CID = Path(pattern=CAMPUS_ID_PATTERN)


def get_portfolio(request: Request) -> PortfolioStore:
    return request.app.state.portfolio


async def _goal(memory: BackboardMemory, campus_id: str) -> str | None:
    try:
        return await memory.get_career_goal(campus_id)
    except BackboardError:
        return None


async def _response(
    campus_id: str, career: str | None, store: DataStore, profiles: dict[str, CareerProfile],
    memory: BackboardMemory, portfolio: PortfolioStore,
) -> ResumeResponse:
    saved = portfolio.get_resume(campus_id)
    if saved is None:
        return ResumeResponse(campus_id=campus_id, resume=None, analysis=None)
    record, text = saved
    target = target_career(store, profiles, campus_id, career, None if career else await _goal(memory, campus_id))
    return ResumeResponse(campus_id=campus_id, resume=record, analysis=analyze_resume(text, store, profiles, campus_id, target))


@router.get("/resume/{campus_id}", response_model=ResumeResponse)
async def get_resume(
    campus_id: str = CID,
    career: str | None = Query(default=None, description="Target career; defaults to the saved goal, then the top match."),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    memory: BackboardMemory = Depends(get_memory),
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> ResumeResponse:
    ensure_is_student(user, campus_id)
    return await _response(campus_id, career, store, profiles, memory, portfolio)


@router.post("/resume/{campus_id}", response_model=ResumeResponse)
async def upload_resume(
    campus_id: str = CID,
    file: UploadFile = File(description="PDF, DOCX, TXT, or MD; 2 MB max."),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    memory: BackboardMemory = Depends(get_memory),
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> ResumeResponse:
    """Replace the stored resume with a new version and analyze it."""
    ensure_is_student(user, campus_id)
    data = await file.read()
    try:
        text = extract_text(file.filename or "resume", data)
    except ResumeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    portfolio.save_resume(campus_id, (file.filename or "resume")[:200], text, len(data))
    return await _response(campus_id, None, store, profiles, memory, portfolio)


@router.delete("/resume/{campus_id}", status_code=204)
def delete_resume(
    campus_id: str = CID,
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    ensure_is_student(user, campus_id)
    portfolio.delete_resume(campus_id)
    return Response(status_code=204)


@router.post("/resume/{campus_id}/ai-feedback", response_model=AIFeedbackResponse)
async def resume_ai_feedback(
    campus_id: str = CID,
    career: str | None = Query(default=None),
    store: DataStore = Depends(get_store),
    profiles: dict[str, CareerProfile] = Depends(get_profiles),
    memory: BackboardMemory = Depends(get_memory),
    gemini: GeminiClient = Depends(get_gemini),
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> AIFeedbackResponse:
    """Optional Gemini rewrite suggestions. Sends the resume text to Gemini only when the student asks."""
    ensure_is_student(user, campus_id)
    saved = portfolio.get_resume(campus_id)
    if saved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload a resume first.")
    _, text = saved
    target = target_career(store, profiles, campus_id, career, None if career else await _goal(memory, campus_id))
    analysis = analyze_resume(text, store, profiles, campus_id, target)
    try:
        suggestions = await gemini.generate(RESUME_SYSTEM_PROMPT, render_resume_prompt(analysis, text), temperature=0.3)
    except GeminiNotConfiguredError:
        return AIFeedbackResponse(suggestions="AI suggestions are unavailable because Gemini isn't configured. The findings above still apply.", gemini="not_configured")
    except GeminiError:
        return AIFeedbackResponse(suggestions="AI suggestions are temporarily unavailable. The findings above still apply.", gemini="error")
    return AIFeedbackResponse(suggestions=suggestions, gemini="ok")


@router.get("/portfolio/{campus_id}", response_model=PortfolioResponse)
def get_portfolio_items(
    campus_id: str = CID,
    store: DataStore = Depends(get_store),
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> PortfolioResponse:
    """Verified items from the record plus self-reported projects. Advisors can view any student's."""
    ensure_can_view_student(user, campus_id)
    return PortfolioResponse(campus_id=campus_id, verified=verified_portfolio(store, campus_id), projects=portfolio.projects(campus_id))


@router.post("/portfolio/{campus_id}/projects", response_model=Project, status_code=201)
def add_project(
    request: ProjectRequest,
    campus_id: str = CID,
    store: DataStore = Depends(get_store),
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> Project:
    ensure_is_student(user, campus_id)
    skills = sorted({s for s in request.skills if s in store.all_skills})
    return portfolio.add_project(campus_id, request.title, request.description, str(request.link) if request.link else None, skills)


@router.delete("/portfolio/{campus_id}/projects/{project_id}", status_code=204)
def delete_project(
    project_id: int,
    campus_id: str = CID,
    portfolio: PortfolioStore = Depends(get_portfolio),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    ensure_is_student(user, campus_id)
    portfolio.delete_project(campus_id, project_id)
    return Response(status_code=204)
