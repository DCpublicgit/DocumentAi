"""Section-aware chunking.

Splits document text into ~max_tokens-sized chunks, breaking preferentially at
detected section headings (numbered sections, Cyrillic chapter/article
markers) and, within an over-long section, at sentence boundaries. Token
count uses the EMBEDDING_MODEL's own tokenizer, so max_tokens means the same
thing here as it does to the model that embeds the result. Each chunk carries
the section label it fell under, or None if it precedes the first detected
heading.

Markdown table rows are atomic: a chunk boundary never falls inside one. The
corpus is full of responsibility and control matrices (L1-POL-14, L1-POL-22's
Хяналтын матриц, L2-MAS-58's risk matrix) whose rows read
"| duty | ... | responsible party |". Splitting a row mid-way strands the
responsible-party cell in a different chunk from the duty it belongs to, so
retrieval can return an obligation without its owner. When a table spans
several chunks, the header row is repeated at the top of each continuation
piece — without it a continuation is just unlabelled cells, uninterpretable
and unusable as a cited source.

Chunk text is otherwise a verbatim contiguous slice of the section (the
repeated table header is the sole exception): pieces are cut at offsets into
the original string, so original whitespace and line structure survive
intact.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from transformers import AutoTokenizer

from app.config import settings

_CARDINAL_WORDS = "НЭГ|ХОЁР|ГУРАВ|ДӨРӨВ|ТАВ|ЗУРГАА|ДОЛОО|НАЙМ|ЕС|АРАВ"

_HEADING_PATTERNS = [
    # Single-level numbering only ("1. Гарчиг") — NOT "1.1." sub-clauses, which
    # are legal-text detail that belongs inside their parent section's chunk.
    re.compile(r"^\d+\.\s+\S.*$"),
    re.compile(r"^[IVXLCDM]+\.\s+\S.*$"),  # Roman numerals
    re.compile(r"^[А-ЯЁӨҮIVXLCDM0-9]+\s+(БҮЛЭГ|ЗҮЙЛ)\b.*$"),  # "НЭГ БҮЛЭГ", "II ЗҮЙЛ"
    re.compile(r"^\d+\s*(дүгээр|дугаар)\s+(зүйл|бүлэг)\b.*$", re.IGNORECASE),
    # Mongolian cardinal-word chapter markers ("НЭГ. Гарчиг") — the numbering
    # convention used across the L1-POL-14 / L3-SOP document family.
    re.compile(rf"^(?:{_CARDINAL_WORDS})\.\s+\S.*$"),
    # Same markers wrapped in "=== ... ===" decoration, optionally with a
    # "БҮЛЭГ" keyword before the number ("=== БҮЛЭГ 1. Гарчиг ===",
    # "=== ХОЁР. Гарчиг ===") — another convention in the same family.
    re.compile(rf"^===\s*(?:БҮЛЭГ\s+)?(?:\d+|{_CARDINAL_WORDS})\.\s+\S.*?\s*===\s*$"),
]

# A numbered/word-numbered line that ends in a dot-leader + page number is a
# table-of-contents entry, not a real heading — several source docs have a
# ToC whose numbering coincidentally matches _HEADING_PATTERNS above.
_TOC_ENTRY = re.compile(r"\.{4,}\s*\d+\s*$")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

# A markdown table row ("| a | b |") and its header underline ("|---|---|").
_TABLE_ROW = re.compile(r"^\|.*\|$")
_TABLE_SEPARATOR = re.compile(r"^\|[\s:|-]+\|$")


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    section: str | None
    content: str


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _TOC_ENTRY.search(stripped):
        return False
    return any(p.match(stripped) for p in _HEADING_PATTERNS)


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """Return [(section_label, section_text), ...] in document order."""
    lines = text.split("\n")
    sections: list[tuple[str | None, list[str]]] = []
    current_label: str | None = None
    current_lines: list[str] = []

    for line in lines:
        if _is_heading(line):
            if current_lines:
                sections.append((current_label, current_lines))
            current_label = line.strip().strip("=").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_label, current_lines))

    return [
        (label, joined)
        for label, ls in sections
        if (joined := "\n".join(ls).strip())
    ]


@lru_cache(maxsize=1)
def _tokenizer():
    """The EMBEDDING_MODEL's own tokenizer, loaded once per process.

    Chunk size has to be measured in the units the embedding model actually
    consumes. BGE-M3 is XLM-R SentencePiece, which splits Mongolian Cyrillic
    ~2.1x finer than whitespace does, so counting words silently produced
    chunks of up to 1260 real tokens against a nominal 500 budget — 23% of the
    corpus over budget. Oversized chunks span several topics, which smears the
    embedding and depresses cosine similarity against a short question.

    Tokenizer only (a few MB of vocab); the model weights are loaded
    separately by app.embedding.
    """
    return AutoTokenizer.from_pretrained(settings.embedding_model)


def _token_count(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False))


@dataclass(frozen=True)
class _Segment:
    """A span of the section text that a chunk boundary may fall between,
    but never inside. Offsets index the section text directly so a rendered
    piece is a verbatim slice of it."""

    start: int
    end: int
    is_table_row: bool


def _segments(section_text: str) -> list[_Segment]:
    """The section's atomic units: one per table row, and one per sentence
    for every other line."""
    segments: list[_Segment] = []
    offset = 0

    for line in section_text.splitlines(keepends=True):
        if _TABLE_ROW.match(line.strip()):
            segments.append(_Segment(offset, offset + len(line), True))
        else:
            cursor = 0
            for match in _SENTENCE_SPLIT.finditer(line):
                segments.append(_Segment(offset + cursor, offset + match.end(), False))
                cursor = match.end()
            if cursor < len(line):
                segments.append(_Segment(offset + cursor, offset + len(line), False))
        offset += len(line)

    return segments


def _table_header(section_text: str, segments: list[_Segment]) -> str | None:
    """The section's table header (title row + its "|---|" underline), to be
    repeated on continuation pieces. None when the section has no table, or
    has one whose first rows aren't a recognizable header."""
    rows = [s for s in segments if s.is_table_row]
    if len(rows) < 2:
        return None
    if not _TABLE_SEPARATOR.match(section_text[rows[1].start : rows[1].end].strip()):
        return None
    return section_text[rows[0].start : rows[1].end].strip()


