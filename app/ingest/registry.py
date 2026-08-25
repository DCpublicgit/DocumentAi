"""Metadata + link-graph parser for policy_documents / policy_document_links.

Reads the "=== METADATA ===", "[DOCUMENT METADATA ...]", and bare (no wrapper
marker — just "Label: value" lines at the top of the file) header styles
found across the transcribed .txt batches in policies/, plus any "ХАМААРАХ
БАРИМТ БИЧИГ" section anywhere in the file. Pure parsing — no I/O beyond
reading the file, no DB access (see app/ingest/registry_loader.py for that).
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from app.ingest.dq import IngestError

logger = logging.getLogger(__name__)


class RegistryParseError(IngestError):
    """Raised when a .txt file's registry metadata is malformed — it declares
    a doc_number but is missing a field the registry requires. Fatal: this is
    a defect in a document that IS meant to be in the register."""


class NoRegistryMetadata(RegistryParseError):
    """Raised when a .txt file declares no doc_number at all, i.e. it is not
    a registry document. Distinct from RegistryParseError because the corpus
    legitimately contains policy files that predate the ISO document set
    (the legacy HR policies) — those have chunks but no policy_documents
    row, and must not abort a registry run. Callers skip + count these; see
    app/ingest/registry_pipeline.py."""


# Data-quality issues already confirmed by manual review of the source corpus
# — seeded explicitly per doc_number rather than inferred at parse time, so
# ingest surfaces them instead of silently trusting the transcribed text.
KNOWN_DQ_FLAGS: dict[str, list[str]] = {
    "L1-POL-10": ["duplicate_doc_number"],
    "L1-POL-15": ["title_mismatch"],
    "L1-POL-14": ["toc_broken_ref"],
    "L2-MAS-58": ["blank_template_appendix"],
    "L2-MAS-59": ["effective_date_outlier"],
    "L3-SOP-42": ["effective_date_outlier"],
    "L3-SOP-52": ["numbering_drift"],
}

_DOC_NUMBER_RE = re.compile(r"(L\d+-[A-Z]+-\d+)")
_DATE_RE = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})")
# GOVERNANCE NOTE blocks use dots for incidental dates (e.g. an order's own
# approval date) and reserve dash-separated ISO format specifically for the
# mandatory/compliance date being called out — so match that format only,
# not the general _DATE_RE, or the first incidental dotted date wins instead.
_ISO_DASH_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

_DOC_NUMBER_LABEL_RE = re.compile(r"^Бүртгэлийн дугаар:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_OWNER_UNIT_LABEL_RE = re.compile(r"^Боловсруулсан нэгж:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_ISO_CLAUSE_LABEL_RE = re.compile(r"^Иш таталт:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_EFFECTIVE_DATE_LABEL_RE = re.compile(
    r"^Мөрдөж эхлэх огноо:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
# Two distinct labels carry the title depending on header style — "Баримт
# бичгийн нэр:" (DOCUMENT METADATA style) or bare "БАРИМТ БИЧИГ:" (the other
# two styles). Never both in the same file; tried in order.
_TITLE_LABEL_RES = [
    re.compile(r"^Баримт бичгийн нэр:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^БАРИМТ БИЧИГ:\s*(.+)$", re.MULTILINE | re.IGNORECASE),
]

_GOVERNANCE_NOTE_RE = re.compile(r"\[GOVERNANCE NOTE.*?\]", re.DOTALL | re.IGNORECASE)

_RELATED_HEADING_RE = re.compile(r"ХАМААРАХ БАРИМТ БИЧИГ", re.IGNORECASE)
# Top-level section headings in this document family are numbered either with
# Cyrillic word-numerals ("ДОЛОО.") or, in at least one file, Arabic numerals
# ("7.") — either marks the end of a preceding section like ХАМААРАХ БАРИМТ
# БИЧИГ.
_MAJOR_HEADING_RE = re.compile(
    r"^(?:===\s*)?(?:\d+\.|(?:НЭГ|ХОЁР|ГУРАВ|ДӨРӨВ|ТАВ|ЗУРГАА|ДОЛОО|НАЙМ|ЕС|АРАВ)\.)\s",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ParsedDocument:
    doc_number: str
    doc_level: str
    title_mn: str
    owner_unit: str
    effective_date: date | None
    mandatory_from: date | None
    iso_clause: str | None
    data_quality_flags: list[str]
    related_links: list[str] = field(default_factory=list)


def _find_label(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _parse_date(raw: str | None) -> date | None:
    if raw is None:
        return None
    match = _DATE_RE.search(raw)
    if match is None:
        return None
    year, month, day = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_effective_date(text: str) -> date | None:
    """The document's own "Мөрдөж эхлэх огноо" cover-page date, or None.

    Public because the chunks pipeline needs it too: policy_chunks.effective_date
    otherwise comes only from the "__v{version}__{date}" filename convention,
    which most of the corpus does not follow — leaving the citation's date
    field rendering "огноогүй" for documents whose date is sitting right there
    in the body. Parsing here (not re-deriving it in the pipeline) keeps one
    definition of where an effective date comes from.
    """
    return _parse_date(_find_label(_EFFECTIVE_DATE_LABEL_RE, text))


def _parse_mandatory_from(text: str) -> date | None:
    note = _GOVERNANCE_NOTE_RE.search(text)
    if note is None:
        return None
    match = _ISO_DASH_DATE_RE.search(note.group(0))
    if match is None:
        return None
    return _parse_date(match.group(1))


def parse_related_links(text: str) -> list[str]:
    """Parse a "ХАМААРАХ БАРИМТ БИЧИГ" section (markdown table or plain
    "Title — DocNumber" list — both forms exist in the corpus) into an
    ordered, de-duplicated list of target doc_numbers.
    """
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if _RELATED_HEADING_RE.search(line):
            start = i + 1
            break
    if start is None:
        return []

    targets: list[str] = []
    seen: set[str] = set()
    for line in lines[start:]:
        if _MAJOR_HEADING_RE.match(line.strip()):
            break
        for m in _DOC_NUMBER_RE.finditer(line):
            token = m.group(1)
            if token not in seen:
                seen.add(token)
                targets.append(token)
    return targets


def parse_document_metadata(txt_path: Path) -> ParsedDocument:
    text = txt_path.read_text(encoding="utf-8")

    doc_number_raw = _find_label(_DOC_NUMBER_LABEL_RE, text)
    doc_number_match = _DOC_NUMBER_RE.search(doc_number_raw) if doc_number_raw else None
    if doc_number_match is None:
        raise NoRegistryMetadata(
            f"{txt_path.name}: no registry metadata header "
            "(missing 'Бүртгэлийн дугаар') — not a registry document"
        )
    doc_number = doc_number_match.group(1)
    doc_level = doc_number.rsplit("-", 1)[0]

    title_mn = None
    for pattern in _TITLE_LABEL_RES:
        title_mn = _find_label(pattern, text)
        if title_mn is not None:
            break
    if title_mn is None:
        raise RegistryParseError(
            f"{txt_path.name}: no parseable title (doc_number={doc_number})"
        )

    owner_unit = _find_label(_OWNER_UNIT_LABEL_RE, text)
    if owner_unit is None:
        raise RegistryParseError(
            f"{txt_path.name}: no parseable owner_unit (doc_number={doc_number})"
        )

    iso_clause = _find_label(_ISO_CLAUSE_LABEL_RE, text)

    effective_date_raw = _find_label(_EFFECTIVE_DATE_LABEL_RE, text)
    effective_date = parse_effective_date(text)
    if effective_date_raw is not None and effective_date is None:
        logger.warning(
            "%s: effective_date present but unparseable: %r", txt_path.name, effective_date_raw
        )

    mandatory_from = _parse_mandatory_from(text)

    flags = list(KNOWN_DQ_FLAGS.get(doc_number, []))
    for flag_name in flags:
        logger.warning(
            "%s: data quality flag '%s' (doc_number=%s)", txt_path.name, flag_name, doc_number
        )

    return ParsedDocument(
        doc_number=doc_number,
        doc_level=doc_level,
        title_mn=title_mn,
        owner_unit=owner_unit,
        effective_date=effective_date,
        mandatory_from=mandatory_from,
        iso_clause=iso_clause,
        data_quality_flags=flags,
        related_links=parse_related_links(text),
    )
