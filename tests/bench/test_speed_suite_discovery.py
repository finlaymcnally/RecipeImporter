from __future__ import annotations

import json
from pathlib import Path

from cookimport.bench.speed_suite import (
    SpeedSuite,
    _discover_freeform_gold_exports,
    discover_speed_targets,
    load_speed_suite,
    validate_speed_suite,
    write_speed_suite,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def test_discover_speed_targets_matches_and_reports_unmatched(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_jsonl(
        gold_root / "match_a" / "exports" / "freeform_span_labels.jsonl",
        [{"source_file": "alpha.epub"}],
    )
    _write_jsonl(
        gold_root / "missing_b" / "exports" / "freeform_span_labels.jsonl",
        [{"source_file": "missing.epub"}],
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [input_root / "alpha.epub"],
    )
    suite = discover_speed_targets(gold_root=gold_root, input_root=input_root)

    assert suite.name.startswith("speed_")
    assert len(suite.targets) == 1
    assert suite.targets[0].target_id == "match_a"
    assert suite.targets[0].source_hint == "alpha.epub"
    assert suite.targets[0].source_file.endswith("input/alpha.epub")
    assert len(suite.unmatched) == 1
    assert "No importable file named `missing.epub`" in str(
        suite.unmatched[0].get("reason")
    )


def test_discover_speed_targets_uses_run_manifest_source_hint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "beta.epub").write_text("epub", encoding="utf-8")

    gold_target = tmp_path / "gold" / "book_beta"
    _write_jsonl(
        gold_target / "exports" / "freeform_span_labels.jsonl",
        [{"label": "OTHER"}],
    )
    (gold_target / "run_manifest.json").write_text(
        json.dumps({"source": {"path": "/tmp/somewhere/beta.epub"}}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [input_root / "beta.epub"],
    )
    suite = discover_speed_targets(
        gold_root=tmp_path / "gold",
        input_root=input_root,
    )

    assert len(suite.targets) == 1
    assert suite.targets[0].source_hint == "beta.epub"
    assert suite.targets[0].source_file.endswith("input/beta.epub")


def test_discover_speed_targets_ignores_live_row_gold_backups(tmp_path: Path) -> None:
    canonical = tmp_path / "gold" / "saltfatacidheatcutdown" / "exports"
    canonical.mkdir(parents=True, exist_ok=True)
    canonical_path = canonical / "freeform_span_labels.jsonl"
    canonical_path.write_text("{}\n", encoding="utf-8")

    backup = (
        tmp_path
        / "gold"
        / "saltfatacidheatcutdown"
        / "live_row_gold_backups"
        / "2026-04-14_17.46.26_project-119"
        / "exports"
    )
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "freeform_span_labels.jsonl").write_text("{}\n", encoding="utf-8")

    assert _discover_freeform_gold_exports(tmp_path / "gold") == [canonical_path]


def test_speed_suite_round_trip_and_validate(tmp_path: Path) -> None:
    source = tmp_path / "input" / "alpha.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "alpha" / "exports" / "freeform_span_labels.jsonl"
    _write_jsonl(gold_spans, [{"source_file": "alpha.epub"}])

    suite = SpeedSuite(
        name="speed_test",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str((tmp_path / "input").resolve()),
        targets=[
            {
                "target_id": "alpha",
                "source_file": str(source.resolve()),
                "gold_spans_path": str(gold_spans.resolve()),
            }
        ],
        unmatched=[],
    )
    suite_path = tmp_path / "suite.json"
    write_speed_suite(suite_path, suite)
    loaded = load_speed_suite(suite_path)

    assert loaded.name == suite.name
    assert loaded.targets[0].target_id == "alpha"
    assert validate_speed_suite(loaded, repo_root=tmp_path) == []
