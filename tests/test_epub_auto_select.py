from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.core.blocks import Block
from cookimport.parsing.epub_auto_select import select_epub_extractor_auto


class _FakeImporter:
    def inspect(self, _path: Path):
        return SimpleNamespace(sheets=[SimpleNamespace(spine_count=8)])

    def _extract_docpack(
        self,
        _path: Path,
        *,
        start_spine: int | None,
        end_spine: int | None,
        extractor: str,
    ) -> list[Block]:
        if start_spine is None or end_spine is None:
            raise RuntimeError("spine range required")
        if extractor == "unstructured":
            raise RuntimeError("unstructured failed")
        if extractor == "legacy":
            # Poor shape: single giant block.
            return [Block(text="x" * 5000)]

        # Structured markdown-like output wins.
        title = Block(text=f"Recipe {start_spine}", font_weight="bold")
        title.add_feature("is_heading", True)
        title.add_feature("heading_level", 1)
        item = Block(text="1 cup flour")
        item.add_feature("is_list_item", True)
        body = Block(text="Mix and cook.")
        return [title, item, body]


def test_select_epub_extractor_auto_is_deterministic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = tmp_path / "book.epub"
    path.write_text("dummy", encoding="utf-8")

    fake_importer = _FakeImporter()
    monkeypatch.setattr(
        "cookimport.parsing.epub_auto_select.registry.get_importer",
        lambda _name: fake_importer,
    )

    first = select_epub_extractor_auto(path)
    second = select_epub_extractor_auto(path)

    assert first.effective_extractor == "markdown"
    assert second.effective_extractor == "markdown"
    assert first.artifact["sample_indices"] == second.artifact["sample_indices"]


def test_select_epub_extractor_auto_raises_when_all_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "book.epub"
    path.write_text("dummy", encoding="utf-8")

    class _AlwaysFailImporter(_FakeImporter):
        def _extract_docpack(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "cookimport.parsing.epub_auto_select.registry.get_importer",
        lambda _name: _AlwaysFailImporter(),
    )

    with pytest.raises(RuntimeError):
        select_epub_extractor_auto(path)
