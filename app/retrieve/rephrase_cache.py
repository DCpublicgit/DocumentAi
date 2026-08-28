"""Tiny bounded in-memory cache shared by query_expansion.expand_query and
query_rewrite.rewrite_standalone_query.

Neither call depends on the corpus — only on a fixed system prompt plus the
question (and, for rewrite, the conversation history) it's given — so the
same input should resolve to the same output for the life of one running
process. Without this, the LLM call itself is the source of the flakiness:
Anthropic (like other hosted providers) doesn't guarantee identical output
for identical input even at temperature=0 — dynamic batching on their end
means floating-point rounding differs by what else is in that batch. That
was measured directly: the same question produced 2 different rephrasings
across repeated calls, and because the rephrasing is what actually gets
embedded and searched, that alone was enough to flip a borderline question
between answering and refusing (app/eval/questions.yaml repeat-run testing).

Caching converts that into "whichever phrasing won on the first ask, every
time after" — real consistency, which the provider's own determinism
guarantee doesn't reach. It does NOT change which phrasing wins that first
ask, so it doesn't by itself fix a question whose score sits right on the
refusal threshold — see both callers' docstrings.

Not `functools.lru_cache`: that decorator caches the coroutine OBJECT an
async function returns, not its awaited result — a second "hit" would try
to await an already-consumed coroutine and raise. This is deliberately
hand-rolled instead.

Process-lifetime only, cleared on restart — exactly when it should be: a
prompt or model change ships via redeploy, which restarts the process,
which drops anything cached against the old prompt.
"""

from collections import OrderedDict
from typing import Hashable

# A few hundred short strings costs nothing to keep — this bounds it purely
# so a long-running process can't grow the cache unboundedly, not because
# the pilot's real question volume is anywhere near this.
_DEFAULT_MAX_SIZE = 500


class BoundedCache:
    def __init__(self, max_size: int = _DEFAULT_MAX_SIZE) -> None:
        self._max_size = max_size
        self._store: OrderedDict[Hashable, object] = OrderedDict()

    def get(self, key: Hashable):
        """Returns the cached value, or None on a miss. None is never a
        legitimate cached value for either caller (a list of phrasings or a
        non-empty rewritten question), so this needs no separate sentinel."""
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def set(self, key: Hashable, value: object) -> None:
        self._store[key] = value
        self._store.move_to_end(key)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)  # evict least recently used

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
