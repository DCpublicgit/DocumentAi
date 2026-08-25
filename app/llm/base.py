"""Provider-swappable LLM client interface. See docs/DATA_CONTRACT.md env
vars LLM_PROVIDER / LLM_MODEL — the generation model must be swappable by
env with zero code change (Anthropic Haiku/Sonnet or local Ollama Qwen)."""

from typing import AsyncIterator, Protocol


class LLMClient(Protocol):
    async def generate(self, system: str, user: str) -> str: ...

    def stream(self, system: str, user: str) -> AsyncIterator[str]: ...
