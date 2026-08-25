"""Mongolian Cyrillic text normalization.

Only touches unicode form and extraction artifacts — never rewords or
reorders content:
  - NFC unicode normalization (composed Cyrillic, consistent codepoints)
  - drop lines that are pure stray-quote/whitespace artifacts (a common
    PyMuPDF/python-docx extraction leftover), not quotes inside real text
  - collapse trailing whitespace and runs of 3+ blank lines
"""

import re
import unicodedata

_STRAY_QUOTE_LINE = re.compile(r'^[\s"\'`«»„“”]+$', re.MULTILINE)
_TRAILING_WS = re.compile(r"[ \t]+\n")
_MULTI_BLANK = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = _STRAY_QUOTE_LINE.sub("", text)
    text = _TRAILING_WS.sub("\n", text)
    text = _MULTI_BLANK.sub("\n\n", text)
    return text.strip()
