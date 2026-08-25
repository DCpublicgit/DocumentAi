"""Constants that are authoritative per docs/DATA_CONTRACT.md.

Do not duplicate or reword these elsewhere — import from here.
"""

REFUSAL_STRING = (
    "Уучлаарай, энэ асуултын хариултыг компанийн бодлогын баримт бичгээс "
    "олж чадсангүй."
)


def is_refusal(text: str) -> bool:
    """Whether an answer is the refusal, tolerating cosmetic drift.

    Exact equality is too brittle here: models routinely echo the required
    sentence with a trailing period, surrounding quotes, or wrapped
    whitespace. Treating such an answer as a real answer is the damaging
    direction of error — it appends a citation list to a refusal, which is
    the one thing CONTRIBUTING.md rule 2 says must never ship (a citation implies
    the policy documents support the statement). So normalize the cosmetics,
    then compare.

    Deliberately NOT a substring/prefix test: an answer that merely mentions
    the refusal wording while going on to answer is a real answer and must
    keep its citations.

    Empty output is deliberately NOT a refusal. A refusal is a factual claim
    to the employee — "this is not in company policy" — and a provider that
    returned nothing (filtered, rate-limited, or reasoning-truncated to zero
    output tokens) is evidence of no such thing. Reporting an outage as a
    refusal would tell someone their question isn't covered by policy when it
    may well be, which is worse than an honest error. Callers must treat empty
    output as a failure; see app.answering.EmptyCompletionError.
    """
    return _normalize_refusal(text) == _normalize_refusal(REFUSAL_STRING)


def _normalize_refusal(text: str) -> str:
    # casefold too: a case-shifted refusal would otherwise read as a real
    # answer and get a citation list appended. No real answer differs from the
    # refusal by case alone, so this only ever errs toward refusing.
    return " ".join(text.split()).strip("\"'«»„“”").rstrip(".").strip().casefold()

# docs/DATA_CONTRACT.md: "merged via Reciprocal Rank Fusion (RRF, k=60)"
RRF_K = 60
