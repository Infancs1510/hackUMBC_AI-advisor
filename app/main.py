"""FastAPI entry point: `uvicorn app.main:app --reload`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.backboard import BackboardMemory
from app.ai.gemini import GeminiClient
from app.api import advising, advisor, alumni, appointments, auth, careers, caseload, dashboard, degree, goal, health, market, plans, reports, resume, roadmap
from app.config import Settings, get_settings
from app.data.loader import load_data
from app.services.career_matching import build_career_profiles
from app.services.alumni_profile import AlumnusNotFoundError
from app.services.appointments import AppointmentError, AppointmentService
from app.services.auth import AuthService
from app.services.plans import PlanError, PlanStore
from app.services.portfolio import PortfolioError, PortfolioStore
from app.services.advising import AdvisingError, AdvisingStore
from app.services.reports import ReportError, ReportStore
from app.services.analytics import AnalyticsCache
from app.services.caseload import CaseloadCache
from app.services.dashboard import UnknownCareerError
from app.services.student_profile import StudentNotFoundError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = load_data(settings.data_dir)
        app.state.store = store
        app.state.career_profiles = build_career_profiles(store.employment)
        app.state.caseload = CaseloadCache(store, app.state.career_profiles)
        app.state.analytics = AnalyticsCache(store, app.state.career_profiles, app.state.caseload)
        app.state.analytics.warm_in_background()
        app.state.auth = AuthService(
            secret=settings.auth_secret,
            ttl_minutes=settings.auth_token_ttl_minutes,
            student_password=settings.student_demo_password,
            advisor_username=settings.advisor_username,
            advisor_password=settings.advisor_password,
        )
        app.state.appointments = AppointmentService(
            settings.app_db_path, settings.advisor_display_name, settings.advising_timezone
        )
        app.state.portfolio = PortfolioStore(settings.app_db_path)
        app.state.plans = PlanStore(settings.app_db_path)
        app.state.advising = AdvisingStore(settings.app_db_path, settings.advisor_display_name)
        app.state.reports = ReportStore(settings.app_db_path)
        if app.state.auth.ephemeral_secret:
            logging.getLogger(__name__).warning("AUTH_SECRET not set; using a random secret (sessions end on restart)")
        app.state.gemini = GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
            base_url=settings.gemini_base_url,
            timeout=settings.gemini_timeout_seconds,
        )
        app.state.memory = BackboardMemory(
            api_key=settings.backboard_api_key,
            base_url=settings.backboard_base_url,
            assistant_prefix=settings.backboard_assistant_prefix,
            timeout=settings.backboard_timeout_seconds,
        )
        yield

    app = FastAPI(
        title="HackUMBC 2026 Career Intelligence API",
        description="Dataset facts -> Python analytics -> Backboard memory -> Gemini advice.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(StudentNotFoundError)
    async def student_not_found(_: Request, exc: StudentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc), "is_alumnus": exc.is_alumnus})

    @app.exception_handler(AlumnusNotFoundError)
    async def alumnus_not_found(_: Request, exc: AlumnusNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc), "is_student": exc.is_student})

    @app.exception_handler(AppointmentError)
    async def appointment_error(_: Request, exc: AppointmentError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(PlanError)
    async def plan_error(_: Request, exc: PlanError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(AdvisingError)
    async def advising_error(_: Request, exc: AdvisingError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(ReportError)
    async def report_error(_: Request, exc: ReportError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(PortfolioError)
    async def portfolio_error(_: Request, exc: PortfolioError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(UnknownCareerError)
    async def unknown_career(_: Request, exc: UnknownCareerError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    for module in (health, auth, dashboard, degree, roadmap, market, goal, appointments, resume, alumni, careers, caseload, advising, plans, reports, advisor):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
