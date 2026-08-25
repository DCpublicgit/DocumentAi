from app.config import settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMClient
from app.llm.ollama_client import OllamaClient
from app.llm.openai_compatible_client import OpenAICompatibleClient

__all__ = ["LLMClient", "build_client", "get_client"]

# provider -> (base_url setting, api_key setting) for the shared OpenAI-compatible client
_OPENAI_COMPATIBLE_PROVIDERS = {
    "openai": ("openai_base_url", "openai_api_key"),
    "gemini": ("gemini_base_url", "gemini_api_key"),
    "deepseek": ("deepseek_base_url", "deepseek_api_key"),
}


def build_client(provider: str, model: str, setting_name: str = "LLM_PROVIDER") -> LLMClient:
    """Builds a client for an explicit provider/model pair. Generation uses
    get_client() below; query expansion runs on its own provider setting (see
    app/retrieve/query_expansion.py), so the dispatch lives here once rather
    than being duplicated per caller.

    `setting_name` only names the env var in error messages, so a misconfigured
    expansion provider doesn't report itself as a bad LLM_PROVIDER.
    """
    if provider == "anthropic":
        _require_key(settings.anthropic_api_key, "ANTHROPIC_API_KEY", provider, setting_name)
        return AnthropicClient(model, settings.anthropic_api_key, settings.llm_max_tokens)
    if provider == "ollama":
        return OllamaClient(model, settings.ollama_base_url, settings.llm_max_tokens)
    if provider in _OPENAI_COMPATIBLE_PROVIDERS:
        base_url_attr, api_key_attr = _OPENAI_COMPATIBLE_PROVIDERS[provider]
        _require_key(
            getattr(settings, api_key_attr), api_key_attr.upper(), provider, setting_name
        )
        return OpenAICompatibleClient(
            model,
            getattr(settings, base_url_attr),
            getattr(settings, api_key_attr),
            settings.llm_max_tokens,
        )
    raise ValueError(f"Unknown {setting_name}: {provider!r}")


def _require_key(value: str, key_name: str, provider: str, setting_name: str) -> None:
    """Fails at construction rather than on the first request, so a missing
    key surfaces as a clear config error instead of a provider 401 buried in
    a stream."""
    if not value:
        raise ValueError(
            f"{setting_name}={provider!r} requires {key_name}, which is empty."
        )


def get_client() -> LLMClient:
    return build_client(settings.llm_provider, settings.llm_model)
