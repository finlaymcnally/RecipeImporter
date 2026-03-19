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
    / "data/golden/benchmark-vs-golden/2026-03-16_13.34.01/single-offline-benchmark/saltfatacidheatcutdown/upload_bundle_v1"
)
KNOWLEDGE_SAMPLE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-16_13.34.01/single-offline-benchmark/saltfatacidheatcutdown/upload_bundle_v1"
)
KNOWLEDGE_SOURCE_KEY = (
    "789eb99e92fd73a31c559131124ac317fd039c440c1c759ed41d99d85af97f8c"
)
SPARSE_SINGLE_PROFILE_BUNDLE = (
    REPO_ROOT
    / "data/golden/benchmark-vs-golden/2026-03-16_13.34.01/single-offline-benchmark/saltfatacidheatcutdown/upload_bundle_v1"
)
SPARSE_SINGLE_PROFILE_SOURCE_KEY = (
    "789eb99e92fd73a31c559131124ac317fd039c440c1c759ed41d99d85af97f8c"
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


def _make_current_knowledge_bundle(tmp_path: Path, *, enabled: bool = True) -> Path:
    copied_root = tmp_path / "single-profile-benchmark"
    shutil.copytree(KNOWLEDGE_SAMPLE_BUNDLE.parent, copied_root)
    run_dir = copied_root / "line_role_only"
    prompts_dir = run_dir / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    knowledge_prompt_path = prompts_dir / "prompt_nonrecipe_knowledge_review.txt"
    knowledge_prompt_path.write_text("knowledge prompt body\n", encoding="utf-8")
    prompt_samples_path = prompts_dir / "prompt_type_samples_from_full_prompt_log.md"
    prompt_samples_path.write_text(
        "# Prompt samples\n\n## knowledge (Knowledge)\n\ncall_id: `fixture-knowledge`\n",
        encoding="utf-8",
    )
    prediction_run_dir = run_dir / "prediction-run"
    prediction_run_dir.mkdir(parents=True, exist_ok=True)
    prompt_budget_path = prediction_run_dir / "prompt_budget_summary.json"
    prompt_budget_path.write_text(
        json.dumps(
            {
                "schema_version": "prompt_budget_summary.v1",
                "by_stage": {"knowledge": {"call_count": 1, "tokens_total": 1234}},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    knowledge_manifest_path = (
        prediction_run_dir / "raw" / "llm" / "fixture-slug" / "knowledge_manifest.json"
    )
    knowledge_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_manifest_path.write_text(
        json.dumps({"pipeline_id": "recipe.knowledge.compact.v1"}, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    bundle_dir = copied_root / "upload_bundle_v1"
    index_path = bundle_dir / "upload_bundle_index.json"
    index_payload = _read_json(index_path)
    index_payload["source_dir"] = str(copied_root)
    analysis = index_payload.setdefault("analysis", {})
    knowledge_summary = dict(analysis.get("knowledge", {}) or {})
    if isinstance(knowledge_summary, dict):
        knowledge_summary["schema_version"] = "upload_bundle_knowledge.v1"
        rows = knowledge_summary.get("rows")
        if isinstance(rows, list) and rows:
            row = dict(rows[0])
            row["enabled"] = enabled
            row["pipeline"] = "codex-knowledge-shard-v1"
            row["pipeline_id"] = "recipe.knowledge.compact.v1"
            row["llm_knowledge_pipeline"] = "codex-knowledge-shard-v1"
            row["knowledge_call_count"] = 1
            row["knowledge_token_total"] = 1234
            row["prompt_knowledge_status"] = "written"
            row["knowledge_manifest_status"] = "written"
            row["prompt_samples_status"] = "written"
            row["prompt_budget_summary_status"] = "written"
            row["prompt_knowledge_in_bundle"] = True
            row["knowledge_manifest_in_bundle"] = True
            row["prompt_samples_in_bundle"] = True
            row["prompt_budget_summary_in_bundle"] = True
            row["shards_written"] = 1
            row["outputs_parsed"] = 1
            row["snippets_written"] = 1
            row["source_key"] = KNOWLEDGE_SOURCE_KEY
            knowledge_summary["rows"] = [row]
        knowledge_summary["enabled_run_count"] = 1 if enabled else 0
        analysis["knowledge"] = knowledge_summary
    navigation = (index_payload.get("navigation") or {})
    row_locators = (navigation.get("row_locators") or {})
    knowledge_rows = row_locators.get("knowledge_by_run")
    if isinstance(knowledge_rows, list):
        for row in knowledge_rows:
            if not isinstance(row, dict):
                continue
            row["prompt_samples_md"] = {
                "path": "line_role_only/prompts/prompt_type_samples_from_full_prompt_log.md",
                "payload_row": 999001,
            }
            row["prompt_knowledge_txt"] = {
                "path": "line_role_only/prompts/prompt_nonrecipe_knowledge_review.txt",
                "payload_row": 999002,
            }
            row["knowledge_manifest_json"] = {
                "path": "line_role_only/prediction-run/raw/llm/fixture-slug/knowledge_manifest.json",
                "payload_row": 999003,
            }
            row["prompt_budget_summary_json"] = {
                "path": "line_role_only/prediction-run/prompt_budget_summary.json",
                "payload_row": 999004,
            }
    index_payload["navigation"]["row_locators"] = row_locators
    index_path.write_text(
        json.dumps(index_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    payload_path = bundle_dir / "upload_bundle_payload.jsonl"
    payload_rows = _read_jsonl(payload_path)
    payload_rows.extend(
        [
            {
                "path": "line_role_only/prompts/prompt_type_samples_from_full_prompt_log.md",
                "content_type": "text",
                "category": "run_artifact",
                "run_subdir": "line_role_only",
                "bytes": prompt_samples_path.stat().st_size,
                "sha256": "fixture-prompt-samples",
                "content_text": prompt_samples_path.read_text(encoding="utf-8"),
            },
            {
                "path": "line_role_only/prompts/prompt_nonrecipe_knowledge_review.txt",
                "content_type": "text",
                "category": "run_artifact",
                "run_subdir": "line_role_only",
                "bytes": knowledge_prompt_path.stat().st_size,
                "sha256": "fixture-knowledge-prompt",
                "content_text": knowledge_prompt_path.read_text(encoding="utf-8"),
            },
            {
                "path": "line_role_only/prediction-run/raw/llm/fixture-slug/knowledge_manifest.json",
                "content_type": "json",
                "category": "run_artifact",
                "run_subdir": "line_role_only",
                "bytes": knowledge_manifest_path.stat().st_size,
                "sha256": "fixture-knowledge-manifest",
                "content_json": json.loads(knowledge_manifest_path.read_text(encoding="utf-8")),
            },
            {
                "path": "line_role_only/prediction-run/prompt_budget_summary.json",
                "content_type": "json",
                "category": "run_artifact",
                "run_subdir": "line_role_only",
                "bytes": prompt_budget_path.stat().st_size,
                "sha256": "fixture-prompt-budget",
                "content_json": json.loads(prompt_budget_path.read_text(encoding="utf-8")),
            },
        ]
    )
    payload_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in payload_rows),
        encoding="utf-8",
    )
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
    assert payload["asks"][0]["selectors"]["include_case_ids"] == []
    assert "selectors" in payload["asks"][0]["question"].lower()


def test_select_cases_is_byte_stable_for_same_arguments(tmp_path: Path) -> None:
    out_path = tmp_path / "selectors.json"
    line_range = f"{SPARSE_SINGLE_PROFILE_SOURCE_KEY}:628:657"
    args = [
        "select-cases",
        "--bundle",
        str(SAMPLE_BUNDLE),
        "--stage",
        "line_role",
        "--include-line-range",
        line_range,
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
    assert len(selectors) == 1
    selector = selectors[0]
    assert selector["case_id"] == "line_range_628_657"
    assert selector["kind"] == "line_range"
    assert selector["start"] == 628
    assert selector["end"] == 657


def test_select_cases_accepts_legacy_hyphen_line_range_syntax(tmp_path: Path) -> None:
    out_path = tmp_path / "selectors.json"
    result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--stage",
            "line_role",
            "--include-line-range",
            f"{SPARSE_SINGLE_PROFILE_SOURCE_KEY}:628-657",
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    selectors = payload["selectors"]
    assert len(selectors) == 1
    selector = selectors[0]
    assert selector["case_id"] == "line_range_628_657"
    assert selector["kind"] == "line_range"
    assert selector["start"] == 628
    assert selector["end"] == 657


def test_pack_writes_fact_artifacts_for_sample_bundle(tmp_path: Path) -> None:
    selectors_path = tmp_path / "selectors.json"
    line_range = f"{SPARSE_SINGLE_PROFILE_SOURCE_KEY}:628:657"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--stage",
            "line_role",
            "--include-line-range",
            line_range,
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
    assert pack_index["selector_count"] == 1
    assert (pack_dir / "README.md").is_file()
    assert (pack_dir / "structure_report.json").is_file()
    assert (pack_dir / "case_export" / "case_export.jsonl").is_file()
    assert (pack_dir / "line_role_audit.jsonl").is_file()
    assert (pack_dir / "prompt_link_audit.jsonl").is_file()
    assert (pack_dir / "page_context.jsonl").is_file()
    assert (pack_dir / "uncertainty.jsonl").is_file()

    case_rows = _read_jsonl(pack_dir / "case_export" / "case_export.jsonl")
    assert len(case_rows) == 1
    assert case_rows[0]["case_id"] == "line_range_628_657"

    audit_rows = _read_jsonl(pack_dir / "line_role_audit.jsonl")
    assert audit_rows == []

    prompt_rows = _read_jsonl(pack_dir / "prompt_link_audit.jsonl")
    assert all(row["status"] in {"ok", "not_applicable", "broken"} for row in prompt_rows)

    uncertainty_rows = _read_jsonl(pack_dir / "uncertainty.jsonl")
    assert uncertainty_rows == []


def test_structure_report_writes_bundle_wide_structure_split(tmp_path: Path) -> None:
    out_path = tmp_path / "structure_report.json"
    result = runner.invoke(
        app,
        [
            "structure-report",
            "--bundle",
            str(SAMPLE_BUNDLE),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    assert payload["schema_version"] == "benchmark_structure_label_report.v1"
    assert payload["label_groups"]["structure_core"] == [
        "RECIPE_TITLE",
        "INGREDIENT_LINE",
        "INSTRUCTION_LINE",
        "HOWTO_SECTION",
        "YIELD_LINE",
        "TIME_LINE",
    ]
    assert isinstance(payload["slices"]["structure_core"], dict)
    assert isinstance(payload["slices"]["nonrecipe_core"], dict)
    assert isinstance(payload["boundary"], dict)


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
                "ask_id": "ask_line_range",
                "question": "Show the line-role evidence for one explicit window.",
                "outputs": ["case_export", "line_role_audit", "prompt_link_audit"],
                "selectors": {
                    "include_case_ids": [],
                    "include_line_ranges": [f"{SPARSE_SINGLE_PROFILE_SOURCE_KEY}:628:657"],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["line_role"],
                },
            },
            {
                "ask_id": "ask_outside_span",
                "question": "Show context for the explicit line window.",
                "outputs": ["page_context", "uncertainty"],
                "selectors": {
                    "include_case_ids": [],
                    "include_line_ranges": [f"{SPARSE_SINGLE_PROFILE_SOURCE_KEY}:628:657"],
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

    ask1_dir = out_dir / "asks" / "ask_line_range"
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
    assert selectors_payload["selectors"][0]["case_id"] == "line_range_628_657"


def test_build_followup_can_write_structure_report_without_case_exports(tmp_path: Path) -> None:
    request_path = tmp_path / "structure_followup_request.json"
    request_payload = {
        "schema_version": "cf.followup_request.v1",
        "bundle_dir": str(SAMPLE_BUNDLE),
        "request_id": "followup_structure_request",
        "request_summary": "Write the bundle-wide structure split only.",
        "requester_context": {
            "already_has_upload_bundle_v1": True,
        },
        "default_stage_filters": ["line_role"],
        "asks": [
            {
                "ask_id": "ask_structure",
                "question": "Write the bundle-wide structure vs nonrecipe summary.",
                "outputs": ["structure_report"],
                "selectors": {
                    "include_case_ids": [],
                    "include_recipe_ids": [],
                    "include_line_ranges": [],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": [],
                },
            }
        ],
    }
    request_path.write_text(json.dumps(request_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = tmp_path / "followup_structure"
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

    ask_dir = out_dir / "asks" / "ask_structure"
    ask_index = _read_json(ask_dir / "index.json")
    assert ask_index["requested_outputs"] == ["structure_report"]
    assert (ask_dir / "structure_report.json").is_file()
    assert not (ask_dir / "case_export").exists()


def test_request_template_includes_knowledge_example_when_bundle_has_knowledge(
    tmp_path: Path,
) -> None:
    knowledge_bundle = _make_current_knowledge_bundle(tmp_path)
    out_path = tmp_path / "followup_request_knowledge.json"
    result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(knowledge_bundle),
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    knowledge_asks = [
        ask
        for ask in payload["asks"]
        if "knowledge_audit" in ask.get("outputs", [])
    ]
    assert knowledge_asks
    assert knowledge_asks[0]["selectors"]["stage_filters"] == ["knowledge"]
    assert knowledge_asks[0]["selectors"]["include_knowledge_output_subdirs"] == [
        "line_role_only"
    ]


def test_request_template_for_sparse_bundle_builds_without_missing_case_ids(
    tmp_path: Path,
) -> None:
    template_path = tmp_path / "sparse_followup_request.json"
    template_result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(SPARSE_SINGLE_PROFILE_BUNDLE),
            "--out",
            str(template_path),
        ],
    )
    assert template_result.exit_code == 0

    template_payload = _read_json(template_path)
    assert template_payload["asks"][0]["selectors"]["include_case_ids"] == []

    out_dir = tmp_path / "sparse_followup_data"
    result = runner.invoke(
        app,
        [
            "build-followup",
            "--bundle",
            str(SPARSE_SINGLE_PROFILE_BUNDLE),
            "--request",
            str(template_path),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    packet_index = _read_json(out_dir / "index.json")
    assert packet_index["schema_version"] == "cf.followup_packet.v1"
    ask_dir = out_dir / "asks" / "ask_001"
    assert (ask_dir / "case_export" / "index.json").is_file()
    assert (ask_dir / "line_role_audit.jsonl").is_file()
    assert (ask_dir / "prompt_link_audit.jsonl").is_file()
    assert (ask_dir / "page_context.jsonl").is_file()
    assert (ask_dir / "uncertainty.jsonl").is_file()


def test_select_cases_supports_knowledge_source_key(tmp_path: Path) -> None:
    knowledge_bundle = _make_current_knowledge_bundle(tmp_path)
    out_path = tmp_path / "knowledge_selectors.json"
    result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(knowledge_bundle),
            "--stage",
            "knowledge",
            "--include-knowledge-source-key",
            KNOWLEDGE_SOURCE_KEY,
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    selectors = payload["selectors"]
    assert len(selectors) == 1
    row = selectors[0]
    assert row["kind"] == "knowledge_run"
    assert row["source_key"] == KNOWLEDGE_SOURCE_KEY
    assert row["output_subdir"] == "line_role_only"
    assert row["case_id"].startswith("knowledge_")
    assert row["payload_locators"]


def test_select_cases_supports_knowledge_source_key_for_sparse_single_profile_bundle(
    tmp_path: Path,
) -> None:
    sparse_bundle = _make_current_knowledge_bundle(tmp_path, enabled=False)
    out_path = tmp_path / "sparse_knowledge_selectors.json"
    result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(sparse_bundle),
            "--stage",
            "knowledge",
            "--include-knowledge-source-key",
            KNOWLEDGE_SOURCE_KEY,
            "--out",
            str(out_path),
        ],
    )
    assert result.exit_code == 0

    payload = _read_json(out_path)
    selectors = payload["selectors"]
    assert len(selectors) == 1
    row = selectors[0]
    assert row["kind"] == "knowledge_run"
    assert row["source_key"] == KNOWLEDGE_SOURCE_KEY
    assert row["output_subdir"] == "line_role_only"
    assert row["enabled"] is False


def test_audit_knowledge_writes_rows(tmp_path: Path) -> None:
    knowledge_bundle = _make_current_knowledge_bundle(tmp_path)
    selectors_path = tmp_path / "knowledge_selectors.json"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(knowledge_bundle),
            "--stage",
            "knowledge",
            "--include-knowledge-source-key",
            KNOWLEDGE_SOURCE_KEY,
            "--out",
            str(selectors_path),
        ],
    )
    assert select_result.exit_code == 0

    out_path = tmp_path / "knowledge_audit.jsonl"
    result = runner.invoke(
        app,
        [
            "audit-knowledge",
            "--bundle",
            str(knowledge_bundle),
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
    assert row["schema_version"] == "cf.knowledge_audit.v1"
    assert row["book_slug"] == "line_role_only"
    assert row["status"] == "ok"
    assert row["enabled"] is True
    assert row["outputs_parsed"] > 0
    assert "prompt_knowledge_txt" in row["local_artifacts"]
    assert "knowledge_manifest_json" in row["payload_locators"]


def test_pack_includes_knowledge_audit_and_case_export(tmp_path: Path) -> None:
    knowledge_bundle = _make_current_knowledge_bundle(tmp_path)
    selectors_path = tmp_path / "knowledge_selectors.json"
    select_result = runner.invoke(
        app,
        [
            "select-cases",
            "--bundle",
            str(knowledge_bundle),
            "--stage",
            "knowledge",
            "--include-knowledge-source-key",
            KNOWLEDGE_SOURCE_KEY,
            "--out",
            str(selectors_path),
        ],
    )
    assert select_result.exit_code == 0

    pack_dir = tmp_path / "knowledge_pack"
    pack_result = runner.invoke(
        app,
        [
            "pack",
            "--bundle",
            str(knowledge_bundle),
            "--selectors",
            str(selectors_path),
            "--out",
            str(pack_dir),
        ],
    )
    assert pack_result.exit_code == 0

    pack_index = _read_json(pack_dir / "index.json")
    assert pack_index["knowledge_audit_rows"] == 1
    assert (pack_dir / "knowledge_audit.jsonl").is_file()

    case_rows = _read_jsonl(pack_dir / "case_export" / "case_export.jsonl")
    assert len(case_rows) == 1
    case_row = case_rows[0]
    assert case_row["kind"] == "knowledge_run"
    assert case_row["knowledge_summary"]["enabled"] is True
    assert any(
        (
            "prompt_nonrecipe_knowledge_review.txt" in row["path"]
            or "prompt_nonrecipe_knowledge_review_stage.txt" in row["path"]
        )
        for row in case_row["knowledge_artifacts"]
    )


def test_build_followup_writes_knowledge_followup_packet(tmp_path: Path) -> None:
    knowledge_bundle = _make_current_knowledge_bundle(tmp_path)
    template_path = tmp_path / "knowledge_template.json"
    template_result = runner.invoke(
        app,
        [
            "request-template",
            "--bundle",
            str(knowledge_bundle),
            "--out",
            str(template_path),
        ],
    )
    assert template_result.exit_code == 0
    template_payload = _read_json(template_path)

    request_path = tmp_path / "knowledge_followup_request.json"
    request_payload = {
        "schema_version": "cf.followup_request.v1",
        "bundle_dir": str(knowledge_bundle),
        "bundle_sha256": template_payload["bundle_sha256"],
        "request_id": "followup_knowledge_request",
        "request_summary": "Answer one knowledge-stage follow-up ask.",
        "requester_context": {
            "already_has_upload_bundle_v1": True,
            "prefer_new_local_artifacts_over_bundle_repeats": True,
            "duplicate_bundle_payloads_only_when_needed_for_context": True,
        },
        "default_stage_filters": ["knowledge"],
        "asks": [
            {
                "ask_id": "ask_knowledge_saltfat",
                "question": "Show the knowledge-stage evidence for Salt Fat Acid Heat.",
                "outputs": ["case_export", "knowledge_audit"],
                "selectors": {
                    "include_case_ids": [],
                    "include_recipe_ids": [],
                    "include_line_ranges": [],
                    "include_knowledge_source_keys": [KNOWLEDGE_SOURCE_KEY],
                    "include_knowledge_output_subdirs": [],
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["knowledge"],
                },
            }
        ],
    }
    request_path.write_text(json.dumps(request_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir = tmp_path / "followup_knowledge"
    result = runner.invoke(
        app,
        [
            "build-followup",
            "--bundle",
            str(knowledge_bundle),
            "--request",
            str(request_path),
            "--out",
            str(out_dir),
        ],
    )
    assert result.exit_code == 0

    ask_dir = out_dir / "asks" / "ask_knowledge_saltfat"
    ask_index = _read_json(ask_dir / "index.json")
    assert ask_index["requested_outputs"] == ["case_export", "knowledge_audit"]
    assert (ask_dir / "case_export" / "case_export.jsonl").is_file()
    assert (ask_dir / "knowledge_audit.jsonl").is_file()
