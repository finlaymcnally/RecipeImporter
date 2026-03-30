from pathlib import Path
from typing import cast

from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.ingest_support import (
    _dedupe_project_name,
    _resolve_project_name,
)


def test_dedupe_project_name_adds_incrementing_suffix() -> None:
    existing = {"the_food_lab", "the_food_lab-1", "other"}
    assert _dedupe_project_name("the_food_lab", existing) == "the_food_lab-2"


def test_resolve_project_name_uses_explicit_name_without_lookup() -> None:
    class FakeClient:
        def list_projects(self) -> list[dict[str, object]]:
            raise AssertionError("list_projects should not be called for explicit names")

    resolved = _resolve_project_name(
        Path("data/input/the_food_lab.epub"),
        "Manual Project",
        cast(LabelStudioClient, FakeClient()),
    )
    assert resolved == "Manual Project"


def test_resolve_project_name_defaults_to_file_stem_and_dedupes() -> None:
    class FakeClient:
        def list_projects(self) -> list[dict[str, object]]:
            return [
                {"title": "the_food_lab"},
                {"title": "the_food_lab-1"},
                {"title": "Unrelated"},
            ]

    resolved = _resolve_project_name(
        Path("data/input/the_food_lab.epub"),
        None,
        cast(LabelStudioClient, FakeClient()),
    )
    assert resolved == "the_food_lab-2"