def _render(section_text: str, segments: list[_Segment], header: str | None) -> str:
    piece = section_text[segments[0].start : segments[-1].end].strip()
    if not piece:
        return ""
    # A piece that opens mid-table gets the header back, so every chunk of a
    # multi-chunk table names its own columns.
    if header and segments[0].is_table_row and not piece.startswith(header):
        piece = f"{header}\n{piece}"
    return piece


def _split_long_section(section_text: str, max_tokens: int) -> list[str]:
    segments = _segments(section_text)
    if not segments:
        return [section_text]

    header = _table_header(section_text, segments)

    pieces: list[str] = []
    current: list[_Segment] = []
    current_tokens = 0

    for segment in segments:
        segment_tokens = _token_count(section_text[segment.start : segment.end])
        # A single segment over budget (a very long sentence, or a wide table
        # row) is emitted whole and overshoots max_tokens — better an oversized
        # chunk than a severed table row or half a sentence.
        if current and current_tokens + segment_tokens > max_tokens:
            pieces.append(_render(section_text, current, header))
            current = []
            current_tokens = 0
        current.append(segment)
        current_tokens += segment_tokens

    if current:
        pieces.append(_render(section_text, current, header))

    return [piece for piece in pieces if piece] or [section_text]


def chunk_document(text: str, max_tokens: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    index = 0

    for label, section_text in _split_sections(text):
        pieces = (
            [section_text]
            if _token_count(section_text) <= max_tokens
            else _split_long_section(section_text, max_tokens)
        )

        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            chunks.append(Chunk(chunk_index=index, section=label, content=piece))
            index += 1

    return chunks
