from datetime import date

from app.citations import (
    extract_used_context,
    format_citation,
    format_citation_list,
    format_context_block,
    is_used_marker_line,
)
from app.config import settings
from app.retrieve.models import RetrievedChunk


def _chunk(**overrides) -> RetrievedChunk:
    defaults = dict(
        file_name="Чөлөө олгох журам.pdf",
        section="1.2",
        policy_version="v3",
        effective_date=date(2025, 1, 1),
        chunk_index=0,
        content="Жилийн ээлжийн амралт 15 өдөр байна.",
    )
    defaults.update(overrides)
    return RetrievedChunk(**defaults)


def test_format_citation_matches_exact_contract_format():
    citation = format_citation(_chunk())
    assert citation == "[Чөлөө олгох журам.pdf · 1.2 · v3 (2025-01-01)]"


def test_format_citation_handles_missing_section_and_date():
    citation = format_citation(_chunk(section=None, effective_date=None))
    assert citation == "[Чөлөө олгох журам.pdf · — · v3 (огноогүй)]"


def test_format_citation_list_has_header_and_one_line_per_source():
    chunks = [
        _chunk(section="1.2", chunk_index=0),
        _chunk(section="2", policy_version="v1", chunk_index=1),
    ]
    block = format_citation_list(chunks)

    lines = block.splitlines()
    assert lines[0] == "Эх сурвалж:"
    assert len(lines) == 3
    assert "1.2" in lines[1]
    assert "2" in lines[2] and "v1" in lines[2]


def test_format_citation_list_deduplicates_same_source():
    chunks = [_chunk(chunk_index=0), _chunk(chunk_index=0)]
    block = format_citation_list(chunks)

    assert len(block.splitlines()) == 2  # header + one citation, not two


def test_format_context_block_tags_file_section_version():
    block = format_context_block(_chunk())
    assert block.startswith("[Чөлөө олгох журам.pdf · 1.2 · v3]\n")
    assert "Жилийн ээлжийн амралт" in block


def test_format_citation_cites_inline_clause_number_over_section():
    chunk = _chunk(section="ДӨРӨВ. ЭД ХӨРӨНГӨ", content="4.1.2. Дараах зүйлийг хориглоно.")
    citation = format_citation(chunk)
    assert "Заалт 4.1.2: Дараах зүйлийг хориглоно." in citation
    assert "ДӨРӨВ. ЭД ХӨРӨНГӨ" not in citation


def test_format_citation_cites_only_first_clause_when_chunk_has_several():
    # Description may still mention "4.8.2" as running text (it's a verbatim
    # slice of the chunk) — what's guaranteed is the citation is filed under
    # the first clause NUMBER, not a second "Заалт 4.8.2:" entry.
    chunk = _chunk(content="4.8.1. Тоног төхөөрөмжийг ашиглуулах. 4.8.2. Хориглоно.")
    citation = format_citation(chunk)
    assert "Заалт 4.8.1:" in citation
    assert "Заалт 4.8.2" not in citation


def test_format_citation_honors_a_verified_preferred_clause():
    """The "4.1 shown instead of 4.2" case: a chunk spanning several clauses
    is cited under whichever one the model actually drew from, when named."""
    chunk = _chunk(content="4.1. Сүлжээний шаардлага. 4.2. VPN ашиглалтын шаардлага.")

    citation = format_citation(chunk, preferred_clause="4.2")

    assert "Заалт 4.2: VPN ашиглалтын шаардлага." in citation
    assert "Заалт 4.1" not in citation


def test_format_citation_falls_back_to_first_clause_when_preferred_is_not_in_the_chunk():
    """Never invent a clause number that isn't in the text (DATA_CONTRACT.md)
    — a preferred clause the model named but that this chunk doesn't
    actually contain must not be trusted blindly."""
    chunk = _chunk(content="4.1. Сүлжээний шаардлага. 4.2. VPN ашиглалтын шаардлага.")

    citation = format_citation(chunk, preferred_clause="4.9")

    assert "Заалт 4.1: Сүлжээний шаардлага." in citation


def test_format_citation_list_applies_preferred_clauses_per_chunk():
    a = _chunk(
        file_name="a.txt", chunk_index=0,
        content="4.1. Сүлжээ. 4.2. VPN ашиглалтын шаардлага.",
    )
    b = _chunk(file_name="b.txt", chunk_index=1, content="9.1. Бусад.")
    preferred = {("a.txt", "v3", 0): "4.2"}

    block = format_citation_list([a, b], preferred)

    assert "Заалт 4.2: VPN ашиглалтын шаардлага." in block
    assert "Заалт 4.1" not in block
    assert "Заалт 9.1" in block


def test_format_citation_falls_back_to_section_when_no_clause_number():
    chunk = _chunk(section="1.2", content="Энгийн өгүүлбэр, заалтын дугаар агуулаагүй.")
    citation = format_citation(chunk)
    assert "[Чөлөө олгох журам.pdf · 1.2 · v3 (2025-01-01)]" == citation


