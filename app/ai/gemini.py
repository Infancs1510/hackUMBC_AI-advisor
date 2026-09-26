"""Minimal async Gemini client over the generateContent REST endpoint."""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

# Transient server errors are retried on the same model. A 429 means the model's quota is
# spent, so retrying it only burns more quota -- move straight to the fallback model instead.
RETRY_SAME_MODEL_STATUS = {500, 503}
FALLBACK_STATUS = {429, 500, 503}


class GeminiError(RuntimeError):
    pass


class GeminiNotConfiguredError(GeminiError):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 2,
        retry_delay: float = 1.0,
        fallback_model: str | None = None,
    ):
        self._api_key = api_key
        self.model = model
        self.fallback_model = fallback_model if fallback_model and fallback_model != model else None
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._max_attempts = max_attempts
        self._retry_delay = retry_delay

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        system: str,
        prompt: str,
        *,
        json_output: bool = False,
        temperature: float = 0.4,
    ) -> str:
        if not self.configured:
            raise GeminiNotConfiguredError("GEMINI_API_KEY is not set")

        generation_config: dict = {"temperature": temperature}
        if json_output:
            generation_config["responseMimeType"] = "application/json"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        models = [self.model] + ([self.fallback_model] if self.fallback_model else [])
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                for model in models:
                    url = f"{self._base_url}/models/{model}:generateContent"
                    for attempt in range(1, self._max_attempts + 1):
                        response = await client.post(url, json=body, headers={"x-goog-api-key": self._api_key})
                        if response.status_code not in RETRY_SAME_MODEL_STATUS or attempt == self._max_attempts:
                            break
                        await asyncio.sleep(self._retry_delay * attempt)
                    if response.status_code not in FALLBACK_STATUS:
                        break
                    logger.warning("Gemini model %s returned HTTP %s", model, response.status_code)
        except httpx.HTTPError as exc:
            raise GeminiError(f"Gemini request failed: {type(exc).__name__}") from exc

        if response.status_code != 200:
            raise GeminiError(f"Gemini returned HTTP {response.status_code}: {response.text[:300]}")

        try:
            candidate = response.json()["candidates"][0]
            parts = candidate["content"]["parts"]
        except (KeyError, IndexError, ValueError) as exc:
            raise GeminiError("Gemini response had no content") from exc
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        if not text:
            raise GeminiError("Gemini response was empty")
        return text
