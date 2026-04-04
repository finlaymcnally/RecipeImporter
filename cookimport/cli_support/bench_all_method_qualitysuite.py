from __future__ import annotations

import datetime as dt
import json
import shlex
from pathlib import Path
from typing import Any

from cookimport.cli_support import (
    QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
    QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS,
    QUALITYSUITE_AGENT_BRIDGE_SCHEMA_VERSION,
    REPO_ROOT,
)


def _normalize_compare_control_path_prefix(value: str | Path | None) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text == "/":
        return text
    return text.rstrip("/")


def _qualitysuite_compare_control_prefixes_for_path(path: Path) -> list[str]:
    candidate = Path(path).expanduser()
    try:
        candidate = candidate.resolve()
    except OSError:
        candidate = candidate

    prefixes: list[str] = []
    seen: set[str] = set()

    def _add(raw_value: str | Path | None) -> None:
        normalized = _normalize_compare_control_path_prefix(raw_value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        prefixes.append(normalized)

    _add(candidate)
    try:
        _add(candidate.relative_to(REPO_ROOT))
    except ValueError:
        pass
    return prefixes


def _qualitysuite_compare_control_filters_for_prefixes(
    prefixes: list[str],
) -> dict[str, Any]:
    clauses = [
        {"operator": "starts_with", "value": value}
        for value in prefixes
        if str(value or "").strip()
    ]
    filters: dict[str, Any] = {
        "quick_filters": {
            "official_full_golden_only": False,
            "exclude_ai_tests": False,
        },
    }
    if clauses:
        filters["column_filter_global_mode"] = "and"
        filters["column_filters"] = {
            "artifact_dir": {
                "mode": "or",
                "clauses": clauses,
            }
        }
    return filters


def _write_qualitysuite_agent_bridge_readme(
    *,
    bundle_dir: Path,
    index_file: Path,
    requests_file: Path,
    output_root: Path,
    golden_root: Path,
    scope_count: int,
    request_count: int,
) -> None:
    output_root_quoted = shlex.quote(str(output_root))
    golden_root_quoted = shlex.quote(str(golden_root))
    requests_file_quoted = shlex.quote(requests_file.name)
    lines = [
        "# Agent Compare-Control Bridge",
        "",
        "This folder links QualitySuite outputs to Compare & Control insights for AI-agent loops.",
        "",
        f"- Index: `{index_file.name}`",
        f"- Ready requests (JSONL): `{requests_file.name}`",
        f"- Scopes: `{scope_count}`",
        f"- Prepared agent requests: `{request_count}`",
        "",
        "Recommended agent flow:",
        "1. Read `qualitysuite_compare_control_index.json` and pick one scope/outcome insight file.",
        "2. If you need deeper drill-down, run the prepared JSONL requests through `compare-control agent`.",
        "3. Map responses back using each request `meta` payload (`scope_id`, `outcome_field`, `label`).",
        "",
    ]
    if request_count > 0:
        lines.extend(
            [
                "Run the prepared requests:",
                "```bash",
                (
                    "cookimport compare-control agent "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} \\"
                ),
                f"  < {requests_file_quoted} > agent_responses.jsonl",
                "```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No follow-up requests were generated. You can still run direct insights manually:",
                "```bash",
                (
                    "cookimport compare-control run --action insights "
                    f"--output-root {output_root_quoted} "
                    f"--golden-root {golden_root_quoted} "
                    "--outcome-field strict_accuracy"
                ),
                "```",
                "",
            ]
        )
    lines.extend(
        [
            (
                "Tip: Requests include `meta` tags (`scope_id`, `outcome_field`, `label`) "
                "so agents can route responses back to the right QualitySuite scope."
            ),
            "",
        ]
    )
    (bundle_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def _write_qualitysuite_agent_bridge_bundle(
    *,
    bundle_dir: Path,
    bundle_type: str,
    scopes: list[dict[str, Any]],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
    extra_index: dict[str, Any] | None = None,
) -> tuple[Path | None, str | None]:
    from cookimport.analytics import compare_control_engine as engine

    try:
        records = engine.load_dashboard_records(
            output_root=output_root,
            golden_root=golden_root,
            since_days=since_days,
            scan_reports=False,
            scan_benchmark_reports=False,
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"Unable to load compare-control records: {exc}"

    bundle_dir.mkdir(parents=True, exist_ok=True)
    index_payload: dict[str, Any] = {
        "schema_version": QUALITYSUITE_AGENT_BRIDGE_SCHEMA_VERSION,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
        "bundle_type": bundle_type,
        "output_root": str(output_root),
        "golden_root": str(golden_root),
        "since_days": since_days,
        "records_loaded": len(records),
        "outcome_fields": list(QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS),
        "scopes": [],
    }
    if isinstance(extra_index, dict) and extra_index:
        index_payload.update(extra_index)

    request_rows: list[dict[str, Any]] = []

    for scope in scopes:
        scope_id = str(scope.get("scope_id") or "").strip()
        scope_label = str(scope.get("scope_label") or scope_id).strip() or scope_id
        if not scope_id:
            continue
        prefixes = [
            _normalize_compare_control_path_prefix(value)
            for value in (scope.get("path_prefixes") or [])
        ]
        prefixes = [value for value in prefixes if value]
        scope_entry: dict[str, Any] = {
            "scope_id": scope_id,
            "scope_label": scope_label,
            "path_prefixes": prefixes,
            "insights": [],
        }
        if isinstance(scope.get("metadata"), dict):
            scope_entry["metadata"] = dict(scope["metadata"])

        for outcome_field in QUALITYSUITE_AGENT_BRIDGE_OUTCOME_FIELDS:
            query = {
                "outcome_field": outcome_field,
                "filters": _qualitysuite_compare_control_filters_for_prefixes(prefixes),
            }
            file_name = f"{scope_id}__{outcome_field}.json"
            insight_path = bundle_dir / file_name
            try:
                insight_payload = engine.generate_insights(records, query)
                wrapped = engine.success_payload(insight_payload)
                insight_path.write_text(
                    json.dumps(wrapped, indent=2, sort_keys=True),
                    encoding="utf-8",
                )

                candidate_rows = int(insight_payload.get("candidate_rows") or 0)
                compare_field = str(insight_payload.get("compare_field") or "")
                highlights = insight_payload.get("highlights")
                highlight_count = len(highlights) if isinstance(highlights, list) else 0
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "candidate_rows": candidate_rows,
                        "compare_field": compare_field,
                        "highlight_count": highlight_count,
                    }
                )

                suggested_queries = insight_payload.get("suggested_queries")
                if isinstance(suggested_queries, list):
                    for query_index, item in enumerate(suggested_queries, start=1):
                        if not isinstance(item, dict):
                            continue
                        action = str(item.get("action") or "").strip().lower()
                        payload = item.get("payload")
                        if not action or not isinstance(payload, dict):
                            continue
                        request_rows.append(
                            {
                                "id": f"{scope_id}-{outcome_field}-{query_index}",
                                "action": action,
                                "payload": payload,
                                "meta": {
                                    "scope_id": scope_id,
                                    "outcome_field": outcome_field,
                                    "label": str(item.get("label") or "").strip(),
                                },
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                error_payload = engine.error_payload(
                    "qualitysuite_agent_bridge_insight_failed",
                    "Unable to generate insights for scope/outcome.",
                    {
                        "scope_id": scope_id,
                        "outcome_field": outcome_field,
                        "error": str(exc),
                    },
                )
                insight_path.write_text(
                    json.dumps(error_payload, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
                scope_entry["insights"].append(
                    {
                        "outcome_field": outcome_field,
                        "file": file_name,
                        "error": str(exc),
                    }
                )

        index_payload["scopes"].append(scope_entry)

    requests_file = bundle_dir / "agent_requests.jsonl"
    if request_rows:
        requests_file.write_text(
            "\n".join(json.dumps(row, sort_keys=True) for row in request_rows) + "\n",
            encoding="utf-8",
        )
    else:
        requests_file.write_text("", encoding="utf-8")
    index_payload["agent_request_count"] = len(request_rows)
    index_payload["agent_requests_jsonl"] = requests_file.name
    index_file_name = "qualitysuite_compare_control_index.json"
    index_payload["agent_handoff"] = {
        "recommended_entrypoint": index_file_name,
        "recommended_flow": [
            "read_index",
            "inspect_scope_insights",
            "run_agent_requests_jsonl",
        ],
    }

    index_file = bundle_dir / index_file_name
    index_file.write_text(
        json.dumps(index_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_qualitysuite_agent_bridge_readme(
        bundle_dir=bundle_dir,
        index_file=index_file,
        requests_file=requests_file,
        output_root=output_root,
        golden_root=golden_root,
        scope_count=len(index_payload["scopes"]),
        request_count=len(request_rows),
    )
    return bundle_dir, None


def _write_qualitysuite_agent_bridge_bundle_for_run(
    *,
    run_root: Path,
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    summary_payload: dict[str, Any] = {}
    summary_path = run_root / "summary.json"
    if summary_path.exists():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                summary_payload = loaded
        except Exception:
            summary_payload = {}

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "run_overall",
            "scope_label": "Quality run overall",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(run_root),
            "metadata": {
                "run_root": str(run_root),
            },
        }
    ]
    experiments = summary_payload.get("experiments")
    if isinstance(experiments, list):
        for row in experiments:
            if not isinstance(row, dict):
                continue
            experiment_id = str(row.get("id") or "").strip()
            if not experiment_id:
                continue
            experiment_root = run_root / "experiments" / experiment_id
            target_path = experiment_root if experiment_root.exists() else run_root
            scopes.append(
                {
                    "scope_id": f"experiment_{experiment_id}",
                    "scope_label": f"Experiment {experiment_id}",
                    "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                        target_path
                    ),
                    "metadata": {
                        "experiment_id": experiment_id,
                        "status": str(row.get("status") or ""),
                        "run_settings_hash": str(row.get("run_settings_hash") or ""),
                    },
                }
            )

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=run_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_run",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "quality_run_dir": str(run_root),
            "quality_summary_path": str(summary_path),
        },
    )


def _resolve_quality_compare_scope_path(run_dir: Path, experiment_id: str) -> Path:
    experiment_clean = str(experiment_id or "").strip()
    if not experiment_clean:
        return run_dir
    experiment_root = run_dir / "experiments" / experiment_clean
    if experiment_root.exists() and experiment_root.is_dir():
        return experiment_root
    return run_dir


def _write_qualitysuite_agent_bridge_bundle_for_compare(
    *,
    comparison_root: Path,
    comparison_payload: dict[str, Any],
    output_root: Path,
    golden_root: Path,
    since_days: int | None = None,
) -> tuple[Path | None, str | None]:
    baseline_run_dir = Path(
        str(comparison_payload.get("baseline_run_dir") or "").strip()
    ).expanduser()
    candidate_run_dir = Path(
        str(comparison_payload.get("candidate_run_dir") or "").strip()
    ).expanduser()
    baseline_experiment_id = str(
        comparison_payload.get("baseline_experiment_id") or ""
    ).strip()
    candidate_experiment_id = str(
        comparison_payload.get("candidate_experiment_id") or ""
    ).strip()

    baseline_scope_path = _resolve_quality_compare_scope_path(
        baseline_run_dir,
        baseline_experiment_id,
    )
    candidate_scope_path = _resolve_quality_compare_scope_path(
        candidate_run_dir,
        candidate_experiment_id,
    )

    scopes: list[dict[str, Any]] = [
        {
            "scope_id": "baseline",
            "scope_label": f"Baseline ({baseline_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                baseline_scope_path
            ),
            "metadata": {
                "run_dir": str(baseline_run_dir),
                "experiment_id": baseline_experiment_id,
            },
        },
        {
            "scope_id": "candidate",
            "scope_label": f"Candidate ({candidate_experiment_id or 'auto'})",
            "path_prefixes": _qualitysuite_compare_control_prefixes_for_path(
                candidate_scope_path
            ),
            "metadata": {
                "run_dir": str(candidate_run_dir),
                "experiment_id": candidate_experiment_id,
            },
        },
    ]

    return _write_qualitysuite_agent_bridge_bundle(
        bundle_dir=comparison_root / QUALITYSUITE_AGENT_BRIDGE_DIR_NAME,
        bundle_type="quality_compare",
        scopes=scopes,
        output_root=output_root,
        golden_root=golden_root,
        since_days=since_days,
        extra_index={
            "comparison_root": str(comparison_root),
            "comparison_verdict": str(
                (comparison_payload.get("overall") or {}).get("verdict") or ""
            ).upper(),
            "baseline_run_dir": str(baseline_run_dir),
            "candidate_run_dir": str(candidate_run_dir),
            "baseline_experiment_id": baseline_experiment_id,
            "candidate_experiment_id": candidate_experiment_id,
        },
    )
