"""Raw text extraction per source file type (pdf, docx, txt)."""

from pathlib import Path

import docx
import fitz  # PyMuPDF

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_pdf(path)
    if suffix == ".docx":
        return _extract_docx(path)
    if suffix == ".txt":
        return _extract_txt(path)
    raise ValueError(f"Unsupported file type: {suffix} ({path.name})")


def _extract_pdf(path: Path) -> str:
    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _extract_docx(path: Path) -> str:
    document = docx.Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


def _extract_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8")
