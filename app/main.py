"""FastAPI entry point: `uvicorn app.main:app --reload`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.backboard import BackboardMemory
from app.ai.gemini import GeminiClient
from app.api import advisor, alumni, careers, dashboard, health
from app.config import Settings, get_settings
from app.data.loader import load_data
from app.services.career_matching import build_career_profiles
from app.services.alumni_profile import AlumnusNotFoundError
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
        allow_origins=settings.cors_origins + ["http://127.0.0.1:5500", "http://localhost:5500", "http://127.0.0.1:8000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(StudentNotFoundError)
    async def student_not_found(_: Request, exc: StudentNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc), "is_alumnus": exc.is_alumnus})

    @app.exception_handler(AlumnusNotFoundError)
    async def alumnus_not_found(_: Request, exc: AlumnusNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc), "is_student": exc.is_student})

    @app.exception_handler(UnknownCareerError)
    async def unknown_career(_: Request, exc: UnknownCareerError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    for module in (health, dashboard, alumni, careers, advisor):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
