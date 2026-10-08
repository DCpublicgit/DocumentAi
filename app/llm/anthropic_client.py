from typing import AsyncIterator

from anthropic import AsyncAnthropic

from app import usage


class AnthropicClient:
    # Overwritten by app.llm.build_client.
    provider = "anthropic"
    role = "answer"

    def _record_usage(self, raw) -> None:
        if raw is not None:
            usage.record(
                self.role, self.provider, self._model,
                int(raw.input_tokens or 0), int(raw.output_tokens or 0),
            )

    def __init__(self, model: str, api_key: str, max_tokens: int) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = AsyncAnthropic(api_key=api_key)
        # Set once the response completes: True when the model hit max_tokens
        # rather than finishing. Safe as instance state because get_client()
        # builds a fresh client per request.
        self.truncated = False

    async def generate(self, system: str, user: str, temperature: float | None = None) -> str:
        kwargs = {} if temperature is None else {"temperature": temperature}
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        self.truncated = response.stop_reason == "max_tokens"
        self._record_usage(getattr(response, "usage", None))
        return "".join(block.text for block in response.content if block.type == "text")

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
            self.truncated = final.stop_reason == "max_tokens"
            self._record_usage(getattr(final, "usage", None))
