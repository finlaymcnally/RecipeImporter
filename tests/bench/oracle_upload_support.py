from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cookimport.cli as cli
import cookimport.cli_commands.bench as bench_cli
import cookimport.cli_support as cli_support
import cookimport.cli_support.bench_oracle as bench_oracle_support
from cookimport.bench import oracle_upload


runner = CliRunner()
INSTANT_LANE = oracle_upload.ORACLE_MODEL_LANE_INSTANT
INSTANT_MODEL = "instant-browser-model"


@pytest.fixture(autouse=True)
def _speed_up_background_oracle_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oracle_upload, "ORACLE_BACKGROUND_SESSION_POLL_SECONDS", 0.01)
    monkeypatch.setattr(oracle_upload, "ORACLE_BACKGROUND_SESSION_POLL_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(oracle_upload, "_detect_oracle_version", lambda: "0.8.6-test")
    monkeypatch.setenv("ORACLE_INSTANT_MODEL", INSTANT_MODEL)


def _make_bundle(
    bundle_dir: Path,
    *,
    run_count: int = 1,
    pair_count: int = 0,
    changed_lines_total: int = 0,
) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    source_root = bundle_dir.parent
    for review_profile in ("quality", "token"):
        review_dir = _review_dir(bundle_dir, review_profile=review_profile)
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "overview.md").write_text(
            "\n".join(
                [
                    f"# {review_profile.title()} Review Packet",
                    "",
                    f"- benchmark root: `{source_root}`",
                    f"- run_count = {run_count}",
                    f"- pair_count = {pair_count}",
                    f"- changed_lines_total = {changed_lines_total}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (review_dir / "index.json").write_text(
            json.dumps(
                {
                    "review_profile": review_profile,
                    "topline": {
                        "run_count": run_count,
                        "pair_count": pair_count,
                        "changed_lines_total": changed_lines_total,
                    },
                    "self_check": {
                        "run_count_verified": True,
                        "pair_count_verified": True,
                        "changed_lines_verified": True,
                        "topline_consistent": True,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (review_dir / "payload.json").write_text(
            json.dumps(
                {
                    "schema_version": "upload_bundle.review_payload.v1",
                    "review_profile": review_profile,
                    "row_count": 1,
                    "rows": [{"path": "row", "payload": "benchmark payload"}],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    _write_profile_bundle_context(bundle_dir)
    _write_profile_payload_rows(bundle_dir)
    return bundle_dir


def _review_dir(bundle_dir: Path, *, review_profile: str = "quality") -> Path:
    return bundle_dir / review_profile


def _review_file(bundle_dir: Path, file_name: str, *, review_profile: str = "quality") -> Path:
    return _review_dir(bundle_dir, review_profile=review_profile) / file_name


def _runs_dir(bundle_dir: Path) -> Path:
    return oracle_upload.oracle_upload_runs_dir(bundle_dir)


def _write_browser_safe_row_locator_index(bundle_dir: Path) -> None:
    index_path = _review_file(bundle_dir, "index.json")
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload["navigation"] = {
        "row_locators": {
            "root_files": {
                "comparison_summary_json": {
                    "path": "codex_vs_vanilla_comparison.json",
                    "payload_row": 2,
                },
                "triage_packet_jsonl": {
                    "path": "_upload_bundle_derived/root/01_recipe_triage.packet.jsonl",
                    "payload_row": 5,
                },
            },
            "starter_pack": {
                "casebook_md": {
                    "path": "_upload_bundle_derived/starter_pack_v1/07_casebook.md",
                    "payload_row": 7,
                },
            },
            "per_run_summaries": [
                {
                    "run_id": "codexfarm",
                    "summary": {
                        "path": "codexfarm/need_to_know_summary.json",
                        "payload_row": 9,
                    },
                }
            ],
        }
    }
    index_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_profile_bundle_context(bundle_dir: Path) -> None:
    for review_profile in ("quality", "token"):
        index_path = _review_file(bundle_dir, "index.json", review_profile=review_profile)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        payload["topline"]["active_recipe_span_breakout"] = {
            "outside_share_of_scored_lines": 0.839018,
        }
        payload["analysis"] = {
            "top_confusion_deltas": [
                {
                    "gold_label": "KNOWLEDGE",
                    "pred_label": "OTHER",
                }
            ],
            "structure_label_report": {
                "boundary": {
                    "codex_exact_ratio_avg": 1.0,
                },
                "slices": {
                    "structure_core": {
                        "codex_f1_avg": 0.777012,
                    },
                    "nonrecipe_core": {
                        "codex_f1_avg": 0.578081,
                    },
                },
            },
            "call_inventory_runtime": {
                "summary": {
                    "total_tokens": 33699633,
                    "nonrecipe_finalize_token_share": 0.8535,
                }
            },
        }
        index_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    comparison_path = bundle_dir.parent / "codex_vs_vanilla_comparison.json"
    comparison_path.write_text(
        json.dumps(
            {
                "metrics": {
                    "codexfarm": {
                        "strict_accuracy": 0.64734,
                        "macro_f1_excluding_other": 0.777327,
                    }
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_budget_path = bundle_dir.parent / "codexfarm" / "prompt_budget_summary.json"
    prompt_budget_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_budget_path.write_text(
        json.dumps(
            {
                "by_stage": {
                    "knowledge": {
                        "tokens_total": 28762251,
                        "wrapper_overhead_tokens": 14637956,
                    },
                    "line_role": {
                        "tokens_total": 2952847,
                    },
                    "recipe_correction": {
                        "tokens_total": 1984535,
                    },
                }
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_profile_payload_rows(bundle_dir: Path) -> None:
    selected_paths = set()
    for profile in oracle_upload.ORACLE_BENCHMARK_REVIEW_PROFILES:
        selected_paths.update(profile.payload_paths)
    rows = []
    for path in sorted(selected_paths):
        rows.append(
            json.dumps(
                {
                    "path": path,
                    "payload": f"payload for {path}",
                }
            )
            + "\n"
        )
    rows.append(
        json.dumps(
            {
                "path": "heavy/unselected.json",
                "payload": "x" * 20000,
            }
        )
        + "\n"
    )
    payload_packet = {
        "schema_version": "upload_bundle.review_payload.v1",
        "row_count": len(rows),
        "rows": [json.loads(row) for row in rows],
    }
    for review_profile in ("quality", "token"):
        review_payload_packet = dict(payload_packet)
        review_payload_packet["review_profile"] = review_profile
        _review_file(bundle_dir, "payload.json", review_profile=review_profile).write_text(
            json.dumps(review_payload_packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
