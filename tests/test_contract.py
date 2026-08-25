"""is_refusal() is the compliance boundary: whichever way it answers decides
whether a citation list gets appended. Appending citations to a refusal is
the damaging error — a citation asserts the policy documents support the
statement (CONTRIBUTING.md rule 2).
"""

import pytest

from app.contract import REFUSAL_STRING, is_refusal


def test_exact_refusal_string_is_a_refusal():
    assert is_refusal(REFUSAL_STRING)


@pytest.mark.parametrize(
    "variant",
    [
        REFUSAL_STRING + ".",
        REFUSAL_STRING + "  ",
        "  " + REFUSAL_STRING,
        "\n" + REFUSAL_STRING + "\n",
        f'"{REFUSAL_STRING}"',
        f"«{REFUSAL_STRING}»",
        REFUSAL_STRING.replace(" ", "  "),
        REFUSAL_STRING.replace("бодлогын баримт", "бодлогын\nбаримт"),
        REFUSAL_STRING.upper(),
    ],
)
def test_cosmetic_drift_still_counts_as_a_refusal(variant):
    """Models echo the required sentence with trailing punctuation, quotes, or
    rewrapped whitespace. Treating those as real answers would append a
    citation list to a refusal."""
    assert is_refusal(variant), f"should be treated as a refusal: {variant!r}"


@pytest.mark.parametrize(
    "answer",
    [
        "Ажлын цаг 09:00-18:00 байна.",
        "Уучлаарай, гэхдээ хариулт нь дараах байдалтай байна: ажлын цаг 09:00.",
        f"{REFUSAL_STRING} Гэхдээ ажлын цаг 09:00-18:00 гэж заасан байна.",
    ],
)
def test_real_answers_are_not_refusals(answer):
    """A real answer must keep its citations — including one that merely
    mentions the refusal wording before going on to answer, which is why this
    is not a prefix or substring test."""
    assert not is_refusal(answer)


@pytest.mark.parametrize("empty", ["", "   ", "\n\n", "\t "])
def test_empty_output_is_not_a_refusal(empty):
    """A refusal asserts "this is not in company policy". An empty completion
    is evidence of a provider problem, not of policy content — reporting it as
    a refusal would tell an employee their question isn't covered when it may
    well be. Callers raise EmptyCompletionError instead."""
    assert not is_refusal(empty)
