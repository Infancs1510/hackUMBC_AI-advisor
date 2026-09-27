from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["student", "advisor"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100, description="Campus ID for students, advisor username for advisors.")
    password: str = Field(min_length=1, max_length=200)


class CurrentUser(BaseModel):
    role: Role
    campus_id: str | None = Field(description="Set for students; null for advisors.")
    display_name: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: int = Field(description="Unix timestamp (seconds).")
    user: CurrentUser
