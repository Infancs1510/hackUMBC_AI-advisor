import pytest
from fastapi.testclient import TestClient

from app.ai.backboard import BackboardError, BackboardNotConfiguredError
from app.ai.gemini import GeminiError, GeminiNotConfiguredError
from app.api.deps import get_gemini, get_memory
from app.config import BASE_DIR, Settings
from app.data.loader import load_data
from app.main import create_app
from app.models.advisor import MemoryItem
from app.services.career_matching import build_career_profiles

# Real students from the supplied dataset (see data/students_current.md sample rows).
TRANSFER_JUNIOR = "CID-116490"
FIRST_TERM = "CID-227285"
IS_FRESHMAN = "CID-514009"
ALUMNUS = "CID-655977"


@pytest.fixture(scope="session")
def store():
    return load_data(BASE_DIR / "data")


@pytest.fixture(scope="session")
def profiles(store):
    return build_career_profiles(store.employment)


class FakeGemini:
    def __init__(self, reply="Here is my advice.", memories_json='{"memories": []}', error=None, configured=True):
        self.reply = reply
        self.memories_json = memories_json
        self.error = error
        self.configured = configured
        self.model = "fake-gemini"
        self.calls: list[dict] = []

    async def generate(self, system, prompt, *, json_output=False, temperature=0.4):
        self.calls.append({"system": system, "prompt": prompt, "json_output": json_output})
        if not self.configured:
            raise GeminiNotConfiguredError("not configured")
        if self.error:
            raise self.error
        return self.memories_json if json_output else self.reply


class FakeMemory:
    """In-process stand-in for Backboard; persists across requests like the real service."""

    def __init__(self, error=None, configured=True):
        self.store: dict[str, list[MemoryItem]] = {}
        self.error = error
        self.configured = configured

    def _check(self):
        if not self.configured:
            raise BackboardNotConfiguredError("not configured")
        if self.error:
            raise self.error

    async def search(self, campus_id, query, limit=8):
        self._check()
        return list(self.store.get(campus_id, []))[:limit]

    async def list(self, campus_id):
        self._check()
        return list(self.store.get(campus_id, []))

    async def add(self, campus_id, item):
        self._check()
        self.store.setdefault(campus_id, []).append(item)


@pytest.fixture(scope="session")
def app():
    settings = Settings(_env_file=None, gemini_api_key=None, backboard_api_key=None)
    return create_app(settings)


@pytest.fixture(scope="session")
def base_client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def make_client(app, base_client):
    def _make(gemini=None, memory=None):
        app.dependency_overrides[get_gemini] = lambda: gemini or FakeGemini()
        app.dependency_overrides[get_memory] = lambda: memory or FakeMemory()
        return base_client

    yield _make
    app.dependency_overrides.clear()


__all__ = ["FakeGemini", "FakeMemory", "GeminiError", "BackboardError"]
