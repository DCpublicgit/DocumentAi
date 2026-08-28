"""Standalone-query rewriting: condenses the newest question plus the prior
conversation turns into one context-free query BEFORE retrieval runs. A
followup like "Тэгвэл цалинтай юу?" ("Is it paid, then?") only means
anything next to the turn before it ("Жирэмсний амралт хэдэн хоног вэ?") —
embedding and FTS see nothing but the followup's own words, so without this
step a pronoun-only question retrieves against the pronoun, not against what
it refers to. Runs BEFORE query expansion (app.retrieve.query_expansion):
expansion still fans the REWRITTEN query into alternate phrasings exactly as
it always has, unaware anything upstream changed.

Own provider/model env vars (QUERY_REWRITE_PROVIDER/QUERY_REWRITE_MODEL) —
see app/config.py's comment; same reasoning as query expansion's.
"""

import logging

from app.config import settings
from app.llm import build_client
from app.retrieve.rephrase_cache import BoundedCache

logger = logging.getLogger(__name__)

# Keyed on everything that actually determines the output. See
# query_expansion.py's identical cache for why, and rephrase_cache.py for
# the full reasoning.
_cache = BoundedCache()


def clear_cache() -> None:
    """Test-only — see query_expansion.clear_cache."""
    _cache.clear()

_ROLE_LABEL = {"user": "Хэрэглэгч", "assistant": "Туслах"}

_SYSTEM_PROMPT = """Та компанийн бодлогын чатботын яриаг хайлтад бэлтгэх систем юм.
Өгөгдсөн өмнөх яриа болон хэрэглэгчийн сүүлийн асуултыг ашиглаж, сүүлийн
асуултыг ӨМНӨХ ЯРИАГҮЙгээр ч ганцаараа бүрэн ойлгогдох нэг асуулт болгож
дахин найруул.

Дүрэм:
1. Сүүлийн асуултад орсон төлөөний үг, товчилсон илэрхийлэл ("тэр", "энэ",
   "тэгвэл", "яах вэ" гэх мэт) юуг зааж байгааг өмнөх яриаас олж, тэдгээрийн
   оронд тодорхой нэр томьёог бич.
2. Сүүлийн асуултын утга, хамрах хүрээг өөрчлөхгүй — зөвхөн тодорхой бус
   зүйлийг өмнөх яриан дахь мэдээллээр нөхөж бич, шинэ агуулга бүү нэм.
3. Хэрэв сүүлийн асуулт өмнөх ярианаас үл хамааран өөрөө аль хэдийн бүрэн
   ойлгогдож байвал огт өөрчлөлгүй яг тэр хэвээр нь гарга.
4. Асуултад БҮҮ хариул — зөвхөн дахин найруулсан асуултыг л гарга.
5. Яг нэг мөр, тайлбаргүй, дугаарлахгүй гарга."""


async def rewrite_standalone_query(question: str, history: list[tuple[str, str]]) -> str:
    """Returns `question` unchanged when there is no history (first turn of a
    conversation — nothing to resolve against) or QUERY_REWRITE_ENABLED is
    false, with no LLM call in either case.

    Rewriting is a retrieval-quality optimization, never a dependency of
    answering: ANY failure (rate limit, missing key, bad provider name)
    degrades to the original question rather than failing the request — same
    fail-open posture as app.retrieve.query_expansion.expand_query. Logged at
    WARNING so a silently-degraded deployment is still visible.

    `history` is [(role, content), ...] for every turn BEFORE the current
    question, oldest first — see app.server._split_history.
    """
    if not history or not settings.query_rewrite_enabled:
        return question

    cache_key = (
        question,
        tuple(history),
        settings.query_rewrite_provider,
        settings.query_rewrite_model,
    )
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        client = build_client(
            settings.query_rewrite_provider,
            settings.query_rewrite_model,
            setting_name="QUERY_REWRITE_PROVIDER",
        )
        transcript = "\n".join(
            f"{_ROLE_LABEL.get(role, role)}: {content}" for role, content in history
        )
        user_message = f"{transcript}\nХэрэглэгч (сүүлийн асуулт): {question}"
        # temperature=0 — same reasoning as query_expansion.expand_query:
        # this decides what gets embedded and searched, so the same
        # followup should resolve to the same standalone question every
        # time, not a fresh sample each request. Doesn't fully get there on
        # its own — the cache above is what actually closes the gap; see
        # rephrase_cache.py.
        rewritten = (await client.generate(_SYSTEM_PROMPT, user_message, temperature=0)).strip()
    except Exception:
        logger.warning(
            "query rewriting failed (provider=%s model=%s) — falling back to the "
            "original question; retrieval continues",
            settings.query_rewrite_provider,
            settings.query_rewrite_model,
            exc_info=True,
        )
        return question

    # An empty completion is as unusable as a failure — fall back the same way
    # rather than handing retrieval an empty query. Neither is cached: both
    # are exactly the "nothing usable happened" case, not a real answer.
    result = rewritten or question
    if rewritten:
        _cache.set(cache_key, result)
    return result
