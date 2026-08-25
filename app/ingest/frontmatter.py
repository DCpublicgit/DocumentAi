"""Strip non-policy front matter and inline annotations before chunking.

The source .txt files are annotated transcriptions, not pure policy text.
Three header conventions carry metadata (title, doc number, owner, ISO
clause, ...) ahead of the real body, and transcriber/analyst commentary
(source defects, data-quality flags, governance context, OCR notes) is
interleaved inline. None of it is policy content — one convention says so
explicitly ("[DOCUMENT METADATA — not policy content, do not chunk/cite
this block]") — so none of it may reach policy_chunks/embeddings; doing so
would let the RAG index surface it as if it were a real cited policy
section. See DATA_CONTRACT.md's citation contract.

app/ingest/registry.py re-reads the raw file independently to populate
policy_documents, so stripping here has no effect on that metadata parse.
"""

import re

_BRACKET_METADATA_BLOCK = re.compile(
    r"\[DOCUMENT METADATA.*?\[END METADATA\]\s*", re.DOTALL
)

# Inline transcriber/analyst commentary — appears both inside and outside
# the bracket metadata block, and outside it can sit mid-clause (e.g. right
# before a numbered sub-item) or even mid-table-row, so this pass runs across
# the whole text and spans newlines.
#
# "Эх сурвалж" here is the transcription provenance footer
# ("[Эх сурвалж: <original>.pdf, 7 хуудас, ...]"), NOT policy content. It
# MUST be stripped: "Эх сурвалж:" is also our citation header
# (app/contract.py), and both ui/src/lib/parseCitations.js and
# app/eval/runner.py split an answer at its FIRST occurrence — so a chunk
# carrying this footer can make the UI truncate the answer and mis-parse the
# citation list. Only the bracketed form is matched, so a policy sentence
# that happens to use the phrase is left alone.
_BRACKET_ANNOTATION = re.compile(
    r"\[(?:SOURCE NOTE|DATA QUALITY FLAG|GOVERNANCE NOTE|NOTE|Тэмдэглэл|Эх сурвалж)\b.*?\]",
    re.DOTALL | re.IGNORECASE,
)

# The "=== ... ===" header convention's non-policy blocks: field metadata,
# approval signoff names, and the table of contents (whose entries are
# frequently stale/broken — see the KNOWN_DQ_FLAGS toc_broken_ref cases in
# registry.py — and must never stand in for a real section heading).
_EQUALS_NON_POLICY_BLOCK = re.compile(
    r"^===\s*(?:METADATA|БАТАЛГААЖУУЛАЛТ|АГУУЛГА)\s*===\s*\n.*?(?=^===|\Z)",
    re.DOTALL | re.MULTILINE,
)

# The third convention: no wrapper at all, just a run of "Label: value"
# lines at the very top of the file (see app/ingest/registry.py's label
# patterns for the same set).
_BARE_HEADER_LABELS = (
    "БАРИМТ БИЧИГ",
    "ДУГААР",
    "ИШ ТАТАЛТ",
    "Иш таталт",
    "Баримт бичгийн нэр",
    "Баримт бичгийн төрөл",
    "Боловсруулсан нэгж",
    "Хэрэгжүүлэх нэгж",
    "Мэдээллийн ангилал",
    "Мөрдөж эхлэх огноо",
    "Хуудасны тоо",
    "Бүртгэлийн дугаар",
    "Хувилбар",
    "Нууцын зэрэг",
)
_BARE_HEADER_LINE = re.compile(
    r"^(?:" + "|".join(re.escape(label) for label in _BARE_HEADER_LABELS) + r"):"
)

_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


def _strip_bare_header(text: str) -> str:
    lines = text.split("\n")
    i = 0
    while i < len(lines) and (not lines[i].strip() or _BARE_HEADER_LINE.match(lines[i].strip())):
        i += 1
    return "\n".join(lines[i:])


def strip_front_matter(text: str) -> str:
    text = _BRACKET_METADATA_BLOCK.sub("", text)
    text = _BRACKET_ANNOTATION.sub("", text)
    text = _EQUALS_NON_POLICY_BLOCK.sub("", text)
    text = _strip_bare_header(text)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)
    return text.strip()
