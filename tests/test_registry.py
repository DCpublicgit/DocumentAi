"""Tests for app/ingest/registry.py (parsing) and the registry ingest
pipeline (idempotency, data-quality flags, link parsing) — see the phase
spec's Task 4.

The idempotency/flag tests exercise a real Postgres (DATABASE_URL — the same
DB the app uses) since they assert on-disk row state. They use doc_numbers
scoped to a "TEST_" file_name and clean up their own rows afterward, so they
don't collide with real corpus data.
"""

from datetime import date
from pathlib import Path

import pytest

from app.db import close_pool, get_pool
from app.ingest.registry import (
    NoRegistryMetadata,
    RegistryParseError,
    parse_document_metadata,
    parse_effective_date,
    parse_related_links,
)
from app.ingest.registry_pipeline import run_registry_ingest

DOCUMENT_METADATA_SAMPLE = """[DOCUMENT METADATA — not policy content, do not chunk/cite this block]
Баримт бичгийн нэр: Туршилтын бодлого
Бүртгэлийн дугаар: L1-POL-90
Боловсруулсан нэгж: Мэдээлэл технологийн хэлтэс
Хэрэгжүүлэх нэгж: Компанийн нийт ажилтнууд
Мөрдөж эхлэх огноо: 2025.11.05
Иш таталт: ISO 27001:2022 Заалт 5.2
[END METADATA]

ТУРШИЛТЫН БОДЛОГО

НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ
1.1. Энэ бол туршилтын агуулга.
"""

BARE_METADATA_SAMPLE = """БАРИМТ БИЧИГ: Туршилтын журам
ДУГААР: L3-SOP-91
ИШ ТАТАЛТ: ISO 27001:2022 Заалт A.5
Боловсруулсан нэгж: Мэдээлэл технологийн хэлтэс
Мөрдөж эхлэх огноо: 2025.01.01
Бүртгэлийн дугаар: L3-SOP-91

НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ
1.1. Энэ бол туршилтын агуулга.
"""

RELATED_LINKS_TABLE_SAMPLE = """ДОЛОО. ХАМААРАХ БАРИМТ БИЧИГ

| Баримт бичгийн нэр | Дугаар |
|---|---|
| Мэдээллийн аюулгүй байдлын бодлого | L1-POL-04 |
| Эрсдэлийн удирдлагын журам | L2-MAS-14 |

НАЙМ. ӨӨРЧЛӨЛТИЙН ТҮҮХ
| Утга | Огноо |
|---|---|
| Анхны | 2025.11.05 |
"""

RELATED_LINKS_PLAIN_LIST_SAMPLE = """ДОЛОО. ХАМААРАХ БАРИМТ БИЧИГ
Мэдээллийн аюулгүй байдлын бодлого — L1-POL-04
Зохистой хэрэглээний бодлого — L1-POL-27

НАЙМ. ӨӨРЧЛӨЛТИЙН ТҮҮХ
Анхны боловсруулалт — 2025.11.05
"""


