from __future__ import annotations

import json
from pathlib import Path

from cookimport.bench.quality_suite import (
    QualitySuite,
    discover_quality_suite,
    load_quality_suite,
    validate_quality_suite,
    write_quality_suite,
)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(row) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def _write_target(
    gold_root: Path,
    *,
    target_name: str,
    source_file: str,
    labels: list[str],
    canonical_chars: int,
) -> None:
    exports_root = gold_root / target_name / "exports"
    rows = [{"source_file": source_file, "label": label} for label in labels]
    _write_jsonl(exports_root / "freeform_span_labels.jsonl", rows)
    (exports_root / "canonical_text.txt").write_text(
        "x" * canonical_chars,
        encoding="utf-8",
    )


def test_discover_quality_suite_is_deterministic_with_representative_cap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("alpha", encoding="utf-8")
    (input_root / "beta.epub").write_text("beta", encoding="utf-8")
    (input_root / "gamma.epub").write_text("gamma", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_target(
        gold_root,
        target_name="alpha_target",
        source_file="alpha.epub",
        labels=["INGREDIENT_LINE", "INGREDIENT_LINE", "INSTRUCTION_LINE"],
        canonical_chars=120,
    )
    _write_target(
        gold_root,
        target_name="beta_target",
        source_file="beta.epub",
        labels=["INSTRUCTION_LINE"],
        canonical_chars=240,
    )
    _write_target(
        gold_root,
        target_name="gamma_target",
        source_file="gamma.epub",
        labels=["OTHER", "INGREDIENT_LINE", "INSTRUCTION_LINE", "RECIPE_TITLE"],
        canonical_chars=360,
    )
    _write_target(
        gold_root,
        target_name="missing_target",
        source_file="missing.epub",
        labels=["OTHER"],
        canonical_chars=180,
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [
            input_root / "alpha.epub",
            input_root / "beta.epub",
            input_root / "gamma.epub",
        ],
    )

    suite_a = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        max_targets=2,
        seed=42,
    )
    suite_b = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        max_targets=2,
        seed=42,
    )

    assert len(suite_a.targets) == 3
    assert len(suite_a.unmatched) == 1
    assert suite_a.selection["algorithm_version"] == "quality_representative_v1"
    assert suite_a.selection["selection_mode"] == "representative_strata"
    assert suite_a.selection["max_targets"] == 2
    assert suite_a.selection["seed"] == 42
    assert suite_a.selected_target_ids == suite_b.selected_target_ids
    assert len(suite_a.selected_target_ids) == 2
    assert set(suite_a.selected_target_ids).issubset(
        {target.target_id for target in suite_a.targets}
    )
    assert all(target.canonical_text_chars > 0 for target in suite_a.targets)
    assert all(target.gold_span_rows > 0 for target in suite_a.targets)


def test_discover_quality_suite_prefers_curated_cutdown_targets_when_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    for source_name in (
        "saltfatacidheat.epub",
        "thefoodlab.epub",
        "seaandsmoke.epub",
        "fallback.epub",
    ):
        (input_root / source_name).write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_target(
        gold_root,
        target_name="saltfatacidheatcutdown",
        source_file="saltfatacidheat.epub",
        labels=["INGREDIENT_LINE", "INSTRUCTION_LINE"],
        canonical_chars=400,
    )
    _write_target(
        gold_root,
        target_name="thefoodlabcutdown",
        source_file="thefoodlab.epub",
        labels=["INGREDIENT_LINE"],
        canonical_chars=300,
    )
    _write_target(
        gold_root,
        target_name="seaandsmokecutdown",
        source_file="seaandsmoke.epub",
        labels=["INSTRUCTION_LINE"],
        canonical_chars=200,
    )
    _write_target(
        gold_root,
        target_name="fallback_target",
        source_file="fallback.epub",
        labels=["OTHER"],
        canonical_chars=100,
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [
            input_root / "saltfatacidheat.epub",
            input_root / "thefoodlab.epub",
            input_root / "seaandsmoke.epub",
            input_root / "fallback.epub",
        ],
    )

    suite = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        seed=42,
    )

    assert suite.selected_target_ids == [
        "saltfatacidheatcutdown",
        "thefoodlabcutdown",
        "seaandsmokecutdown",
    ]
    assert suite.selection["selection_mode"] == "curated_target_ids"
    assert suite.selection["preferred_target_ids_missing"] == []


