from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from cookimport.cf_debug_cli import app


runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-04_20.33.53/single-profile-benchmark/upload_bundle_v1"
)
PASS4_SAMPLE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-06_15.22.11/single-profile-benchmark/upload_bundle_v1"
)
PASS4_SOURCE_KEY = "02_saltfatacidheatcutdown"


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


def _make_current_pass4_bundle(tmp_path: Path) -> Path:
    copied_root = tmp_path / "single-profile-benchmark"
    shutil.copytree(PASS4_SAMPLE_BUNDLE.parent, copied_root)
    bundle_dir = copied_root / "upload_bundle_v1"
    index_path = bundle_dir / "upload_bundle_index.json"
    index_payload = _read_json(index_path)
    index_payload["source_dir"] = str(copied_root)
    row_locators = ((index_payload.get("navigation") or {}).get("row_locators") or {})
    pass4_rows = row_locators.get("pass4_by_run")
    if isinstance(pass4_rows, list):
        for row in pass4_rows:
            if not isinstance(row, dict):
                continue
            if "knowledge_manifest_json" in row:
                continue
            for label, locator in list(row.items()):
                if label in {"run_id", "output_subdir"} or not isinstance(locator, dict):
                    continue
                locator_path = str(locator.get("path") or "")
                if "knowledge_manifest" not in locator_path:
                    continue
                row["knowledge_manifest_json"] = locator
                del row[label]
                break
    index_path.write_text(
        json.dumps(index_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload_path = bundle_dir / "upload_bundle_payload.jsonl"
    payload_rows = _read_jsonl(payload_path)
    for row in payload_rows:
        path = str(row.get("path") or "")
        if path.endswith("pass4_knowledge_manifest.json"):
            row["path"] = path[: -len("pass4_knowledge_manifest.json")] + "knowledge_manifest.json"
    payload_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in payload_rows),
        encoding="utf-8",
    )
    for manifest_path in copied_root.rglob("pass4_knowledge_manifest.json"):
        manifest_path.rename(manifest_path.with_name("knowledge_manifest.json"))
    return bundle_dir


def test_request_template_writes_web_ai_followup_manifest(tmp_path: Path) -> None:
    out_path = tmp_path / "followup_request.json"
    result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    assert payload["schema_version"] == "cf.followup_request.v1"
    assert payload["requester_context"]["already_has_upload_bundle_v1"] is True
    assert payload["asks"][0]["outputs"] == [
        "case_export",
        "line_role_audit",
        "prompt_link_audit",
        "page_context",
        "uncertainty",
    ]
    assert payload["asks"][0]["selectors"]["include_case_ids"] == ["regression_c6"]


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
    assert all(row["status"] in {"ok", "not_applicable", "broken"} for row in prompt_rows)

    uncertainty_rows = _read_jsonl(pack_dir / "uncertainty.jsonl")
    assert uncertainty_rows
    assert "trust_score" in uncertainty_rows[0]


