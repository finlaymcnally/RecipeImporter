from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cf_debug_cli import app


runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-04_20.33.53/single-profile-benchmark/upload_bundle_v1"
)


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        rows.append(json.loads(text))
    return rows


def test_select_cases_is_byte_stable_for_same_arguments(tmp_path: Path) -> None:
    out_path = tmp_path / "selectors.json"
    args = [
        "select-cases",
        "--bundle",
        str(SAMPLE_BUNDLE),
        "--stage",
        "line_role",
        "--include-case-id",
        "regression_c6",
        "--include-case-id",
        "regression_c11",
        "--include-case-id",
        "outside_span_window_628_657",
        "--include-case-id",
        "win_c10",
        "--out",
        str(out_path),
    ]

    first = runner.invoke(app, args)
    assert first.exit_code == 0
    first_bytes = out_path.read_bytes()

    second = runner.invoke(app, args)
    assert second.exit_code == 0
    second_bytes = out_path.read_bytes()

    assert first_bytes == second_bytes

    payload = _read_json(out_path)
    selectors = payload["selectors"]
    assert [row["case_id"] for row in selectors] == [
        "outside_span_window_628_657",
        "regression_c11",
        "regression_c6",
        "win_c10",
    ]
    outside_span = selectors[0]
    assert outside_span["kind"] == "line_range"
    assert outside_span["start"] == 628
    assert outside_span["end"] == 657


def test_pack_writes_fact_artifacts_for_sample_bundle(tmp_path: Path) -> None:
    selectors_path = tmp_path / "selectors.json"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--stage",
            "line_role",
            "--include-case-id",
            "regression_c6",
            "--include-case-id",
            "win_c10",
            "--out",
            str(selectors_path),
        ],
    )
    assert select_result.exit_code == 0

    pack_dir = tmp_path / "pack"
    pack_result = runner.invoke(
        app,
        [
            "pack",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--selectors",
            str(selectors_path),
            "--out",
            str(pack_dir),
        ],
    )
    assert pack_result.exit_code == 0

    pack_index = _read_json(pack_dir / "index.json")
    assert pack_index["schema_version"] == "cf.followup_pack.v1"
    assert pack_index["selector_count"] == 2
    assert (pack_dir / "README.md").is_file()
    assert (pack_dir / "case_export" / "case_export.jsonl").is_file()
    assert (pack_dir / "line_role_audit.jsonl").is_file()
    assert (pack_dir / "prompt_link_audit.jsonl").is_file()
    assert (pack_dir / "page_context.jsonl").is_file()
    assert (pack_dir / "uncertainty.jsonl").is_file()

    case_rows = _read_jsonl(pack_dir / "case_export" / "case_export.jsonl")
    assert [row["case_id"] for row in case_rows] == ["regression_c6", "win_c10"]
    regression_case = case_rows[0]
    assert regression_case["metrics"]["delta_codex_minus_baseline"] == -0.8125
    assert regression_case["stage_comparison"]["short_title"] == (
        "Autumn: Roasted Squash, Sage, and Hazelnut"
    )

    audit_rows = _read_jsonl(pack_dir / "line_role_audit.jsonl")
    assert any(row["case_id"] == "regression_c6" for row in audit_rows)

    prompt_rows = _read_jsonl(pack_dir / "prompt_link_audit.jsonl")
    assert all(row["status"] in {"ok", "not_applicable"} for row in prompt_rows)

    uncertainty_rows = _read_jsonl(pack_dir / "uncertainty.jsonl")
    assert uncertainty_rows
