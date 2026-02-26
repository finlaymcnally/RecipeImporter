from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cli import app
from tests.fixtures.make_epub import make_test_epub


runner = CliRunner()


def test_epub_inspect_writes_report(tmp_path: Path) -> None:
    source = make_test_epub(tmp_path / "sample.epub", title="Inspect Me")
    out_dir = tmp_path / "inspect-out"

    result = runner.invoke(app, ["epub", "inspect", str(source), "--out", str(out_dir)])
    assert result.exit_code == 0

    report_path = out_dir / "inspect_report.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["title"] == "Inspect Me"
    assert payload["package_path"] == "OEBPS/content.opf"
    assert len(payload["spine"]) == 2
    assert payload["spine"][0]["href"] == "chapter1.xhtml"


def test_epub_dump_and_unpack_only_spine(tmp_path: Path) -> None:
    source = make_test_epub(tmp_path / "sample.epub")

    dump_dir = tmp_path / "dump-out"
    dump_result = runner.invoke(
        app,
        [
            "epub",
            "dump",
            str(source),
            "--spine-index",
            "0",
            "--format",
            "plain",
            "--out",
            str(dump_dir),
        ],
    )
    assert dump_result.exit_code == 0
    assert (dump_dir / "spine_0000.txt").exists()
    dump_meta = json.loads((dump_dir / "dump_meta.json").read_text(encoding="utf-8"))
    assert dump_meta["spine_index"] == 0
    assert dump_meta["href"] == "chapter1.xhtml"

    unpack_dir = tmp_path / "unpack-out"
    unpack_result = runner.invoke(
        app,
        [
            "epub",
            "unpack",
            str(source),
            "--out",
            str(unpack_dir),
            "--only-spine",
        ],
    )
    assert unpack_result.exit_code == 0
    assert (unpack_dir / "META-INF" / "container.xml").exists()
    assert (unpack_dir / "OEBPS" / "content.opf").exists()
    assert (unpack_dir / "OEBPS" / "chapter1.xhtml").exists()
    assert (unpack_dir / "OEBPS" / "chapter2.xhtml").exists()


def test_epub_blocks_and_candidates_write_artifacts(tmp_path: Path) -> None:
    source = make_test_epub(tmp_path / "sample.epub")

    blocks_dir = tmp_path / "blocks-out"
    blocks_result = runner.invoke(
        app,
        [
            "epub",
            "blocks",
            str(source),
            "--extractor",
            "beautifulsoup",
            "--out",
            str(blocks_dir),
        ],
    )
    assert blocks_result.exit_code == 0
    assert (blocks_dir / "blocks.jsonl").exists()
    assert (blocks_dir / "blocks_stats.json").exists()
    assert (blocks_dir / "blocks_preview.md").exists()
    stats = json.loads((blocks_dir / "blocks_stats.json").read_text(encoding="utf-8"))
    assert stats["block_count"] > 0
    assert stats["total_text_chars"] > 0

    candidates_dir = tmp_path / "candidates-out"
    candidates_result = runner.invoke(
        app,
        [
            "epub",
            "candidates",
            str(source),
            "--extractor",
            "beautifulsoup",
            "--out",
            str(candidates_dir),
        ],
    )
    assert candidates_result.exit_code == 0
    assert (candidates_dir / "candidates.json").exists()
    assert (candidates_dir / "candidates_preview.md").exists()
    candidates_payload = json.loads(
        (candidates_dir / "candidates.json").read_text(encoding="utf-8")
    )
    assert candidates_payload["block_count"] > 0
    assert candidates_payload["candidates"]


def test_epub_validate_missing_epubcheck_respects_strict(tmp_path: Path) -> None:
    source = make_test_epub(tmp_path / "sample.epub")

    non_strict = runner.invoke(app, ["epub", "validate", str(source)])
    assert non_strict.exit_code == 0
    assert "EPUBCheck jar not found" in non_strict.stdout

    strict = runner.invoke(app, ["epub", "validate", str(source), "--strict"])
    assert strict.exit_code == 1


def test_epub_race_command_is_not_available() -> None:
    result = runner.invoke(app, ["epub", "--help"])
    assert result.exit_code == 0
    assert "race" not in result.stdout