def test_build_followup_writes_iterative_followup_packet(tmp_path: Path) -> None:
    template_path = tmp_path / "template.json"
    template_result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--out",
            str(template_path),
        ],
    )
    assert template_result.exit_code == 0
    template_payload = _read_json(template_path)

    request_path = tmp_path / "followup_request.json"
    request_payload = {
        "schema_version": "cf.followup_request.v1",
        "bundle_dir": str(SAMPLE_BUNDLE),
        "bundle_sha256": template_payload["bundle_sha256"],
        "request_id": "followup_data1_request",
        "request_summary": "Answer two targeted follow-up asks from the web AI.",
        "requester_context": {
            "already_has_upload_bundle_v1": True,
            "prefer_new_local_artifacts_over_bundle_repeats": True,
            "duplicate_bundle_payloads_only_when_needed_for_context": True,
        },
        "default_stage_filters": ["line_role"],
        "asks": [
            {
                "ask_id": "ask_regression_c6",
                "question": "Why is regression_c6 bad?",
                "outputs": ["case_export", "line_role_audit", "prompt_link_audit"],
                "selectors": {
                    "include_case_ids": ["regression_c6"],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["line_role"],
                },
            },
            {
                "ask_id": "ask_outside_span",
                "question": "Show context for the outside-span weird window.",
                "outputs": ["page_context", "uncertainty"],
                "selectors": {
                    "include_case_ids": ["outside_span_window_628_657"],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["line_role"],
                },
            },
        ],
    }
    request_path.write_text(json.dumps(request_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = tmp_path / "followup_data1"
    result = runner.invoke(
        app,
        [
            "build-followup",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--request",
            str(request_path),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    packet_index = _read_json(out_dir / "index.json")
    assert packet_index["schema_version"] == "cf.followup_packet.v1"
    assert packet_index["request_id"] == "followup_data1_request"
    assert packet_index["ask_count"] == 2
    assert (out_dir / "request_manifest.json").is_file()
    assert (out_dir / "README.md").is_file()

    ask1_dir = out_dir / "asks" / "ask_regression_c6"
    ask1_index = _read_json(ask1_dir / "index.json")
    assert ask1_index["delta_contract"]["requester_already_has_upload_bundle_v1"] is True
    assert (ask1_dir / "selectors.json").is_file()
    assert (ask1_dir / "case_export" / "case_export.jsonl").is_file()
    assert (ask1_dir / "line_role_audit.jsonl").is_file()
    assert (ask1_dir / "prompt_link_audit.jsonl").is_file()

    ask2_dir = out_dir / "asks" / "ask_outside_span"
    ask2_index = _read_json(ask2_dir / "index.json")
    assert ask2_index["requested_outputs"] == ["page_context", "uncertainty"]
    assert (ask2_dir / "page_context.jsonl").is_file()
    assert (ask2_dir / "uncertainty.jsonl").is_file()
    assert not (ask2_dir / "case_export").exists()

    selectors_payload = _read_json(ask2_dir / "selectors.json")
    assert selectors_payload["selectors"][0]["case_id"] == "outside_span_window_628_657"


def test_request_template_includes_pass4_example_when_bundle_has_pass4(tmp_path: Path) -> None:
    pass4_bundle = _make_current_pass4_bundle(tmp_path)
    out_path = tmp_path / "followup_request_pass4.json"
    result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(pass4_bundle),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    pass4_asks = [
        ask
        for ask in payload["asks"]
        if "pass4_knowledge_audit" in ask.get("outputs", [])
    ]
    assert pass4_asks
    assert pass4_asks[0]["selectors"]["stage_filters"] == ["pass4"]
    assert pass4_asks[0]["selectors"]["include_pass4_output_subdirs"] == [
        f"{PASS4_SOURCE_KEY}/codexfarm"
    ]


def test_select_cases_supports_pass4_source_key(tmp_path: Path) -> None:
    pass4_bundle = _make_current_pass4_bundle(tmp_path)
    out_path = tmp_path / "pass4_selectors.json"
    result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(pass4_bundle),
            "--stage",
            "pass4",
            "--include-pass4-source-key",
            PASS4_SOURCE_KEY,
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    selectors = payload["selectors"]
    assert len(selectors) == 1
    row = selectors[0]
    assert row["kind"] == "pass4_run"
    assert row["book_slug"] == PASS4_SOURCE_KEY
    assert row["output_subdir"] == f"{PASS4_SOURCE_KEY}/codexfarm"
    assert row["case_id"].startswith("pass4_")
    assert row["payload_locators"]


def test_audit_pass4_knowledge_writes_rows(tmp_path: Path) -> None:
    pass4_bundle = _make_current_pass4_bundle(tmp_path)
    selectors_path = tmp_path / "pass4_selectors.json"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(pass4_bundle),
            "--stage",
            "pass4",
            "--include-pass4-source-key",
            PASS4_SOURCE_KEY,
            "--out",
            str(selectors_path),
        ],
    )
    assert select_result.exit_code == 0

    out_path = tmp_path / "pass4_knowledge_audit.jsonl"
    result = runner.invoke(
        app,
        [
            "audit-pass4-knowledge",
            "--bundle",
            str(pass4_bundle),
            "--selectors",
            str(selectors_path),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    rows = _read_jsonl(out_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema_version"] == "cf.pass4_knowledge_audit.v1"
    assert row["book_slug"] == PASS4_SOURCE_KEY
    assert row["status"] == "ok"
    assert row["enabled"] is True
    assert row["outputs_parsed"] > 0
    assert "prompt_task4_txt" in row["local_artifacts"]
    assert "knowledge_manifest_json" in row["payload_locators"]


def test_pack_includes_pass4_knowledge_audit_and_case_export(tmp_path: Path) -> None:
    pass4_bundle = _make_current_pass4_bundle(tmp_path)
    selectors_path = tmp_path / "pass4_selectors.json"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(pass4_bundle),
            "--stage",
            "pass4",
            "--include-pass4-source-key",
            PASS4_SOURCE_KEY,
            "--out",
            str(selectors_path),
        ],
    )
    assert select_result.exit_code == 0

    pack_dir = tmp_path / "pass4_pack"
    pack_result = runner.invoke(
        app,
        [
            "pack",
            "--bundle",
            str(pass4_bundle),
            "--selectors",
            str(selectors_path),
            "--out",
            str(pack_dir),
        ],
    )
    assert pack_result.exit_code == 0

    pack_index = _read_json(pack_dir / "index.json")
    assert pack_index["pass4_knowledge_audit_rows"] == 1
    assert (pack_dir / "pass4_knowledge_audit.jsonl").is_file()

    case_rows = _read_jsonl(pack_dir / "case_export" / "case_export.jsonl")
    assert len(case_rows) == 1
    case_row = case_rows[0]
    assert case_row["kind"] == "pass4_run"
    assert case_row["pass4_knowledge_summary"]["enabled"] is True
    assert any(
        (
            "prompt_task4_knowledge.txt" in row["path"]
            or "prompt_task4_pass4_knowledge.txt" in row["path"]
        )
        for row in case_row["pass4_artifacts"]
    )


def test_build_followup_writes_pass4_followup_packet(tmp_path: Path) -> None:
    pass4_bundle = _make_current_pass4_bundle(tmp_path)
    template_path = tmp_path / "pass4_template.json"
    template_result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(pass4_bundle),
            "--out",
            str(template_path),
        ],
    )
    assert template_result.exit_code == 0
    template_payload = _read_json(template_path)

    request_path = tmp_path / "pass4_followup_request.json"
    request_payload = {
        "schema_version": "cf.followup_request.v1",
        "bundle_dir": str(pass4_bundle),
        "bundle_sha256": template_payload["bundle_sha256"],
        "request_id": "followup_pass4_request",
        "request_summary": "Answer one pass4 knowledge follow-up ask.",
        "requester_context": {
            "already_has_upload_bundle_v1": True,
            "prefer_new_local_artifacts_over_bundle_repeats": True,
            "duplicate_bundle_payloads_only_when_needed_for_context": True,
        },
        "default_stage_filters": ["pass4"],
        "asks": [
            {
                "ask_id": "ask_pass4_saltfat",
                "question": "Show the pass4 knowledge evidence for Salt Fat Acid Heat.",
                "outputs": ["case_export", "pass4_knowledge_audit"],
                "selectors": {
                    "include_case_ids": [],
                    "include_recipe_ids": [],
                    "include_line_ranges": [],
                    "include_pass4_source_keys": [PASS4_SOURCE_KEY],
                    "include_pass4_output_subdirs": [],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["pass4"],
                },
            }
        ],
    }
    request_path.write_text(json.dumps(request_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = tmp_path / "followup_pass4"
    result = runner.invoke(
        app,
        [
            "build-followup",
            "--bundle",
            str(pass4_bundle),
            "--request",
            str(request_path),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    ask_dir = out_dir / "asks" / "ask_pass4_saltfat"
    ask_index = _read_json(ask_dir / "index.json")
    assert ask_index["requested_outputs"] == ["case_export", "pass4_knowledge_audit"]
    assert (ask_dir / "case_export" / "case_export.jsonl").is_file()
    assert (ask_dir / "pass4_knowledge_audit.jsonl").is_file()