def test_parses_document_metadata_style_header(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text(DOCUMENT_METADATA_SAMPLE, encoding="utf-8")

    doc = parse_document_metadata(path)

    assert doc.doc_number == "L1-POL-90"
    assert doc.doc_level == "L1-POL"
    assert doc.title_mn == "Туршилтын бодлого"
    assert doc.owner_unit == "Мэдээлэл технологийн хэлтэс"
    assert doc.effective_date == date(2025, 11, 5)
    assert doc.iso_clause == "ISO 27001:2022 Заалт 5.2"


def test_parses_bare_style_header(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text(BARE_METADATA_SAMPLE, encoding="utf-8")

    doc = parse_document_metadata(path)

    assert doc.doc_number == "L3-SOP-91"
    assert doc.doc_level == "L3-SOP"
    assert doc.title_mn == "Туршилтын журам"
    assert doc.owner_unit == "Мэдээлэл технологийн хэлтэс"
    assert doc.effective_date == date(2025, 1, 1)
    assert doc.iso_clause == "ISO 27001:2022 Заалт A.5"


def test_no_doc_number_raises_no_registry_metadata(tmp_path: Path) -> None:
    # Mirrors the real legacy HR policies (e.g. "Ажлын цагийн хуваарийн
    # журам"): no doc_number at all means "not a registry document", which
    # the pipeline skips rather than treating as a defect.
    path = tmp_path / "no_header.txt"
    path.write_text("АЖЛЫН ЦАГИЙН ЖУРАМ\n\n1. Ерөнхий зүйл\n", encoding="utf-8")

    with pytest.raises(NoRegistryMetadata):
        parse_document_metadata(path)


def test_doc_number_present_but_missing_title_stays_fatal(tmp_path: Path) -> None:
    # A document that DOES declare itself part of the register but is missing
    # a required field is a real defect — it must not be quietly skipped.
    path = tmp_path / "malformed.txt"
    path.write_text(
        "Бүртгэлийн дугаар: L1-POL-93\nБоловсруулсан нэгж: Мэдээлэл технологийн хэлтэс\n",
        encoding="utf-8",
    )

    with pytest.raises(RegistryParseError) as exc_info:
        parse_document_metadata(path)
    assert not isinstance(exc_info.value, NoRegistryMetadata)


def test_parse_effective_date_reads_the_cover_page_date() -> None:
    # Used by the chunks pipeline so citations don't render "огноогүй" for a
    # document whose date is sitting in its own header.
    assert parse_effective_date("Мөрдөж эхлэх огноо: 2025.11.05\n") == date(2025, 11, 5)
    assert parse_effective_date("Мөрдөж эхлэх огноо: 2025-11-05\n") == date(2025, 11, 5)


def test_parse_effective_date_returns_none_when_absent() -> None:
    assert parse_effective_date("НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Текст.\n") is None


def test_governance_note_populates_mandatory_from(tmp_path: Path) -> None:
    # Mirrors the real L1-POL-04 pattern: an incidental dotted date (the
    # order's own approval date) appears BEFORE the dash-format mandatory
    # date — the parser must not grab the first date it sees.
    text = DOCUMENT_METADATA_SAMPLE.replace(
        "Бүртгэлийн дугаар: L1-POL-90\n",
        "Бүртгэлийн дугаар: L1-POL-90\n"
        "[GOVERNANCE NOTE: approved by Order dated 2025.11.05, becomes MANDATORY "
        'starting "2026 оны 01 сарын 03" (2026-01-03).]\n',
    )
    path = tmp_path / "sample.txt"
    path.write_text(text, encoding="utf-8")

    doc = parse_document_metadata(path)

    assert doc.mandatory_from == date(2026, 1, 3)
    assert doc.effective_date == date(2025, 11, 5)


def test_no_governance_note_leaves_mandatory_from_null(tmp_path: Path) -> None:
    path = tmp_path / "sample.txt"
    path.write_text(DOCUMENT_METADATA_SAMPLE, encoding="utf-8")

    doc = parse_document_metadata(path)

    assert doc.mandatory_from is None


def test_parses_related_links_from_markdown_table() -> None:
    assert parse_related_links(RELATED_LINKS_TABLE_SAMPLE) == ["L1-POL-04", "L2-MAS-14"]


def test_parses_related_links_from_plain_list() -> None:
    assert parse_related_links(RELATED_LINKS_PLAIN_LIST_SAMPLE) == ["L1-POL-04", "L1-POL-27"]


def test_no_related_section_returns_empty_list() -> None:
    assert parse_related_links("НЭГ. НИЙТЛЭГ ҮНДЭСЛЭЛ\n1.1. Текст.\n") == []


# --- Integration tests against the real Postgres (DATABASE_URL) ---

TEST_DOC_A = """[DOCUMENT METADATA — not policy content, do not chunk/cite this block]
Баримт бичгийн нэр: Туршилт баримт бичиг А
Бүртгэлийн дугаар: L1-POL-10
Боловсруулсан нэгж: Санхүүгийн хэлтэс
Мөрдөж эхлэх огноо: 2025.01.01
[END METADATA]

ТУРШИЛТЫН БАРИМТ БИЧИГ А
"""

TEST_DOC_B = """[DOCUMENT METADATA — not policy content, do not chunk/cite this block]
Баримт бичгийн нэр: Туршилт баримт бичиг Б
Бүртгэлийн дугаар: L1-POL-10
Боловсруулсан нэгж: Хуулийн хэлтэс
Мөрдөж эхлэх огноо: 2025.02.02
[END METADATA]

ДОЛОО. ХАМААРАХ БАРИМТ БИЧИГ
Туршилтын холбоос — L1-POL-91

НАЙМ. ӨӨРЧЛӨЛТИЙН ТҮҮХ
"""


async def _cleanup(file_names: list[str]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        for name in file_names:
            await conn.execute(
                "DELETE FROM policy_document_links WHERE source_file_name = $1", name
            )
            await conn.execute("DELETE FROM policy_documents WHERE file_name = $1", name)


async def test_duplicate_doc_number_produces_two_flagged_rows_no_pk_collision(
    tmp_path: Path,
) -> None:
    (tmp_path / "TEST_dup_a.txt").write_text(TEST_DOC_A, encoding="utf-8")
    (tmp_path / "TEST_dup_b.txt").write_text(TEST_DOC_B, encoding="utf-8")

    try:
        summary = await run_registry_ingest(tmp_path)
        assert summary.files_processed == 2
        assert summary.flagged_doc_count == 2

        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT file_name, data_quality_flags FROM policy_documents "
            "WHERE doc_number = 'L1-POL-10' AND file_name IN ($1, $2)",
            "TEST_dup_a.txt",
            "TEST_dup_b.txt",
        )
        assert len(rows) == 2
        for row in rows:
            assert "duplicate_doc_number" in row["data_quality_flags"]
    finally:
        await _cleanup(["TEST_dup_a.txt", "TEST_dup_b.txt"])
        await close_pool()


async def test_file_without_doc_number_is_skipped_not_fatal(tmp_path: Path) -> None:
    """Regression: a legacy policy with no doc_number used to raise mid-loop,
    after earlier documents had already been committed — aborting the run and
    leaving the register half-written. It must now be skipped and counted,
    with the other documents still ingested."""
    good = DOCUMENT_METADATA_SAMPLE.replace("L1-POL-90", "L1-POL-94")
    (tmp_path / "TEST_has_number.txt").write_text(good, encoding="utf-8")
    # Sorts AFTER the good file, so under the old code the good file was
    # already committed by the time this one raised.
    (tmp_path / "TEST_zz_legacy.txt").write_text(
        "АЖЛЫН ЦАГИЙН ЖУРАМ\n\n1. Ерөнхий зүйл\n", encoding="utf-8"
    )

    try:
        summary = await run_registry_ingest(tmp_path)

        assert summary.files_found == 2
        assert summary.files_processed == 1
        assert summary.files_skipped == 1

        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT file_name FROM policy_documents WHERE file_name IN ($1, $2)",
            "TEST_has_number.txt",
            "TEST_zz_legacy.txt",
        )
        assert [r["file_name"] for r in rows] == ["TEST_has_number.txt"]
    finally:
        await _cleanup(["TEST_has_number.txt", "TEST_zz_legacy.txt"])
        await close_pool()


async def test_malformed_registry_doc_aborts_before_any_writes(tmp_path: Path) -> None:
    """Regression: validation must happen before the first write, so a
    malformed file leaves NO rows behind — not a partially-loaded register."""
    good = DOCUMENT_METADATA_SAMPLE.replace("L1-POL-90", "L1-POL-95")
    (tmp_path / "TEST_aaa_good.txt").write_text(good, encoding="utf-8")
    # Declares a doc_number (so it's meant to be in the register) but has no
    # title — fatal. Sorts after the good file.
    (tmp_path / "TEST_zzz_bad.txt").write_text(
        "Бүртгэлийн дугаар: L1-POL-96\nБоловсруулсан нэгж: Мэдээлэл технологийн хэлтэс\n",
        encoding="utf-8",
    )

    try:
        with pytest.raises(RegistryParseError):
            await run_registry_ingest(tmp_path)

        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT file_name FROM policy_documents WHERE file_name IN ($1, $2)",
            "TEST_aaa_good.txt",
            "TEST_zzz_bad.txt",
        )
        assert rows == [], "aborted run must not leave the register half-written"
    finally:
        await _cleanup(["TEST_aaa_good.txt", "TEST_zzz_bad.txt"])
        await close_pool()


