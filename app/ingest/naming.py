"""Derive policy_version + effective_date from a policy file's name.

Convention: "{Name}__v{version}__{YYYY-MM-DD}.{ext}"
e.g. "Чөлөө олгох журам__v3__2025-01-01.pdf"

Fallbacks when a file doesn't follow the convention (sane, not silent —
callers see the fallback values in the DQ summary via normal logging):
  - no "__v{version}__" segment found -> policy_version = DEFAULT_VERSION ("v1")
  - version segment present but date missing/unparseable -> effective_date = None
  - file_name stored in the DB is always "{Name}{ext}" (version/date stripped
    out, since they already live in their own columns per DATA_CONTRACT.md);
    if the pattern doesn't match at all, the original filename is used as-is.
"""

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DEFAULT_VERSION = "v1"

_PATTERN = re.compile(
    r"^(?P<name>.+?)__(?P<version>v[A-Za-z0-9.]+)__(?P<date>\d{4}-\d{2}-\d{2})$"
)

_VERSION_SEGMENT = re.compile(r"(\d+)|([A-Za-z]+)")


def version_sort_key(policy_version: str) -> tuple[tuple[int, int, str], ...]:
    """Ordering key for policy_version strings, so "newest version" is a real
    comparison rather than "whichever was ingested last".

    Compares segment-wise with numeric segments ordered numerically, so
    v2 < v10 (a plain string sort gets this wrong) and v1 < v1.1 (a shorter
    prefix sorts first). Non-numeric segments sort after numeric ones at the
    same position, so an unparseable version is still ordered deterministically
    rather than raising.
    """
    raw = policy_version[1:] if policy_version[:1].lower() == "v" else policy_version
    return tuple(
        (0, int(number), "") if number else (1, 0, alpha.lower())
        for number, alpha in _VERSION_SEGMENT.findall(raw)
    )


def latest_version(versions: list[str]) -> str:
    """The newest of `versions` per version_sort_key. The raw string is the
    tiebreak so two versions with an identical key resolve deterministically.
    """
    return max(versions, key=lambda v: (version_sort_key(v), v))


@dataclass(frozen=True)
class ParsedName:
    file_name: str
    policy_version: str
    effective_date: date | None


def parse_filename(path: Path) -> ParsedName:
    match = _PATTERN.match(path.stem)
    if match is None:
        return ParsedName(
            file_name=path.name,
            policy_version=DEFAULT_VERSION,
            effective_date=None,
        )

    name = match.group("name")
    version = match.group("version")
    try:
        effective_date = date.fromisoformat(match.group("date"))
    except ValueError:
        effective_date = None

    return ParsedName(
        file_name=f"{name}{path.suffix}",
        policy_version=version,
        effective_date=effective_date,
    )
