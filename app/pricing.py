"""USD price per 1M tokens, keyed by (provider, model). The one place prices
live; every cost figure in the audit table and the eval reports is derived
from it.

A model with no entry is UNPRICED, not free: cost_usd() returns None and every
report says so, because a silently-zero cost would make an expensive model
look cheap in a comparison. Add the entry (with its source and date) before
trusting any cost for that model. Verify against the provider's pricing page
on the "as of" date, not from memory — prices move, and some are promotional.
"""

# (provider, model) -> (input $/1M, output $/1M, note)
PRICES: dict[tuple[str, str], tuple[float, float, str]] = {
    # Google Gemini API, Standard tier, ai.google.dev/gemini-api/docs/pricing, as of 2026-10-07.
    ("gemini", "gemini-3.5-flash-lite"): (0.30, 2.50, "Gemini Standard, 2026-10-07"),
    ("gemini", "gemini-3.1-flash-lite"): (0.25, 1.50, "Gemini Standard, 2026-10-07"),
    ("gemini", "gemini-3.5-flash"): (1.50, 9.00, "Gemini Standard, 2026-10-07"),
    # Promotional until 2026-12-31; the page lists $1.50 / $7.50 from 2027-01-01.
    ("gemini", "gemini-3.8-flash"): (0.75, 3.75, "Gemini Standard, promo until 2026-12-31"),
    # The alias is priced as what it pointed to when checked (gemini-3.5-flash-lite,
    # per pydantic/genai-prices#679). Pin the real model name to get a trustworthy figure.
    ("gemini", "gemini-flash-lite-latest"): (0.30, 2.50, "alias, assumed 3.5-flash-lite"),
}

# Local models cost no API money (server cost is separate and fixed).
_FREE_PROVIDERS = {"ollama"}


def price_per_million(provider: str, model: str) -> tuple[float, float] | None:
    if provider in _FREE_PROVIDERS:
        return 0.0, 0.0
    entry = PRICES.get((provider, model))
    return None if entry is None else (entry[0], entry[1])


def cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> float | None:
    price = price_per_million(provider, model)
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000