async def test_reingesting_older_version_does_not_resurrect_it_as_current(
    tmp_path: Path,
) -> None:
    """Regression: is_current used to be flipped by ingest order, so
    re-ingesting v1 after v2 made the superseded v1 current again."""
    sample = DOCUMENT_METADATA_SAMPLE.replace("L1-POL-90", "L1-POL-97")

    def write(version: str) -> Path:
        d = tmp_path / version
        d.mkdir()
        (d / f"TEST_versioned__{version}__2025-01-01.txt").write_text(
            sample, encoding="utf-8"
        )
        return d

    v1_dir, v2_dir = write("v1"), write("v2")

    try:
        await run_registry_ingest(v1_dir)
        await run_registry_ingest(v2_dir)
        # The old version arrives last — it must NOT take over is_current.
        await run_registry_ingest(v1_dir)

        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT policy_version, is_current FROM policy_documents "
            "WHERE file_name = $1 ORDER BY policy_version",
            "TEST_versioned.txt",
        )
        assert {(r["policy_version"], r["is_current"]) for r in rows} == {
            ("v1", False),
            ("v2", True),
        }
    finally:
        await _cleanup(["TEST_versioned.txt"])
        await close_pool()


async def test_registry_ingest_is_idempotent(tmp_path: Path) -> None:
    text = DOCUMENT_METADATA_SAMPLE.replace("L1-POL-90", "L1-POL-92")
    (tmp_path / "TEST_idempotent.txt").write_text(text, encoding="utf-8")

    try:
        await run_registry_ingest(tmp_path)
        await run_registry_ingest(tmp_path)

        pool = await get_pool()
        rows = await pool.fetch(
            "SELECT * FROM policy_documents WHERE file_name = $1", "TEST_idempotent.txt"
        )
        assert len(rows) == 1
    finally:
        await _cleanup(["TEST_idempotent.txt"])
        await close_pool()