def test_format_citation_clause_description_is_truncated_at_word_boundary():
    long_tail = " ".join(f"үг{i}" for i in range(1, 40))
    chunk = _chunk(content=f"1.1. {long_tail}")
    citation = format_citation(chunk)

    description = citation.split("Заалт 1.1: ", 1)[1].split(" ·", 1)[0]
    assert description.endswith("…")
    assert len(description) <= settings.clause_description_max_chars + 1
    assert " …" not in description  # cut at a word boundary, not mid-word then trimmed


def test_extract_used_context_splits_off_one_marker_line_per_chunk():
    text = "Товч хариулт:\nЖишээ хариулт.\n\nАШИГЛАСАН 1:\nАШИГЛАСАН 3:"

    answer, used = extract_used_context(text)

    assert answer == "Товч хариулт:\nЖишээ хариулт."
    assert used == [(1, None), (3, None)]


def test_extract_used_context_parses_a_specific_clause_per_line():
    text = "Хариулт.\n\nАШИГЛАСАН 1: 4.2\nАШИГЛАСАН 3:"

    answer, used = extract_used_context(text)

    assert answer == "Хариулт."
    assert used == [(1, "4.2"), (3, None)]


def test_extract_used_context_handles_whitespace_and_bracketed_index():
    text = "Хариулт.\n\nАШИГЛАСАН  [2] :  1.2 \nАШИГЛАСАН 4:"

    answer, used = extract_used_context(text)

    assert answer == "Хариулт."
    assert used == [(2, "1.2"), (4, None)]


def test_extract_used_context_survives_a_multi_clause_list_a_small_model_might_emit():
    """Regression: a real gemini-flash-lite response listed several clauses
    after one colon in a single packed line ("1:4.2.1, 4.2.2, 4.3.1") — the
    old single-line format could not tell that apart from separate entry
    boundaries and silently mis-parsed. One line per chunk sidesteps this: a
    line this malformed just fails its OWN parse and is skipped, without
    corrupting any other line's entry."""
    text = "Хариулт.\n\nАШИГЛАСАН 1: 4.2.1, 4.2.2, 4.3.1\nАШИГЛАСАН 2: 4.1"

    answer, used = extract_used_context(text)

    assert answer == "Хариулт."
    # Line 1 doesn't fully match (trailing content after the first clause
    # number isn't whitespace) so it contributes no entry at all — but that
    # failure is contained to its own line and never corrupts line 2's.
    assert (2, "4.1") in used


def test_extract_used_context_returns_none_when_marker_is_missing():
    text = "Хариулт текст, дугааргүй дуусна."

    answer, used = extract_used_context(text)

    assert answer == text
    assert used is None


def test_extract_used_context_returns_none_when_every_marker_line_is_malformed():
    """If every marker-shaped line fails to parse, entries ends up empty —
    falls back to None (cite everything), same as no marker at all."""
    text = "Хариулт.\n\nАШИГЛАСАН 1: 4.2.1, 4.2.2, 4.3.1"

    answer, used = extract_used_context(text)

    assert answer == "Хариулт."
    assert used is None


def test_extract_used_context_skips_a_line_with_an_unparseable_clause():
    """A marker-shaped line that doesn't fully parse is dropped, not treated
    as invalidating the whole block — other, well-formed lines still count."""
    text = "Хариулт.\n\nАШИГЛАСАН 1: юу ч биш\nАШИГЛАСАН 2: 4.1"

    answer, used = extract_used_context(text)

    assert answer == "Хариулт."
    assert used == [(2, "4.1")]


def test_is_used_marker_line_matches_malformed_clauses_too():
    """Used by the streaming path to decide what to withhold from the live
    stream — must catch a marker-shaped line even with a malformed clause,
    or it would leak the raw "АШИГЛАСАН N: ..." line to the employee
    verbatim."""
    assert is_used_marker_line("АШИГЛАСАН 1: 4.2")
    assert is_used_marker_line("АШИГЛАСАН 1:")
    assert is_used_marker_line("АШИГЛАСАН [1]: юу ч биш")
    assert not is_used_marker_line("Энгийн өгүүлбэр.")
    assert not is_used_marker_line("АШИГЛАСАН 1")  # missing the colon


def test_format_citation_strips_delimiter_characters_from_clause_description():
    import re

    chunk = _chunk(content="1.1. Энэ [заалт] нь (хаалт) ба · тэмдэгт агуулна.")
    citation = format_citation(chunk)

    # None of the stripped characters survive in the extracted description,
    # so the 4-group "[a · b · c (d)]" citation-line shape stays intact for
    # downstream parsers (app/eval/runner.py, ui/src/lib/parseCitations.js).
    match = re.match(r"^\[(.+?) · (.+?) · (.+?) \((.+?)\)\]$", citation)
    assert match is not None, citation
    assert "[" not in match.group(2)
    assert "]" not in match.group(2)
    assert "(" not in match.group(2)
    assert ")" not in match.group(2)
