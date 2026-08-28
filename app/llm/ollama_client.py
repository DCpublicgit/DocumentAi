"""Local Ollama, via its OpenAI-compatible /chat/completions endpoint
(OLLAMA_BASE_URL already points at .../v1 per docs/DATA_CONTRACT.md)."""

import json
from typing import AsyncIterator

import httpx


class OllamaClient:
    def __init__(self, model: str, base_url: str, max_tokens: int) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens
        # See AnthropicClient.truncated — finish_reason == "length" here.
        self.truncated = False

    def _payload(
        self, system: str, user: str, stream: bool, temperature: float | None = None
    ) -> dict:
        payload = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "stream": stream,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        return payload

    async def generate(self, system: str, user: str, temperature: float | None = None) -> str:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                json=self._payload(system, user, stream=False, temperature=temperature),
            )
            response.raise_for_status()
            data = response.json()
            self.truncated = data["choices"][0].get("finish_reason") == "length"
            # Same null-content guard as OpenAICompatibleClient.
            return data["choices"][0]["message"].get("content") or ""

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                json=self._payload(system, user, stream=True),
            ) as response:
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
                        yield delta