def test_discover_quality_suite_curated_selection_fills_remaining_slots_when_capped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    for source_name in (
        "saltfatacidheat.epub",
        "thefoodlab.epub",
        "seaandsmoke.epub",
        "fallback_a.epub",
        "fallback_b.epub",
        "fallback_c.epub",
    ):
        (input_root / source_name).write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_target(
        gold_root,
        target_name="saltfatacidheatcutdown",
        source_file="saltfatacidheat.epub",
        labels=["INGREDIENT_LINE", "INSTRUCTION_LINE"],
        canonical_chars=400,
    )
    _write_target(
        gold_root,
        target_name="thefoodlabcutdown",
        source_file="thefoodlab.epub",
        labels=["INGREDIENT_LINE"],
        canonical_chars=300,
    )
    _write_target(
        gold_root,
        target_name="seaandsmokecutdown",
        source_file="seaandsmoke.epub",
        labels=["INSTRUCTION_LINE"],
        canonical_chars=200,
    )
    _write_target(
        gold_root,
        target_name="fallback_a",
        source_file="fallback_a.epub",
        labels=["OTHER", "OTHER", "OTHER"],
        canonical_chars=800,
    )
    _write_target(
        gold_root,
        target_name="fallback_b",
        source_file="fallback_b.epub",
        labels=["OTHER", "RECIPE_TITLE"],
        canonical_chars=700,
    )
    _write_target(
        gold_root,
        target_name="fallback_c",
        source_file="fallback_c.epub",
        labels=["OTHER"],
        canonical_chars=600,
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [
            input_root / "saltfatacidheat.epub",
            input_root / "thefoodlab.epub",
            input_root / "seaandsmoke.epub",
            input_root / "fallback_a.epub",
            input_root / "fallback_b.epub",
            input_root / "fallback_c.epub",
        ],
    )

    suite_a = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        max_targets=5,
        seed=42,
    )
    suite_b = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        max_targets=5,
        seed=42,
    )

    assert suite_a.selected_target_ids == suite_b.selected_target_ids
    assert suite_a.selected_target_ids[:3] == [
        "saltfatacidheatcutdown",
        "thefoodlabcutdown",
        "seaandsmokecutdown",
    ]
    assert len(suite_a.selected_target_ids) == 5
    assert set(suite_a.selected_target_ids[3:]).issubset(
        {"fallback_a", "fallback_b", "fallback_c"}
    )
    assert len(suite_a.selection["representative_fill_target_ids"]) == 2


def test_discover_quality_suite_falls_back_to_raw_input_filenames_when_importable_scan_is_empty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True, exist_ok=True)
    (input_root / "alpha.epub").write_text("epub", encoding="utf-8")

    gold_root = tmp_path / "gold"
    _write_target(
        gold_root,
        target_name="alpha_target",
        source_file="alpha.epub",
        labels=["OTHER"],
        canonical_chars=64,
    )

    monkeypatch.setattr(
        "cookimport.bench.speed_suite._list_importable_files",
        lambda _input_root: [],
    )

    suite = discover_quality_suite(
        gold_root=gold_root,
        input_root=input_root,
        seed=42,
    )

    assert len(suite.targets) == 1
    assert suite.targets[0].target_id == "alpha_target"
    assert suite.selected_target_ids == ["alpha_target"]
    assert suite.unmatched == []


def test_quality_suite_round_trip_and_validate(tmp_path: Path) -> None:
    source = tmp_path / "input" / "alpha.epub"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("epub", encoding="utf-8")
    gold_spans = tmp_path / "gold" / "alpha" / "exports" / "freeform_span_labels.jsonl"
    _write_jsonl(gold_spans, [{"source_file": "alpha.epub", "label": "OTHER"}])
    (gold_spans.parent / "canonical_text.txt").write_text("abc", encoding="utf-8")

    suite = QualitySuite(
        name="quality_test",
        generated_at="2026-02-28_12.00.00",
        gold_root=str((tmp_path / "gold").resolve()),
        input_root=str((tmp_path / "input").resolve()),
        seed=42,
        max_targets=1,
        selection={
            "algorithm_version": "quality_representative_v1",
            "seed": 42,
            "max_targets": 1,
            "matched_count": 1,
            "strata_counts": {"small:sparse": 1},
        },
        targets=[
            {
                "target_id": "alpha",
                "source_file": str(source.resolve()),
                "gold_spans_path": str(gold_spans.resolve()),
                "source_hint": "alpha.epub",
                "canonical_text_chars": 3,
                "gold_span_rows": 1,
                "label_count": 1,
                "size_bucket": "small",
                "label_bucket": "sparse",
            }
        ],
        selected_target_ids=["alpha"],
        unmatched=[],
    )

    suite_path = tmp_path / "suite.json"
    write_quality_suite(suite_path, suite)
    loaded = load_quality_suite(suite_path)

    assert loaded.name == suite.name
    assert loaded.selected_target_ids == ["alpha"]
    assert validate_quality_suite(loaded, repo_root=tmp_path) == []
