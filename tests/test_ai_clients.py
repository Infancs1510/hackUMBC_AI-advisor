"""HTTP-level tests for the Gemini and Backboard clients using httpx.MockTransport."""

import asyncio
import json

import httpx
import pytest

from app.ai.backboard import BackboardError, BackboardMemory, BackboardNotConfiguredError
from app.ai.gemini import GeminiClient, GeminiError, GeminiNotConfiguredError
from app.models.advisor import MemoryItem


def run(coro):
    return asyncio.run(coro)


def test_gemini_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["x-goog-api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "Hi there"}]}}]})

    client = GeminiClient("k", "gemini-test", transport=httpx.MockTransport(handler))
    assert run(client.generate("sys", "prompt", json_output=True)) == "Hi there"
    assert seen["url"].endswith("/models/gemini-test:generateContent")
    assert seen["key"] == "k"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_errors():
    with pytest.raises(GeminiNotConfiguredError):
        run(GeminiClient(None, "m").generate("s", "p"))
    failing = GeminiClient("k", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500, text="err")), retry_delay=0)
    with pytest.raises(GeminiError):
        run(failing.generate("s", "p"))
    empty = GeminiClient("k", "m", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": []})))
    with pytest.raises(GeminiError):
        run(empty.generate("s", "p"))


class FakeBackboardServer:
    def __init__(self):
        self.assistants: dict[str, str] = {}
        self.memories: dict[str, list[dict]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "bb-key"
        path = request.url.path.removeprefix("/api")
        if request.method == "GET" and path == "/assistants":
            name = request.url.params["name"]
            found = [{"assistant_id": aid, "name": name} for n, aid in self.assistants.items() if n == name]
            return httpx.Response(200, json=found)
        if request.method == "POST" and path == "/assistants":
            body = json.loads(request.content)
            aid = f"asst-{len(self.assistants) + 1}"
            self.assistants[body["name"]] = aid
            return httpx.Response(200, json={"assistant_id": aid, "name": body["name"]})
        aid = path.split("/")[2]
        if request.method == "DELETE":
            memory_id = path.rsplit("/", 1)[1]
            self.memories[aid] = [m for m in self.memories.get(aid, []) if m["id"] != memory_id]
            return httpx.Response(200, json={"success": True, "message": "deleted"})
        if request.method == "POST" and path.endswith("/memories"):
            body = json.loads(request.content)
            self.next_id = getattr(self, "next_id", 0) + 1
            self.memories.setdefault(aid, []).append({"id": f"m{self.next_id}", **body})
            return httpx.Response(201, json={})
        if path.endswith("/memories/search") or path.endswith("/memories"):
            items = self.memories.get(aid, [])
            return httpx.Response(200, json={"memories": items, "total_count": len(items)})
        return httpx.Response(404)


def test_backboard_memory_persists_via_assistant_lookup():
    server = FakeBackboardServer()

    def client():
        return BackboardMemory("bb-key", "https://bb.test/api", transport=httpx.MockTransport(server))

    first = client()
    assert run(first.search("CID-111111", "anything")) == []
    assert server.assistants == {}  # searching does not create assistants
    run(first.add("CID-111111", MemoryItem(content="Interested in cloud.", category="career_interest")))
    assert len(server.assistants) == 1
    assert "CID-111111" not in next(iter(server.assistants))  # raw ID is not sent

    # A new client instance (e.g. after a server restart) finds the same assistant.
    second = client()
    found = run(second.search("CID-111111", "cloud"))
    assert found == [MemoryItem(content="Interested in cloud.", category="career_interest")]
    assert run(second.list("CID-222222")) == []


def test_backboard_errors():
    with pytest.raises(BackboardNotConfiguredError):
        run(BackboardMemory(None).search("CID-111111", "q"))
    failing = BackboardMemory("bb-key", transport=httpx.MockTransport(lambda r: httpx.Response(401, text="no")))
    with pytest.raises(BackboardError):
        run(failing.search("CID-111111", "q"))


def test_gemini_retries_transient_errors():
    responses = [httpx.Response(503, text="overloaded"),
                 httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})]
    client = GeminiClient("k", "m", transport=httpx.MockTransport(lambda r: responses.pop(0)), retry_delay=0)
    assert run(client.generate("s", "p")) == "ok"


def test_gemini_falls_back_on_quota_without_retrying():
    seen = []

    def handler(request):
        model = request.url.path.split("/models/")[1].split(":")[0]
        seen.append(model)
        if model == "primary":
            return httpx.Response(429, text="quota")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "from fallback"}]}}]})

    client = GeminiClient("k", "primary", transport=httpx.MockTransport(handler), retry_delay=0,
                          fallback_model="backup")
    assert run(client.generate("s", "p")) == "from fallback"
    assert seen == ["primary", "backup"]


def test_gemini_no_fallback_on_client_errors():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(400, text="bad request")

    client = GeminiClient("k", "primary", transport=httpx.MockTransport(handler), fallback_model="backup")
    with pytest.raises(GeminiError):
        run(client.generate("s", "p"))
    assert len(seen) == 1


def test_backboard_career_goal_replaces_previous():
    server = FakeBackboardServer()
    memory = BackboardMemory("bb-key", "https://bb.test/api", transport=httpx.MockTransport(server))
    assert run(memory.get_career_goal("CID-111111")) is None
    run(memory.add("CID-111111", MemoryItem(content="Prefers remote work.", category="preference")))
    run(memory.set_career_goal("CID-111111", "Cybersecurity"))
    run(memory.set_career_goal("CID-111111", "Health IT"))
    assert run(memory.get_career_goal("CID-111111")) == "Health IT"
    contents = [m["content"] for m in next(iter(server.memories.values()))]
    assert contents == ["Prefers remote work.", "Primary career goal: Health IT."]
