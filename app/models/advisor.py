from typing import Literal

from pydantic import BaseModel, Field

CAMPUS_ID_PATTERN = r"^CID-\d{6}$"

MemoryCategory = Literal["career_interest", "goal", "preference", "context"]
ServiceState = Literal["ok", "not_configured", "error"]


class AdvisorRequest(BaseModel):
    campus_id: str = Field(pattern=CAMPUS_ID_PATTERN, examples=["CID-116490"])
    message: str = Field(min_length=1, max_length=2000, examples=["What should I take next semester?"])
    career: str | None = Field(default=None, description="Optional career to focus on; defaults to the top match.")


class MemoryItem(BaseModel):
    content: str
    category: str | None = None


class ServiceStatus(BaseModel):
    gemini: ServiceState
    backboard: ServiceState


class AdvisorResponse(BaseModel):
    campus_id: str
    reply: str
    focus_career: str | None
    recommended_course_ids: list[str] = Field(description="Catalog courses included in the AI context.")
    memories_used: list[MemoryItem]
    memories_saved: list[MemoryItem]
    services: ServiceStatus


class MemoryListResponse(BaseModel):
    campus_id: str
    memories: list[MemoryItem]
    backboard: ServiceState
