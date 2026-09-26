"""FastAPI dependencies. Tests override these to inject fakes."""

from fastapi import Request

from app.ai.backboard import BackboardMemory
from app.ai.gemini import GeminiClient
from app.data.loader import DataStore
from app.services.career_matching import CareerProfile


def get_store(request: Request) -> DataStore:
    return request.app.state.store


def get_profiles(request: Request) -> dict[str, CareerProfile]:
    return request.app.state.career_profiles


def get_gemini(request: Request) -> GeminiClient:
    return request.app.state.gemini


def get_memory(request: Request) -> BackboardMemory:
    return request.app.state.memory
