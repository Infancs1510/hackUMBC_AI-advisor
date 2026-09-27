import pytest
from fastapi.testclient import TestClient

from app.ai.backboard import BackboardError, BackboardNotConfiguredError
from app.ai.gemini import GeminiError, GeminiNotConfiguredError
from app.api.deps import get_gemini, get_memory
from app.config import BASE_DIR, Settings
from app.data.loader import load_data
from app.main import create_app
from app.models.advisor import MemoryItem
from app.models.auth import CurrentUser
from app.services.career_matching import build_career_profiles

# Real students from the supplied dataset (see data/students_current.md sample rows).
TRANSFER_JUNIOR = "CID-116490"
FIRST_TERM = "CID-227285"
IS_FRESHMAN = "CID-514009"
ALUMNUS = "CID-655977"

STUDENT_PASSWORD = "student-pw"
ADVISOR_PASSWORD = "advisor-pw"


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
        self.goals: dict[str, str] = {}
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

    async def get_career_goal(self, campus_id):
        self._check()
        return self.goals.get(campus_id)

    async def set_career_goal(self, campus_id, career):
        self._check()
        self.goals[campus_id] = career


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    settings = Settings(
        _env_file=None,
        app_db_path=tmp_path_factory.mktemp("appdata") / "test.db",
        gemini_api_key=None,
        backboard_api_key=None,
        auth_secret="test-secret",
        student_demo_password=STUDENT_PASSWORD,
        advisor_username="advisor",
        advisor_password=ADVISOR_PASSWORD,
    )
    return create_app(settings)


@pytest.fixture(scope="session")
def base_client(app):
    with TestClient(app) as client:
        yield client


def _headers(app, user: CurrentUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {app.state.auth.issue(user).token}"}


@pytest.fixture(scope="session")
def advisor_client(app, base_client):
    """Signed in as an advisor. Shares app state (loaded by base_client's lifespan)."""
    return TestClient(app, headers=_headers(app, CurrentUser(role="advisor", campus_id=None, display_name="Advisor")))


@pytest.fixture(scope="session")
def student_client(app, base_client):
    """Factory: a client signed in as the given current student."""

    def _make(campus_id: str = TRANSFER_JUNIOR) -> TestClient:
        user = CurrentUser(role="student", campus_id=campus_id, display_name=campus_id)
        return TestClient(app, headers=_headers(app, user))

    return _make


@pytest.fixture
def make_client(app, student_client):
    """A student-signed-in client with fake Gemini/Backboard injected."""

    def _make(gemini=None, memory=None, as_student: str = TRANSFER_JUNIOR):
        app.dependency_overrides[get_gemini] = lambda: gemini or FakeGemini()
        app.dependency_overrides[get_memory] = lambda: memory or FakeMemory()
        return student_client(as_student)

    yield _make
    app.dependency_overrides.clear()


__all__ = ["FakeGemini", "FakeMemory", "GeminiError", "BackboardError"]
