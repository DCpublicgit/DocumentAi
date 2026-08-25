from datetime import date
from pathlib import Path

from app.ingest.naming import (
    DEFAULT_VERSION,
    latest_version,
    parse_filename,
    version_sort_key,
)


def test_parses_name_version_and_date_from_convention():
    parsed = parse_filename(Path("Чөлөө олгох журам__v3__2025-01-01.pdf"))

    assert parsed.file_name == "Чөлөө олгох журам.pdf"
    assert parsed.policy_version == "v3"
    assert parsed.effective_date == date(2025, 1, 1)


def test_non_conforming_filename_falls_back_to_default_version():
    parsed = parse_filename(Path("Ажлын журам.txt"))

    assert parsed.file_name == "Ажлын журам.txt"
    assert parsed.policy_version == DEFAULT_VERSION
    assert parsed.effective_date is None


def test_versions_order_numerically_not_lexically():
    # The bug this guards: a plain string sort puts "v10" before "v2", which
    # would make v2 look newer and win the is_current flip.
    assert version_sort_key("v2") < version_sort_key("v10")
    assert latest_version(["v1", "v2", "v10"]) == "v10"
    assert latest_version(["v10", "v2", "v1"]) == "v10"


def test_dotted_versions_order_by_segment():
    assert version_sort_key("v1") < version_sort_key("v1.1")
    assert version_sort_key("v1.2") < version_sort_key("v1.10")
    assert latest_version(["v1.10", "v1.2", "v1"]) == "v1.10"


def test_latest_version_is_independent_of_input_order():
    versions = ["v3", "v1", "v10", "v2"]
    assert latest_version(versions) == "v10"
    assert latest_version(list(reversed(versions))) == "v10"


def test_unparseable_version_is_ordered_deterministically_not_raising():
    # Non-numeric segments sort after numeric ones rather than blowing up.
    assert version_sort_key("v1") < version_sort_key("vDRAFT")
    assert latest_version(["v1", "vDRAFT"]) == "vDRAFT"
    assert latest_version(["v2", "v2a"]) == "v2a"


def test_single_version_is_its_own_latest():
    assert latest_version(["v1"]) == "v1"
