"""app.documents resolves a citation's docId back to a real file on disk —
the critical property is that a client-supplied file_name can NEVER escape
POLICY_DIR, since it only ever selects among files actually found by
scanning the directory (see the module docstring).
"""

from pathlib import Path

from app.config import settings
from app.documents import find_document_path, guess_content_type


def _write(tmp_path, name: str, content: str = "агуулга") -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")


def test_finds_a_file_matching_the_naming_convention(tmp_path, monkeypatch):
    _write(tmp_path, "Чөлөө_олгох_журам__v3__2025-01-01.txt")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    path = find_document_path("Чөлөө_олгох_журам.txt")

    assert path is not None
    assert path.name == "Чөлөө_олгох_журам__v3__2025-01-01.txt"


def test_finds_a_legacy_file_with_no_version_suffix(tmp_path, monkeypatch):
    _write(tmp_path, "Хуучин_бодлого.txt")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    path = find_document_path("Хуучин_бодлого.txt")

    assert path is not None
    assert path.name == "Хуучин_бодлого.txt"


def test_narrows_to_the_exact_version_when_given(tmp_path, monkeypatch):
    _write(tmp_path, "Бодлого__v1__2024-01-01.txt", content="хуучин")
    _write(tmp_path, "Бодлого__v2__2025-01-01.txt", content="шинэ")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    path = find_document_path("Бодлого.txt", policy_version="v1")

    assert path is not None
    assert path.read_text(encoding="utf-8") == "хуучин"


def test_returns_none_for_a_file_name_that_does_not_exist(tmp_path, monkeypatch):
    _write(tmp_path, "Бодлого__v1__2024-01-01.txt")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    assert find_document_path("Байхгүй_файл.txt") is None


def test_path_traversal_attempt_never_escapes_policy_dir(tmp_path, monkeypatch):
    """The core safety property: file_name only ever selects among files
    ACTUALLY FOUND by scanning POLICY_DIR — it is never concatenated into a
    filesystem path — so a client cannot use "../" (or an absolute path) to
    read anything outside the corpus, regardless of what exists on the real
    filesystem above tmp_path."""
    _write(tmp_path, "Бодлого__v1__2024-01-01.txt")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    assert find_document_path("../../../../etc/passwd") is None
    assert find_document_path("..\\..\\Windows\\System32\\drivers\\etc\\hosts") is None
    assert find_document_path("/etc/passwd") is None


def test_ignores_non_servable_file_types_in_policy_dir(tmp_path, monkeypatch):
    (tmp_path / "Бодлого.txt.tmp").write_text("stray temp file", encoding="utf-8")
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path))

    assert find_document_path("Бодлого.txt.tmp") is None


def test_returns_none_when_policy_dir_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "policy_dir", str(tmp_path / "nope"))

    assert find_document_path("Бодлого.txt") is None


def test_guess_content_type_covers_all_supported_extensions():
    assert guess_content_type(Path("Бодлого.txt")) == "text/plain"
    assert guess_content_type(Path("a.pdf")) == "application/pdf"
    assert guess_content_type(Path("a.docx")) == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


def test_guess_content_type_falls_back_for_an_unknown_extension():
    assert guess_content_type(Path("a.xyz")) == "application/octet-stream"
