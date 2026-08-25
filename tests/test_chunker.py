from app.config import settings
from app.ingest.chunker import _token_count, chunk_document


def test_no_headings_produces_single_chunk_with_no_section():
    text = "Энэ бол энгийн догол мөр. Гарчиг байхгүй энгийн текст юм."
    chunks = chunk_document(text, max_tokens=500)

    assert len(chunks) == 1
    assert chunks[0].section is None
    assert chunks[0].chunk_index == 0
    assert "Энэ бол" in chunks[0].content


def test_splits_on_numbered_headings_and_keeps_section_label():
    text = (
        "1. Ерөнхий зүйл\n"
        "Энэ хэсэгт ерөнхий зохицуулалтыг тусгав.\n"
        "2. Хариуцлага\n"
        "Энэ хэсэгт хариуцлагыг тусгав."
    )
    chunks = chunk_document(text, max_tokens=500)

    assert len(chunks) == 2
    assert chunks[0].section == "1. Ерөнхий зүйл"
    assert "ерөнхий зохицуулалтыг" in chunks[0].content
    assert chunks[1].section == "2. Хариуцлага"
    assert "хариуцлагыг" in chunks[1].content


def test_chunk_index_is_sequential_across_whole_document():
    text = "1. Нэг\nӨгүүлбэр нэг.\n2. Хоёр\nӨгүүлбэр хоёр.\n3. Гурав\nӨгүүлбэр гурав."
    chunks = chunk_document(text, max_tokens=500)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_long_section_is_split_by_sentence_and_keeps_section_label():
    sentences = " ".join(f"Энэ бол {i}-р өгүүлбэр." for i in range(1, 21))
    text = f"1. Урт хэсэг\n{sentences}"

    # 20, not the original 10: max_tokens is now counted with the embedding
    # model's tokenizer instead of str.split(), and this Cyrillic heading (4
    # tokens) plus one sentence (7) already exceeds 10 — which flushed the
    # heading into a chunk of its own with no body. 20 restores the original
    # intent of this test, ~2 sentences per chunk. The assertions below are
    # unchanged.
    chunks = chunk_document(text, max_tokens=20)

    assert len(chunks) > 1
    assert all(c.section == "1. Урт хэсэг" for c in chunks)
    # Sentence boundaries are respected: no chunk cuts a sentence in half.
    for c in chunks:
        assert c.content.strip().endswith(".")
    # Content is preserved in order, just split.
    rejoined = " ".join(c.content for c in chunks)
    for i in range(1, 21):
        assert f"{i}-р өгүүлбэр" in rejoined


def test_recognizes_cyrillic_zuil_bulэg_headings():
    text = "НЭГ БҮЛЭГ\nЕрөнхий зохицуулалт.\nХОЁР БҮЛЭГ\nХариуцлагын зохицуулалт."
    chunks = chunk_document(text, max_tokens=500)

    assert len(chunks) == 2
    assert chunks[0].section == "НЭГ БҮЛЭГ"
    assert chunks[1].section == "ХОЁР БҮЛЭГ"


def test_recognizes_bare_cardinal_word_headings():
    text = (
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "Энэ хэсэгт ерөнхий зохицуулалтыг тусгав.\n"
        "ХОЁР. ҮҮРЭГ, ХАРИУЦЛАГА\n"
        "Энэ хэсэгт хариуцлагыг тусгав."
    )
    chunks = chunk_document(text, max_tokens=500)

    assert len(chunks) == 2
    assert chunks[0].section == "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ"
    assert chunks[1].section == "ХОЁР. ҮҮРЭГ, ХАРИУЦЛАГА"


def test_recognizes_equals_wrapped_headings_and_strips_decoration():
    text = (
        "=== БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ ===\n"
        "Энэ хэсэгт ерөнхий зохицуулалтыг тусгав.\n"
        "=== ХОЁР. ҮҮРЭГ ХАРИУЦЛАГА ===\n"
        "Энэ хэсэгт хариуцлагыг тусгав."
    )
    chunks = chunk_document(text, max_tokens=500)

    assert len(chunks) == 2
    assert chunks[0].section == "БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ"
    assert chunks[1].section == "ХОЁР. ҮҮРЭГ ХАРИУЦЛАГА"


def _table_section(n_rows: int) -> str:
    rows = "\n".join(
        f"| {i} | Мөр {i}-ийн тайлбар энд байна. | Хариуцагч {i} |"
        for i in range(1, n_rows + 1)
    )
    return f"НЭГ. ХҮСНЭГТ\n| № | Тайлбар | Хариуцагч |\n|---|---|---|\n{rows}"


