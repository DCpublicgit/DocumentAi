"""Query expansion: rewrites the user's question into alternate phrasings
before retrieval, so hybrid search also catches policy-document terminology
that differs from the user's own wording (e.g. "амралтын хүсэлт" vs "чөлөө
авах" for a leave request). Env-gated per docs/DATA_CONTRACT.md
(QUERY_EXPANSION_ENABLED) so it's an A/B-able dimension in the Phase 5 eval,
not baked-in behavior.

One LLM call produces all QUERY_EXPANSION_N rephrasings at once — never N
separate calls. Runs on QUERY_EXPANSION_PROVIDER/QUERY_EXPANSION_MODEL,
deliberately separate from LLM_PROVIDER/LLM_MODEL: expansion is an axis
orthogonal to the generation-model comparison (V1-V6 in the eval runbook),
and must not vary when that comparison swaps generation providers.

Separate does not mean hardcoded, though. The provider is its own env var
(defaulting to anthropic) so an Ollama-only or hosted-provider deployment
can point expansion at the model it actually has credentials for, instead
of every question silently requiring an Anthropic key. A missing key fails
at client construction with a named setting, not as a 401 mid-request.
"""

import logging

from app.config import settings
from app.llm import build_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Та компанийн бодлогын чатботын хайлтад туслах систем юм.
Өгөгдсөн асуултыг өөр өөр үг хэллэгээр яг {n} удаа дахин найруул.

Дүрэм:
1. Асуултын утгыг өөрчлөхгүйгээр өөр нэр томьёо, ижил утгатай үг хэллэг ашигла
   (жишээ нь "чөлөө авах" гэсний оронд "амралтын хүсэлт" гэх мэт) — учир нь
   бодлогын баримт бичигт хэрэглэгчийн хэрэглэснээс өөр үг хэллэг байж болно.
2. Асуултад орсон тоо, дүрмийн нэр, товчлол зэрэг тодорхой нэр томьёог
   (жишээ нь "3-2-1", "ISO 27001", огноо, кодын дугаар) хэвээр нь, огт
   өөрчлөлгүй үлдээ — эдгээрийг ерөнхий үг рүү сольвол хайлт өөр сэдэв рүү
   шилжиж, буруу баримт бичиг татагдах эрсдэлтэй.
3. Асуултын хамрах хүрээг өргөжүүлж, ерөнхийлж болохгүй. Яг ижил сэдэв, яг
   ижил тодорхой түвшинд өөр үгээр илэрхийл — илүү өргөн, ерөнхий сэдэв рүү
   бүү шилжүүл.
4. Яг {n} мөр гарга — мөр бүрт нэг дахин найруулсан асуулт.
5. Дугаарлахгүй, тайлбар нэмэхгүй, зөвхөн асуултуудыг л гарга."""


async def expand_query(question: str) -> list[str]:
    """Returns [question, *rephrasings]. QUERY_EXPANSION_ENABLED=false is a
    pure no-op: returns [question] with no LLM call, so retrieval runs the
    same single-query path it always has.

    Expansion is a recall optimization, never a dependency of answering: ANY
    failure degrades to [question] — the exact single-query path used when the
    feature is off — rather than failing the request. A rate limit from the
    expansion provider (likely on a free tier), a missing key, or a
    misconfigured provider name must not turn an answerable question into a
    500. Logged at WARNING so a silently-degraded deployment is still visible.
    """
    if not settings.query_expansion_enabled:
        return [question]

    try:
        client = build_client(
            settings.query_expansion_provider,
            settings.query_expansion_model,
            setting_name="QUERY_EXPANSION_PROVIDER",
        )
        system = _SYSTEM_PROMPT.format(n=settings.query_expansion_n)
        response = await client.generate(system, question)
    except Exception:
        logger.warning(
            "query expansion failed (provider=%s model=%s) — falling back to the "
            "unexpanded question; retrieval continues",
            settings.query_expansion_provider,
            settings.query_expansion_model,
            exc_info=True,
        )
        return [question]

    rephrasings = [line.strip() for line in response.strip().splitlines() if line.strip()]
    return [question] + rephrasings[: settings.query_expansion_n]
