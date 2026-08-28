"""Provider-swappable LLM client interface. See docs/DATA_CONTRACT.md env
vars LLM_PROVIDER / LLM_MODEL — the generation model must be swappable by
env with zero code change (Anthropic Haiku/Sonnet or local Ollama Qwen)."""

from typing import AsyncIterator, Protocol


class LLMClient(Protocol):
    # temperature=None leaves the provider's own default in place (the main
    # answer generation path never passes it — that response should stay
    # naturally worded, not deterministic). Query rewriting/expansion pass
    # 0 explicitly: those calls only decide what gets embedded and searched,
    # never anything an employee reads, and their whole point is to be the
    # SAME standalone query every time the same question is asked — sampling
    # a different rephrasing on every request measurably shifts retrieval's
    # top_score run to run, occasionally enough to flip a borderline
    # question between answering and refusing (found via
    # app/eval/questions.yaml repeat-run testing).
    async def generate(self, system: str, user: str, temperature: float | None = None) -> str: ...

    def stream(self, system: str, user: str) -> AsyncIterator[str]: ...
