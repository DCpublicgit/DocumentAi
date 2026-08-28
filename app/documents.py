"""Resolves a citation's `docId` (== policy_chunks.file_name) back to the
real file on disk, for the "view full document" link behind
GET /v1/documents/{file_name} in app.server.

Deliberately re-derives the (file_name, policy_version) -> on-disk path
mapping from app.ingest.naming.parse_filename on every call rather than
caching it: the corpus is small (~30 files, see docs/DATA_CONTRACT.md's cost
posture — no caching machinery until measured traffic justifies it), and
this keeps the endpoint correct even if policies/ changes between ingests,
with zero staleness to reason about.
"""

import mimetypes
from pathlib import Path

from app.config import settings
from app.ingest.naming import parse_filename, version_sort_key

# Extensions app.ingest.extract actually knows how to read — anything else in
# POLICY_DIR is not a real corpus file (a stray .DS_Store, a half-copied
# temp file) and must never be servable.
_SERVABLE_EXTENSIONS = {".pdf", ".docx", ".txt"}


def find_document_path(file_name: str, policy_version: str | None = None) -> Path | None:
    """`file_name` has its version/date segment already stripped (see
    app.ingest.naming's module docstring) — the on-disk file is named
    "{name}__v{version}__{date}{ext}", or plain "{name}{ext}" for a file
    that never followed the naming convention. Either way, matching by the
    SAME parse_filename() ingest itself uses is the only way back to the
    real path.

    Never builds a path from client input directly — `file_name` only ever
    selects a match among files actually scanned off disk, so a request
    value can't escape POLICY_DIR (no path-traversal surface: this returns
    a `Path` found by `iterdir()`, never `POLICY_DIR / user_input`).

    `policy_version`, when given, narrows to that exact version; omitted,
    returns the highest version among matches, per the SAME
    `version_sort_key` app.ingest.loader/registry_loader use to derive
    `is_current` — so this agrees with the DB's notion of "current" instead
    of an alphabetical directory-listing order, which is not a version
    ordering (e.g. "v10" would sort before "v2").
    """
    policy_dir = Path(settings.policy_dir)
    if not policy_dir.is_dir():
        return None
    matches: list[tuple[str, Path]] = []
    for path in sorted(policy_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in _SERVABLE_EXTENSIONS:
            continue
        parsed = parse_filename(path)
        if parsed.file_name != file_name:
            continue
        if policy_version is not None:
            if parsed.policy_version == policy_version:
                return path
            continue
        matches.append((parsed.policy_version, path))
    if not matches:
        return None
    return max(matches, key=lambda m: (version_sort_key(m[0]), m[0]))[1]


def guess_content_type(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(path.name)
    return content_type or "application/octet-stream"
