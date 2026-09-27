"""Simple demo authentication with stateless HMAC-signed tokens.

Token format: base64url(json payload) + "." + base64url(HMAC-SHA256(payload)).
This is deliberately minimal for a hackathon demo -- shared demo passwords, no user table.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from app.data.loader import DataStore
from app.models.advisor import CAMPUS_ID_PATTERN
from app.models.auth import CurrentUser, LoginResponse


class AuthError(Exception):
    """Invalid credentials or token."""


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class AuthService:
    def __init__(
        self,
        secret: str | None,
        ttl_minutes: int,
        student_password: str,
        advisor_username: str,
        advisor_password: str,
    ):
        self.ephemeral_secret = not secret
        self._secret = (secret or secrets.token_urlsafe(32)).encode()
        self._ttl_seconds = ttl_minutes * 60
        self._student_password = student_password
        self._advisor_username = advisor_username
        self._advisor_password = advisor_password

    # --- tokens --------------------------------------------------------------------

    def _sign(self, payload: bytes) -> str:
        return _b64encode(hmac.new(self._secret, payload, hashlib.sha256).digest())

    def issue(self, user: CurrentUser, now: float | None = None) -> LoginResponse:
        expires_at = int((now or time.time()) + self._ttl_seconds)
        payload = json.dumps(
            {"role": user.role, "sub": user.campus_id, "exp": expires_at}, separators=(",", ":")
        ).encode()
        token = f"{_b64encode(payload)}.{self._sign(payload)}"
        return LoginResponse(token=token, expires_at=expires_at, user=user)

    def verify(self, token: str, now: float | None = None) -> CurrentUser:
        try:
            encoded, signature = token.split(".", 1)
            payload = _b64decode(encoded)
        except (ValueError, TypeError) as exc:
            raise AuthError("Malformed token") from exc
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise AuthError("Invalid token signature")
        try:
            data = json.loads(payload)
            role, subject, expires_at = data["role"], data["sub"], int(data["exp"])
        except (ValueError, KeyError, TypeError) as exc:
            raise AuthError("Malformed token") from exc
        if expires_at < (now or time.time()):
            raise AuthError("Session expired")
        if role == "advisor":
            return CurrentUser(role="advisor", campus_id=None, display_name="Advisor")
        if role == "student" and isinstance(subject, str):
            return CurrentUser(role="student", campus_id=subject, display_name=subject)
        raise AuthError("Malformed token")

    # --- login ---------------------------------------------------------------------

    def login(self, username: str, password: str, store: DataStore) -> LoginResponse:
        """Advisors use the configured username; students use a current-student campus_id.

        Every failure returns the same error so the response does not reveal which IDs exist.
        """
        username = username.strip()
        if hmac.compare_digest(username.casefold(), self._advisor_username.casefold()):
            if hmac.compare_digest(password, self._advisor_password):
                return self.issue(CurrentUser(role="advisor", campus_id=None, display_name="Advisor"))
            raise AuthError("Invalid username or password")

        campus_id = username.upper()
        valid_student = re.fullmatch(CAMPUS_ID_PATTERN, campus_id) and store.is_student(campus_id)
        password_ok = hmac.compare_digest(password, self._student_password)
        if valid_student and password_ok:
            return self.issue(CurrentUser(role="student", campus_id=campus_id, display_name=campus_id))
        raise AuthError("Invalid username or password")
