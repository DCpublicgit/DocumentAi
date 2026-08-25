"""Cheap, deterministic gate for input that never had linguistic structure to
begin with — keyboard mashing ("цйбйцанжуа", "kjshdf lkjashdf") rather than a
real question in any language. Runs BEFORE query expansion, embedding, FTS,
and reranking (see app.answering._retrieve_and_prepare), so junk input costs
microseconds instead of an LLM round trip, an embedding call, and a database
query. See docs/DATA_CONTRACT.md "Gibberish gate".

This is deliberately NOT a general off-topic detector: a fluent-but-off-topic
question (real words, wrong subject — "Улаанбаатар хотын цаг агаар ямар вэ?")
has real linguistic structure and passes straight through this gate untouched.
That case is still (imperfectly) handled downstream by SCORE_THRESHOLD and the
model's own refusal instruction — a much harder problem this module does not
attempt, because a false positive here (refusing a real question) is worse
than a false negative (falling through to the slower, but still correct,
existing path).

Biased hard toward false-negatives over false-positives, same fail-open
posture as app.retrieve.query_expansion's failure handling and
app.answering._resolve_used_context: missing a piece of gibberish just costs
the normal retrieval latency it costs today; wrongly flagging a real question
tells an employee their question doesn't make sense.
"""

import re

from app.config import settings

# Cyrillic (Mongolian) + Latin vowels, upper and lower. Iotated Cyrillic
# vowels (е, ё, ю, я) count as vowels — they always carry a vowel sound.
# 'ы' and 'й' are included too: excluding them was the first cut of this
# heuristic, checked only by eye against a handful of gibberish strings — it
# flagged ~40% of app/eval/questions.yaml's real questions as gibberish,
# because 'ы' is exactly the connecting vowel in the extremely common
# genitive/accusative suffixes "-ын"/"-ыг" ("байдлын", "ажилтныг"), and 'й'
# is a semivowel that breaks a consonant cluster the same way. 'ь'/'ъ' (soft/
# hard sign — palatalization markers, not consonant sounds) are included as
# vowels for the same reason: run-breaking, not because they're vowels.
# Recheck against app/eval/questions.yaml (all 78, zero should flag) before
# narrowing this set again.
_VOWELS = set("aeiouAEIOU" "аэиоуөүыйьъеёюяАЭИОУӨҮЫЙЬЪЕЁЮЯ")

# Letter-only runs, any script — digits and punctuation break a run.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# A digit run sandwiched between TWO separate letter runs with no separator
# ("aawdwad45h64") — real questions reference numbers with a unit, space, or
# punctuation around them ("15 хоног", "4.2-р зүйл", "P1", "CVSS", "ISO
# 27001"; a single letter-digit boundary, not one on both sides), never
# letters-digits-letters fused into one token.
_DIGIT_FUSED_LETTERS_RE = re.compile(r"[^\W\d_]+\d+[^\W\d_]", re.UNICODE)


def _longest_vowelless_run(word: str) -> int:
    longest = run = 0
    for ch in word:
        if ch in _VOWELS:
            run = 0
        else:
            run += 1
            longest = max(longest, run)
    return longest


def is_gibberish(text: str) -> bool:
    """True for input with no linguistic structure in any script.

    Two independent signals, either one enough to flag:
      - a run of GIBBERISH_MAX_CONSONANT_RUN or more consonants in a row
        within one letters-only token (real Mongolian and English words don't
        do this — even a common Mongolian word like "шаардлага" tops out at a
        3-consonant run, "рдл").
      - a digit run fused directly onto letters on both sides, anywhere in
        the message — not how numbers appear in a real question.

    Empty input, and input that is nothing but digits/punctuation, are not
    this gate's problem — they fall through to retrieval/refusal as before.
    """
    stripped = text.strip()
    if not stripped:
        return False

    if _DIGIT_FUSED_LETTERS_RE.search(stripped):
        return True

    return any(
        _longest_vowelless_run(word) >= settings.gibberish_max_consonant_run
        for word in _WORD_RE.findall(stripped)
    )
