from __future__ import annotations

from pathlib import Path

import pytest

from cookimport.plugins.epub import EpubImporter
from tests.fixtures.make_epub import make_synthetic_epub


def _extract_blocks(epub_path: Path, *, extractor: str) -> list:
    importer = EpubImporter()
    importer._overrides = None  # noqa: SLF001
    try:
        return importer._extract_docpack(epub_path, extractor=extractor)  # noqa: SLF001
    except ModuleNotFoundError:
        if extractor == "unstructured":
            pytest.skip("unstructured dependency not available in test environment")
        raise


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_text_normalization_handles_soft_hyphen_and_unicode_noise(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"normalize-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Normalization</h1>
                <p>Ingredients</p>
                <p>1\u00a0cup but\u00adter</p>
                <p>1\u200bcup milk</p>
                <p>1\u00bd tsp salt</p>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    text_blob = "\n".join(block.text for block in blocks)
    assert "\u00ad" not in text_blob
    assert "\u200b" not in text_blob
    assert "1 cup butter" in text_blob
    assert "1/2 tsp salt" in text_blob


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_br_collapsed_ingredient_lines_are_split(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"br-split-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>BR Split</h1>
                <p>Ingredients</p>
                <p>1 cup flour<br/>2 eggs<br/>1/2 tsp salt</p>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    texts = {block.text for block in blocks}
    assert {"1 cup flour", "2 eggs", "1/2 tsp salt"}.issubset(texts)


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_bullet_prefixes_are_removed_before_signal_detection(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"bullet-strip-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Bullet Ingredients</h1>
                <ul>
                  <li>• 1 cup sugar</li>
                  <li>– 2 tbsp oil</li>
                </ul>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    ingredient_blocks = [
        block for block in blocks if "sugar" in block.text or "oil" in block.text
    ]
    assert ingredient_blocks
    assert all(
        not block.text.startswith(("•", "–", "-", "—")) for block in ingredient_blocks
    )
    assert any(block.features.get("starts_with_quantity") for block in ingredient_blocks)


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_nav_spine_document_is_ignored(
    tmp_path: Path,
    extractor: str,
) -> None:
    nav_doc = """
    <nav epub:type="toc">
      <h1>Table of Contents</h1>
      <ol>
        <li><a href="chapter1.xhtml">Noise Chapter</a></li>
      </ol>
    </nav>
    """
    source = make_synthetic_epub(
        tmp_path / f"nav-skip-{extractor}.epub",
        nav_document=nav_doc,
        include_nav_in_spine=True,
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Example Stew</h1>
                <p>Ingredients</p>
                <p>1 cup broth</p>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    text_blob = "\n".join(block.text for block in blocks)
    assert "Table of Contents" not in text_blob
    assert "Noise Chapter" not in text_blob
    assert "Example Stew" in text_blob


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_pagebreak_markers_are_filtered(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"pagebreak-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Pagebreak test</h1>
                <p epub:type="pagebreak">12</p>
                <p role="doc-pagebreak">13</p>
                <p>1 cup flour</p>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    block_texts = [block.text.strip() for block in blocks]
    assert "12" not in block_texts
    assert "13" not in block_texts
    assert "1 cup flour" in block_texts


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_table_rows_preserve_cells_and_delimiter(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"table-rows-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Table Ingredients</h1>
                <table>
                  <tr><th>Ingredient</th><th>Type</th><th>Amount</th><th>Weight</th></tr>
                  <tr><td>Water</td><td></td><td>1 cup</td><td>8 ounces</td></tr>
                  <tr><td>Butter</td><td></td><td>1 tbsp</td><td>0.5 ounce</td></tr>
                </table>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    rows = [block for block in blocks if block.features.get("epub_table_row")]
    assert any(row.text == "Ingredient | Type | Amount | Weight" for row in rows)

    water_row = next(row for row in rows if row.text.startswith("Water |"))
    assert water_row.features.get("epub_table_cells") == ["Water", "", "1 cup", "8 ounces"]
    assert water_row.features.get("epub_table_column_count") == 4


@pytest.mark.parametrize("extractor", ["beautifulsoup", "unstructured"])
def test_epub_table_rows_still_trigger_quantity_signals(
    tmp_path: Path,
    extractor: str,
) -> None:
    source = make_synthetic_epub(
        tmp_path / f"table-quantity-{extractor}.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                """
                <h1>Table Ingredients</h1>
                <table>
                  <tr><td>1 cup</td><td>sugar</td></tr>
                  <tr><td>2 tbsp</td><td>oil</td></tr>
                </table>
                """,
            ),
        ],
    )

    blocks = _extract_blocks(source, extractor=extractor)
    rows = [block for block in blocks if block.features.get("epub_table_row")]
    assert any(row.text == "1 cup | sugar" for row in rows)
    assert any(row.text == "2 tbsp | oil" for row in rows)
    assert any(row.features.get("starts_with_quantity") for row in rows)


def test_epub_health_warnings_are_written_to_report_and_raw_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repeated_lines = "".join("<p>content noise</p>" for _ in range(48))
    source = make_synthetic_epub(
        tmp_path / "health-warning.epub",
        spine_documents=[
            (
                "chapter1.xhtml",
                f"""
                <h1>Health Check</h1>
                {repeated_lines}
                """,
            ),
        ],
    )

    monkeypatch.setenv("C3IMP_EPUB_EXTRACTOR", "beautifulsoup")
    result = EpubImporter().convert(source, None)
    assert "epub_duplicate_block_rate_high" in result.report.warnings

    health_artifact = next(
        artifact
        for artifact in result.raw_artifacts
        if artifact.location_id == "epub_extraction_health"
    )
    assert health_artifact.content["warnings"]
    assert health_artifact.content["metrics"]["duplicate_block_rate"] > 0.35
