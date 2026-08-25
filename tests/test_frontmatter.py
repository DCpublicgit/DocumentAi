from app.ingest.frontmatter import strip_front_matter


def test_strips_bracket_metadata_block_and_keeps_body():
    text = (
        "[DOCUMENT METADATA — not policy content, do not chunk/cite this block]\n"
        "Баримт бичгийн нэр: Туршилтын бодлого\n"
        "Бүртгэлийн дугаар: L1-POL-90\n"
        "[END METADATA]\n"
        "\n"
        "ТУРШИЛТЫН БОДЛОГО\n"
        "\n"
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "1.1. Энэ бол туршилтын агуулга."
    )
    result = strip_front_matter(text)

    assert "DOCUMENT METADATA" not in result
    assert "Бүртгэлийн дугаар" not in result
    assert "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ" in result
    assert "1.1. Энэ бол туршилтын агуулга." in result


def test_strips_inline_source_note_without_touching_surrounding_clause():
    text = (
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "1.1. Эхний өгүүлбэр.\n"
        "[SOURCE NOTE: sub-item numbering preserved exactly as in source PDF.]\n"
        "1.1.1. Дараагийн өгүүлбэр."
    )
    result = strip_front_matter(text)

    assert "SOURCE NOTE" not in result
    assert "1.1. Эхний өгүүлбэр." in result
    assert "1.1.1. Дараагийн өгүүлбэр." in result


def test_strips_data_quality_flag_and_governance_note_and_transcription_note():
    text = (
        "[DATA QUALITY FLAG: this doc_number collides with another document.]\n"
        "[GOVERNANCE NOTE: approved by Order No. 123, dated 2025.11.05.]\n"
        "[Тэмдэглэл: Энэхүү текст нь сканнердсан PDF-ийг унших замаар гаргасан.]\n"
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "1.1. Бодит агуулга."
    )
    result = strip_front_matter(text)

    assert "DATA QUALITY FLAG" not in result
    assert "GOVERNANCE NOTE" not in result
    assert "Тэмдэглэл" not in result
    assert result == "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Бодит агуулга."


def test_strips_equals_wrapped_metadata_signoff_and_toc_blocks():
    text = (
        "БАРИМТ БИЧИГ: Дотоод сүлжээ ашиглах ерөнхий журам\n"
        "ДУГААР: L3-SOP-42\n"
        "\n"
        "=== METADATA ===\n"
        "Боловсруулсан нэгж: Мэдээлэл технологийн хэлтэс\n"
        "\n"
        "=== БАТАЛГААЖУУЛАЛТ ===\n"
        "Баталсан: Гүйцэтгэх захирал Б.Гантиг\n"
        "\n"
        "=== АГУУЛГА ===\n"
        "1. ЕРӨНХИЙ ЗҮЙЛ ......................................... 1\n"
        "\n"
        "=== БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ ===\n"
        "Бодит бодлогын агуулга."
    )
    result = strip_front_matter(text)

    assert "METADATA" not in result
    assert "БАТАЛГААЖУУЛАЛТ" not in result
    assert "Баталсан" not in result
    assert "АГУУЛГА" not in result
    assert "...." not in result
    assert "=== БҮЛЭГ 1. ЕРӨНХИЙ ЗҮЙЛ ===" in result
    assert "Бодит бодлогын агуулга." in result


def test_strips_bare_label_header_with_no_wrapper():
    text = (
        "БАРИМТ БИЧИГ: Хортой программ хангамжийг хянах бодлого\n"
        "ДУГААР: L1-POL-18\n"
        "ИШ ТАТАЛТ: ISO 9001:2015 Заалт 7.5\n"
        "Боловсруулсан нэгж: Мэдээлэл технологийн хэлтэс\n"
        "Хэрэгжүүлэх нэгж: Компанийн нийт ажилтнууд\n"
        "Мэдээллийн ангилал: Дотоод хэрэгцээний\n"
        "Мөрдөж эхлэх огноо: 2025.11.05\n"
        "Хуудасны тоо: 6\n"
        "Бүртгэлийн дугаар: L1-POL-18\n"
        "\n"
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "1.1. Бодит агуулга."
    )
    result = strip_front_matter(text)

    assert result == "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Бодит агуулга."


def test_strips_transcription_provenance_footer_that_collides_with_citation_header():
    """"Эх сурвалж:" is our citation header (app/contract.py). Both the UI and
    the eval split an answer at its FIRST occurrence, so a chunk carrying the
    transcriber's provenance footer would truncate the answer and mis-parse
    the citation list."""
    text = (
        "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n"
        "1.1. Бодит агуулга.\n"
        "[Эх сурвалж: L1-POL-18_Хортой_программ.pdf, 7 хуудас, "
        "гарын үсэг зурсан удирдлагын баталгаажуулалттай]"
    )
    result = strip_front_matter(text)

    assert "Эх сурвалж" not in result
    assert result == "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Бодит агуулга."


def test_policy_text_using_the_phrase_unbracketed_is_kept():
    # Only the bracketed footer form is an annotation — a real sentence that
    # uses the same words must survive.
    text = "НЭГ. ЕРӨНХИЙ\n1.1. Эх сурвалжийг заавал заасан байна."
    assert strip_front_matter(text) == text


def test_strips_bare_note_annotation_embedded_mid_table_row():
    # Real L1-POL-04 shape: a [NOTE: ...] wraps across lines inside a table
    # row, breaking the row in two. Removing it makes the row whole again.
    text = (
        "| № | Нэр | Дугаар |\n"
        "|---|---|---|\n"
        "| 20 | Сургалтын бодлого | L1-POL-10 [NOTE: this is the SAME number\n"
        "as item 6 above — a collision preserved as-is.] |"
    )
    result = strip_front_matter(text)

    assert "NOTE" not in result
    for line in result.splitlines():
        assert line.strip().startswith("|") and line.strip().endswith("|")


def test_document_with_no_front_matter_is_left_alone():
    text = "НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Гарчиггүй энгийн эхлэлтэй баримт."
    assert strip_front_matter(text) == text
