"""Shared client for any OpenAI-compatible /chat/completions endpoint —
OpenAI, Gemini (via its OpenAI-compat endpoint), and DeepSeek all speak this
shape. Same wire format as OllamaClient, plus a bearer API key: hosted
providers require auth, local Ollama does not.

Hosted providers rate-limit. Without retries a 429 propagates to the employee
as a 500, and it is not hypothetical: a 30-question eval run lost 19 questions
to Gemini free-tier 429s, and because query expansion is a second call per
question it also silently degraded retrieval on the ones that survived. Both
call sites therefore retry transient failures with bounded exponential
backoff.

NOTE: AnthropicClient has the same gap and is deliberately untouched here —
it is a separate client and out of this change's scope.
"""

import asyncio
import json
import random
from typing import AsyncIterator

import httpx

from app.config import settings

# Transient upstream conditions worth another attempt: provider rate limiting
# (429) and server-side faults (5xx). Any other 4xx is a bad request — a
# malformed payload or a dead key — and retrying it only burns quota and
# delays surfacing the real error.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


def _retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Seconds to wait before the next attempt (attempt is 0-based).

    The provider's own Retry-After wins when present — it knows when its
    quota window actually resets, and guessing shorter just wastes an
    attempt. Otherwise exponential backoff with full jitter, so concurrent
    callers don't retry in lockstep and re-trigger the same limit together.
    """
    if response is not None:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(float(header), settings.llm_retry_max_delay)
            except ValueError:
                pass  # Retry-After may be an HTTP-date; fall through to backoff.
    backoff = min(
        settings.llm_retry_base_delay * (2**attempt), settings.llm_retry_max_delay
    )
    return backoff * (0.5 + random.random() / 2)


class OpenAICompatibleClient:
    def __init__(self, model: str, base_url: str, api_key: str, max_tokens: int) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        self._headers = {"Authorization": f"Bearer {api_key}"}
        # See AnthropicClient.truncated — finish_reason == "length" here.
        self.truncated = False

    def _payload(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "stream": stream,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    async def generate(self, system: str, user: str) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            for attempt in range(settings.llm_max_retries + 1):
                final = attempt == settings.llm_max_retries
                try:
                    response = await client.post(
                        f"{self._base_url}/chat/completions",
                        headers=self._headers,
                        json=self._payload(system, user, stream=False),
                    )
                except httpx.TransportError:
                    # Connection reset / DNS / timeout: no response to read a
                    # status off, but just as transient as a 503.
                    if final:
                        raise
                    await asyncio.sleep(_retry_delay(attempt, None))
                    continue

                if response.status_code in _RETRY_STATUS and not final:
                    await asyncio.sleep(_retry_delay(attempt, response))
                    continue

                response.raise_for_status()
                data = response.json()
                self.truncated = data["choices"][0].get("finish_reason") == "length"
                # content is null (not "") on a filtered or empty completion —
                # Gemini's OpenAI-compat endpoint does this. Returning None would
                # blow up on .strip() in app/answering.py; "" flows into the
                # empty-answer refusal path instead.
                return data["choices"][0]["message"].get("content") or ""

        raise AssertionError("unreachable: final attempt returns or raises")

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=300) as client:
            for attempt in range(settings.llm_max_retries + 1):
                final = attempt == settings.llm_max_retries
                # Only a failure BEFORE the first delta reaches the caller is
                # retryable: re-issuing the request after tokens have already
                # been yielded would duplicate them into the answer.
                started = False
                try:
                    async with client.stream(
                        "POST",
                        f"{self._base_url}/chat/completions",
                        headers=self._headers,
                        json=self._payload(system, user, stream=True),
                    ) as response:
                        if response.status_code >= 400:
                            # A streaming response's body must be read before
                            # its status can be raised on.
                            await response.aread()
                            if response.status_code in _RETRY_STATUS and not final:
                                await asyncio.sleep(_retry_delay(attempt, response))
                                continue
                        response.raise_for_status()

                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            payload = line[len("data:") :].strip()
                            if payload == "[DONE]":
                                break
                            choice = json.loads(payload)["choices"][0]
                            if choice.get("finish_reason") == "length":
                                self.truncated = True
                            delta = choice["delta"].get("content")
                            if delta:
                                started = True
                                yield delta
                    return
                except httpx.TransportError:
                    if final or started:
                        raise
                    await asyncio.sleep(_retry_delay(attempt, None))
                    continue