def test_long_table_never_splits_a_row_in_half():
    # Regression: sentence-splitting treated the newline after a row's
    # trailing "." as a sentence boundary, so a row's last cell (the
    # responsible party) landed in a different chunk from its duty.
    chunks = chunk_document(_table_section(15), max_tokens=40)

    assert len(chunks) > 1
    for c in chunks:
        for line in c.content.splitlines():
            if line.startswith("|"):
                assert line.rstrip().endswith("|"), f"severed table row: {line!r}"

    # Every row survives intact and in order.
    rejoined = "\n".join(c.content for c in chunks)
    for i in range(1, 16):
        assert f"| {i} | Мөр {i}-ийн тайлбар энд байна. | Хариуцагч {i} |" in rejoined


def test_table_header_is_repeated_on_every_continuation_chunk():
    chunks = chunk_document(_table_section(15), max_tokens=40)

    assert len(chunks) > 1
    for c in chunks:
        assert "| № | Тайлбар | Хариуцагч |" in c.content
        assert "|---|---|---|" in c.content


def test_prose_chunks_preserve_original_line_structure():
    # Chunk text is a verbatim slice, so paragraph breaks survive rather than
    # being flattened into spaces.
    body = "\n\n".join(f"1.{i}. Энэ бол {i}-р заалт." for i in range(1, 13))
    chunks = chunk_document(f"НЭГ. ЗААЛТУУД\n{body}", max_tokens=12)

    assert len(chunks) > 1
    assert any("\n\n" in c.content for c in chunks)
    rejoined = " ".join(c.content for c in chunks)
    for i in range(1, 13):
        assert f"1.{i}. Энэ бол {i}-р заалт." in rejoined


def test_token_count_uses_the_model_tokenizer_not_whitespace():
    """Regression guard for the sizing bug.

    _token_count was len(text.split()). BGE-M3 is XLM-R SentencePiece, which
    splits Mongolian Cyrillic far finer than whitespace does, so a nominal
    500-token budget was really letting through chunks of ~1260 model tokens
    (23% of the live corpus was over budget). If this ever equals the
    whitespace count again, the budget has stopped meaning what it says.
    """
    text = "Энэ бол 1-р өгүүлбэр."

    assert len(text.split()) == 4
    assert _token_count(text) == 7
    assert _token_count(text) != len(text.split())


def test_no_emitted_chunk_exceeds_the_token_budget():
    """The budget holds in REAL tokens, at the configured CHUNK_SIZE_TOKENS.

    Documented exception, deliberately not exercised here: a single segment
    that is itself over budget (one very long sentence, or a wide table row)
    is emitted whole rather than severed, so it may overshoot. Every sentence
    below is far under budget, so nothing here is entitled to overshoot.
    """
    sentences = " ".join(
        f"Байгууллагын ажилтан {i} дугаар журмыг чанд мөрдөх үүрэгтэй."
        for i in range(1, 81)
    )
    text = f"1. Ерөнхий зүйл\n{sentences}"

    chunks = chunk_document(text, max_tokens=settings.chunk_size_tokens)

    assert len(chunks) > 1, "corpus-sized input should split into several chunks"
    for c in chunks:
        assert _token_count(c.content) <= settings.chunk_size_tokens


def test_table_of_contents_dot_leader_entries_are_not_headings():
    # A ToC with dot-leaders + trailing page numbers coincidentally matches
    # the numbered/cardinal-word heading shape — it must not split the doc
    # or leak into a section label, and the real body headings (no dot
    # leaders) must still be detected.
    text = (
        "=== АГУУЛГА ===\n"
        "1. ЕРӨНХИЙ ЗҮЙЛ ......................................... 1\n"
        "2. ХАРИУЦЛАГА ........................................... 3\n"
        "\n"
        "=== БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ ===\n"
        "Энэ хэсэгт ерөнхий зохицуулалтыг тусгав.\n"
        "=== БҮЛЭГ 2. ХАРИУЦЛАГА ===\n"
        "Энэ хэсэгт хариуцлагыг тусгав."
    )
    chunks = chunk_document(text, max_tokens=500)

    # The ToC dot-leader lines land in the None-section preamble along with
    # "=== АГУУЛГА ===" — they must NOT each become their own heading/chunk.
    assert len(chunks) == 3
    assert chunks[0].section is None
    assert chunks[1].section == "БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ"
    assert chunks[2].section == "БҮЛЭГ 2. ХАРИУЦЛАГА"
    assert "...." not in chunks[1].content
    assert "...." not in chunks[2].content
