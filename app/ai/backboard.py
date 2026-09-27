"""Backboard memory store: career interests, goals, and preferences only.

Each student gets their own Backboard assistant, because Backboard memories live at the
assistant level; this keeps one student's memories out of another's searches. The assistant
name is derived from a hash of the campus_id so the raw ID is not sent to Backboard, and it is
looked up by name so memory survives server restarts.
"""

import asyncio
import hashlib
import logging

import httpx

from app.models.advisor import MemoryItem

logger = logging.getLogger(__name__)

ASSISTANT_SYSTEM_PROMPT = (
    "Memory store for a university career advisor. Holds only a student's career interests, "
    "goals, and preferences. Academic records live elsewhere and are authoritative."
)


CAREER_GOAL_KIND = "career_goal"


class BackboardError(RuntimeError):
    pass


class BackboardNotConfiguredError(BackboardError):
    pass


class BackboardMemory:
    def __init__(
        self,
        api_key: str | None,
        base_url: str = "https://app.backboard.io/api",
        assistant_prefix: str = "hackumbc-advisor",
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._prefix = assistant_prefix
        self._timeout = timeout
        self._transport = transport
        self._assistant_ids: dict[str, str] = {}
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def assistant_name(self, campus_id: str) -> str:
        digest = hashlib.sha256(campus_id.encode()).hexdigest()[:16]
        return f"{self._prefix}-{digest}"

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.configured:
            raise BackboardNotConfiguredError("BACKBOARD_API_KEY is not set")
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.request(method, path, headers={"X-API-Key": self._api_key}, **kwargs)
        except httpx.HTTPError as exc:
            raise BackboardError(f"Backboard request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise BackboardError(f"Backboard {method} {path} returned HTTP {response.status_code}: {response.text[:300]}")
        return response

    async def _assistant_id(self, campus_id: str, create: bool = True) -> str | None:
        if campus_id in self._assistant_ids:
            return self._assistant_ids[campus_id]
        async with self._lock:
            if campus_id in self._assistant_ids:
                return self._assistant_ids[campus_id]
            name = self.assistant_name(campus_id)
            found = (await self._request("GET", "/assistants", params={"name": name, "limit": 1})).json()
            if found:
                assistant_id = found[0]["assistant_id"]
            elif create:
                created = await self._request(
                    "POST", "/assistants", json={"name": name, "system_prompt": ASSISTANT_SYSTEM_PROMPT}
                )
                assistant_id = created.json()["assistant_id"]
            else:
                return None
            self._assistant_ids[campus_id] = assistant_id
            return assistant_id

    @staticmethod
    def _to_items(payload: dict) -> list[MemoryItem]:
        items = []
        for memory in payload.get("memories", []):
            metadata = memory.get("metadata") or {}
            items.append(MemoryItem(content=memory["content"], category=metadata.get("category")))
        return items

    async def search(self, campus_id: str, query: str, limit: int = 8) -> list[MemoryItem]:
        assistant_id = await self._assistant_id(campus_id, create=False)
        if assistant_id is None:
            return []
        response = await self._request(
            "POST", f"/assistants/{assistant_id}/memories/search", json={"query": query, "limit": limit}
        )
        return self._to_items(response.json())

    async def list(self, campus_id: str) -> list[MemoryItem]:
        assistant_id = await self._assistant_id(campus_id, create=False)
        if assistant_id is None:
            return []
        response = await self._request("GET", f"/assistants/{assistant_id}/memories")
        return self._to_items(response.json())

    async def _raw_memories(self, campus_id: str) -> tuple[str | None, list[dict]]:
        assistant_id = await self._assistant_id(campus_id, create=False)
        if assistant_id is None:
            return None, []
        response = await self._request("GET", f"/assistants/{assistant_id}/memories")
        return assistant_id, response.json().get("memories", [])

    async def get_career_goal(self, campus_id: str) -> str | None:
        _, memories = await self._raw_memories(campus_id)
        for memory in memories:
            metadata = memory.get("metadata") or {}
            if metadata.get("kind") == CAREER_GOAL_KIND and metadata.get("career"):
                return metadata["career"]
        return None

    async def set_career_goal(self, campus_id: str, career: str) -> None:
        """Replace any saved career goal with this one (a goal is a preference, not an academic fact)."""
        assistant_id, memories = await self._raw_memories(campus_id)
        for memory in memories:
            if (memory.get("metadata") or {}).get("kind") == CAREER_GOAL_KIND:
                await self._request("DELETE", f"/assistants/{assistant_id}/memories/{memory['id']}")
        assistant_id = await self._assistant_id(campus_id, create=True)
        await self._request(
            "POST",
            f"/assistants/{assistant_id}/memories",
            json={
                "content": f"Primary career goal: {career}.",
                "metadata": {"category": "goal", "kind": CAREER_GOAL_KIND, "career": career, "source": "career_pathways"},
            },
        )

    async def add(self, campus_id: str, item: MemoryItem) -> None:
        assistant_id = await self._assistant_id(campus_id, create=True)
        await self._request(
            "POST",
            f"/assistants/{assistant_id}/memories",
            json={"content": item.content, "metadata": {"category": item.category, "source": "advisor"}},
        )
