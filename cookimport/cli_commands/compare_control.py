from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import typer

from cookimport.cli_support import (
    DEFAULT_GOLDEN,
    DEFAULT_OUTPUT,
    _fail,
    _unwrap_typer_option_default,
)
from cookimport.cli_support.compare_control import (
    _clean_compare_control_string_list,
    _compare_control_dispatch_action,
    _compare_control_ui_state_path_for_dashboard,
    _load_compare_control_dashboard_ui_state_payload,
    _normalize_compare_control_dashboard_chart_layout,
    _normalize_compare_control_dashboard_combined_axis_mode,
    _normalize_compare_control_discovery_prefs_for_dashboard,
    _resolve_compare_control_dashboard_dir,
    _write_compare_control_dashboard_ui_state_payload,
)


def register(app: typer.Typer) -> dict[str, object]:
    @app.command("discovery-preferences")
    def compare_control_discovery_preferences(
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Output root used to resolve the default dashboard location.",
        ),
        dashboard_dir: Path | None = typer.Option(
            None,
            "--dashboard-dir",
            help=(
                "Dashboard directory containing assets/dashboard_ui_state.json. "
                "Defaults to <history root for output>/dashboard."
            ),
        ),
        show_only: bool = typer.Option(
            False,
            "--show-only",
            help="Print current discovery preferences without writing.",
        ),
        reset: bool = typer.Option(
            False,
            "--reset",
            help="Reset discovery preferences to defaults.",
        ),
        exclude_fields: list[str] | None = typer.Option(
            None,
            "--exclude-field",
            help="Discovery card preference: exclude this field (repeatable).",
        ),
        prefer_fields: list[str] | None = typer.Option(
            None,
            "--prefer-field",
            help="Discovery card preference: boost this field (repeatable).",
        ),
        demote_patterns: list[str] | None = typer.Option(
            None,
            "--demote-pattern",
            help="Discovery card preference: demote fields containing this substring (repeatable).",
        ),
        max_cards: int | None = typer.Option(
            None,
            "--max-cards",
            min=1,
            max=40,
            help="Discovery card preference: max cards shown in discover view.",
        ),
    ) -> None:
        """Read or update dashboard Compare & Control discovery-card preferences."""
        output_root = _unwrap_typer_option_default(output_root)
        dashboard_dir = _unwrap_typer_option_default(dashboard_dir)
        show_only = _unwrap_typer_option_default(show_only)
        reset = _unwrap_typer_option_default(reset)
        exclude_fields = _unwrap_typer_option_default(exclude_fields)
        prefer_fields = _unwrap_typer_option_default(prefer_fields)
        demote_patterns = _unwrap_typer_option_default(demote_patterns)
        max_cards = _unwrap_typer_option_default(max_cards)

        resolved_dashboard_dir = _resolve_compare_control_dashboard_dir(
            Path(output_root),
            dashboard_dir,
        )
        ui_state_path = _compare_control_ui_state_path_for_dashboard(resolved_dashboard_dir)
        payload = _load_compare_control_dashboard_ui_state_payload(ui_state_path)

        previous_runs_payload = payload.get("previous_runs")
        if not isinstance(previous_runs_payload, dict):
            previous_runs_payload = {}
        compare_control_payload = previous_runs_payload.get("compare_control")
        if not isinstance(compare_control_payload, dict):
            compare_control_payload = {}

        current_prefs = _normalize_compare_control_discovery_prefs_for_dashboard(
            compare_control_payload.get("discovery_preferences")
        )
        updates_requested = any(
            value is not None
            for value in (
                exclude_fields,
                prefer_fields,
                demote_patterns,
                max_cards,
            )
        )
        should_write = bool(reset or updates_requested) and not bool(show_only)

        if not should_write:
            typer.secho(f"Dashboard UI state: {ui_state_path}", fg=typer.colors.CYAN)
            typer.echo(json.dumps(current_prefs, indent=2, sort_keys=True))
            if not ui_state_path.exists():
                typer.secho(
                    "Note: state file does not exist yet; run `cookimport stats-dashboard` first "
                    "or pass explicit update flags to create it.",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            return

        next_prefs = _normalize_compare_control_discovery_prefs_for_dashboard({})
        if not reset:
            next_prefs = _normalize_compare_control_discovery_prefs_for_dashboard(current_prefs)
        if exclude_fields is not None:
            next_prefs["exclude_fields"] = _clean_compare_control_string_list(exclude_fields)
        if prefer_fields is not None:
            next_prefs["prefer_fields"] = _clean_compare_control_string_list(prefer_fields)
        if demote_patterns is not None:
            next_prefs["demote_patterns"] = _clean_compare_control_string_list(demote_patterns)
        if max_cards is not None:
            next_prefs["max_cards"] = int(max_cards)

        compare_control_payload["discovery_preferences"] = next_prefs
        previous_runs_payload["compare_control"] = compare_control_payload
        payload["previous_runs"] = previous_runs_payload

        _write_compare_control_dashboard_ui_state_payload(ui_state_path, payload)

        typer.secho(f"Updated discovery preferences in {ui_state_path}", fg=typer.colors.GREEN)
        typer.echo(json.dumps(next_prefs, indent=2, sort_keys=True))

    @app.command("dashboard-state")
    def compare_control_dashboard_state(
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Output root used to resolve the default dashboard location.",
        ),
        dashboard_dir: Path | None = typer.Option(
            None,
            "--dashboard-dir",
            help=(
                "Dashboard directory containing assets/dashboard_ui_state.json. "
                "Defaults to <history root for output>/dashboard."
            ),
        ),
        target_set: str = typer.Option(
            "primary",
            "--set",
            help="Which compare/control set to edit: primary or secondary.",
        ),
        show_only: bool = typer.Option(
            False,
            "--show-only",
            help="Print the current compare/control dashboard state without writing.",
        ),
        reset: bool = typer.Option(
            False,
            "--reset",
            help="Reset the targeted set to default state before applying updates.",
        ),
        outcome_field: str | None = typer.Option(
            None,
            "--outcome-field",
            help="Visible Compare & Control outcome field.",
        ),
        compare_field: str | None = typer.Option(
            None,
            "--compare-field",
            help="Visible Compare & Control compare field.",
        ),
        view_mode: str | None = typer.Option(
            None,
            "--view",
            help="Visible Compare & Control view: discover, raw, or controlled.",
        ),
        hold_constant_fields: list[str] | None = typer.Option(
            None,
            "--hold-constant-field",
            help="Visible hold-constant field (repeatable). Replaces the target set list.",
        ),
        split_field: str | None = typer.Option(
            None,
            "--split-field",
            help="Visible Compare & Control split field.",
        ),
        selected_groups: list[str] | None = typer.Option(
            None,
            "--selected-group",
            help="Visible categorical group subset (repeatable). Replaces the target set list.",
        ),
        enable_second_set: bool = typer.Option(
            False,
            "--enable-second-set",
            help="Enable Set 2 in the visible dashboard layout.",
        ),
        disable_second_set: bool = typer.Option(
            False,
            "--disable-second-set",
            help="Disable Set 2 in the visible dashboard layout.",
        ),
        chart_layout: str | None = typer.Option(
            None,
            "--chart-layout",
            help="Visible dual-set chart layout: stacked, side_by_side, or combined.",
        ),
        combined_axis_mode: str | None = typer.Option(
            None,
            "--combined-axis-mode",
            help="Visible combined-chart Y-axis mode: single or dual.",
        ),
    ) -> None:
        """Read or update the live Compare & Control state used by the dashboard UI."""
        output_root = _unwrap_typer_option_default(output_root)
        dashboard_dir = _unwrap_typer_option_default(dashboard_dir)
        target_set = _unwrap_typer_option_default(target_set)
        show_only = _unwrap_typer_option_default(show_only)
        reset = _unwrap_typer_option_default(reset)
        outcome_field = _unwrap_typer_option_default(outcome_field)
        compare_field = _unwrap_typer_option_default(compare_field)
        view_mode = _unwrap_typer_option_default(view_mode)
        hold_constant_fields = _unwrap_typer_option_default(hold_constant_fields)
        split_field = _unwrap_typer_option_default(split_field)
        selected_groups = _unwrap_typer_option_default(selected_groups)
        enable_second_set = _unwrap_typer_option_default(enable_second_set)
        disable_second_set = _unwrap_typer_option_default(disable_second_set)
        chart_layout = _unwrap_typer_option_default(chart_layout)
        combined_axis_mode = _unwrap_typer_option_default(combined_axis_mode)

        set_key = str(target_set or "primary").strip().lower()
        if set_key not in {"primary", "secondary"}:
            _fail("--set must be either 'primary' or 'secondary'.")
        if enable_second_set and disable_second_set:
            _fail("Choose only one of --enable-second-set or --disable-second-set.")

        resolved_dashboard_dir = _resolve_compare_control_dashboard_dir(
            Path(output_root),
            dashboard_dir,
        )
        ui_state_path = _compare_control_ui_state_path_for_dashboard(resolved_dashboard_dir)
        payload = _load_compare_control_dashboard_ui_state_payload(ui_state_path)

        previous_runs_payload = payload.get("previous_runs")
        if not isinstance(previous_runs_payload, dict):
            previous_runs_payload = {}
        compare_control_payload = previous_runs_payload.get("compare_control")
        if not isinstance(compare_control_payload, dict):
            compare_control_payload = {}

        current_state = (
            compare_control_payload.get("second_set")
            if set_key == "secondary"
            else compare_control_payload
        )
        if not isinstance(current_state, dict):
            current_state = {}

        updates_requested = any(
            value is not None
            for value in (
                outcome_field,
                compare_field,
                view_mode,
                hold_constant_fields,
                split_field,
                selected_groups,
                chart_layout,
                combined_axis_mode,
            )
        ) or enable_second_set or disable_second_set
        should_write = bool(reset or updates_requested) and not bool(show_only)

        if not should_write:
            shown_state = dict(current_state)
            if set_key == "secondary":
                shown_state["second_set_enabled"] = bool(
                    compare_control_payload.get("second_set_enabled")
                )
            shown_state["chart_layout"] = _normalize_compare_control_dashboard_chart_layout(
                compare_control_payload.get("chart_layout")
            )
            shown_state["combined_axis_mode"] = (
                _normalize_compare_control_dashboard_combined_axis_mode(
                    compare_control_payload.get("combined_axis_mode")
                )
            )
            typer.secho(f"Dashboard UI state: {ui_state_path}", fg=typer.colors.CYAN)
            typer.echo(json.dumps(shown_state, indent=2, sort_keys=True))
            if not ui_state_path.exists():
                typer.secho(
                    "Note: state file does not exist yet; run `cookimport stats-dashboard` first "
                    "or pass explicit update flags to create it.",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            return

        next_state: dict[str, Any] = {} if reset else dict(current_state)
        if outcome_field is not None:
            next_state["outcome_field"] = str(outcome_field or "").strip()
        if compare_field is not None:
            next_state["compare_field"] = str(compare_field or "").strip()
        if view_mode is not None:
            next_state["view_mode"] = str(view_mode or "").strip().lower()
        if hold_constant_fields is not None:
            next_state["hold_constant_fields"] = _clean_compare_control_string_list(
                hold_constant_fields
            )
        if split_field is not None:
            next_state["split_field"] = str(split_field or "").strip()
        if selected_groups is not None:
            next_state["selected_groups"] = _clean_compare_control_string_list(selected_groups)
        if (
            compare_field is not None
            and view_mode is None
            and str(next_state.get("compare_field") or "").strip()
            and str(next_state.get("view_mode") or "").strip().lower() in {"", "discover"}
        ):
            next_state["view_mode"] = "raw"

        next_state["discovery_preferences"] = (
            _normalize_compare_control_discovery_prefs_for_dashboard(
                next_state.get("discovery_preferences")
            )
        )

        if set_key == "secondary":
            compare_control_payload["second_set"] = next_state
            if enable_second_set or compare_field is not None or outcome_field is not None:
                compare_control_payload["second_set_enabled"] = True
        else:
            compare_control_payload.update(next_state)

        if enable_second_set:
            compare_control_payload["second_set_enabled"] = True
        if disable_second_set:
            compare_control_payload["second_set_enabled"] = False
        if chart_layout is not None:
            compare_control_payload["chart_layout"] = (
                _normalize_compare_control_dashboard_chart_layout(chart_layout)
            )
        if combined_axis_mode is not None:
            compare_control_payload["combined_axis_mode"] = (
                _normalize_compare_control_dashboard_combined_axis_mode(combined_axis_mode)
            )

        previous_runs_payload["compare_control"] = compare_control_payload
        payload["previous_runs"] = previous_runs_payload
        _write_compare_control_dashboard_ui_state_payload(ui_state_path, payload)

        result_state = (
            compare_control_payload.get("second_set")
            if set_key == "secondary"
            else compare_control_payload
        )
        shown_state = dict(result_state if isinstance(result_state, dict) else {})
        shown_state["second_set_enabled"] = bool(compare_control_payload.get("second_set_enabled"))
        shown_state["chart_layout"] = _normalize_compare_control_dashboard_chart_layout(
            compare_control_payload.get("chart_layout")
        )
        shown_state["combined_axis_mode"] = (
            _normalize_compare_control_dashboard_combined_axis_mode(
                compare_control_payload.get("combined_axis_mode")
            )
        )
        typer.secho(
            f"Updated compare/control dashboard state in {ui_state_path}",
            fg=typer.colors.GREEN,
        )
        typer.echo(json.dumps(shown_state, indent=2, sort_keys=True))

    @app.command("run")
    def compare_control_run(
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Root output folder for staged imports.",
        ),
        golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--golden-root",
            help="Root folder for golden-set / benchmark data.",
        ),
        since_days: int | None = typer.Option(
            None,
            "--since-days",
            help="Only include runs from the last N days.",
        ),
        scan_reports: bool = typer.Option(
            False,
            "--scan-reports",
            help="Force scanning individual *.excel_import_report.json files.",
        ),
        scan_benchmark_reports: bool = typer.Option(
            False,
            "--scan-benchmark-reports",
            help="Force recursive benchmark eval_report.json scans under --golden-root.",
        ),
        action: str = typer.Option(
            "analyze",
            "--action",
            help=(
                "Action to run: analyze, discover, fields, suggest_hold_constants, "
                "suggest_splits, insights, subset_filter_patch, ping."
            ),
        ),
        query_file: Path | None = typer.Option(
            None,
            "--query-file",
            help="JSON file containing either a payload object or {action, payload}.",
        ),
        view_mode: str = typer.Option(
            "discover",
            "--view",
            help="Analysis view mode for analyze/discover actions.",
        ),
        outcome_field: str | None = typer.Option(
            None,
            "--outcome-field",
            help="Numeric outcome field for compare/control analysis.",
        ),
        compare_field: str | None = typer.Option(
            None,
            "--compare-field",
            help="Compare-by field for compare/control analysis.",
        ),
        hold_constant_fields: list[str] | None = typer.Option(
            None,
            "--hold-constant-field",
            help="Field to hold constant (repeatable).",
        ),
        split_field: str | None = typer.Option(
            None,
            "--split-field",
            help="Optional split-by field.",
        ),
        selected_groups: list[str] | None = typer.Option(
            None,
            "--selected-group",
            help="Group key used by subset_filter_patch (repeatable).",
        ),
        filters_json: str | None = typer.Option(
            None,
            "--filters-json",
            help="JSON object for filters payload (quick_filters + column_filters).",
        ),
        discover_exclude_fields: list[str] | None = typer.Option(
            None,
            "--discover-exclude-field",
            help="Discovery preference: exclude this field from discovery cards (repeatable).",
        ),
        discover_prefer_fields: list[str] | None = typer.Option(
            None,
            "--discover-prefer-field",
            help="Discovery preference: boost this field in discovery cards (repeatable).",
        ),
        discover_demote_patterns: list[str] | None = typer.Option(
            None,
            "--discover-demote-pattern",
            help=(
                "Discovery preference: demote field names containing this substring "
                "(repeatable, case-insensitive)."
            ),
        ),
        discover_max_cards: int | None = typer.Option(
            None,
            "--discover-max-cards",
            min=1,
            max=40,
            help="Discovery preference: max number of discovery cards to return.",
        ),
    ) -> None:
        """Run backend Compare & Control once and print structured JSON."""
        output_root = _unwrap_typer_option_default(output_root)
        golden_root = _unwrap_typer_option_default(golden_root)
        since_days = _unwrap_typer_option_default(since_days)
        scan_reports = _unwrap_typer_option_default(scan_reports)
        scan_benchmark_reports = _unwrap_typer_option_default(scan_benchmark_reports)
        action = _unwrap_typer_option_default(action)
        query_file = _unwrap_typer_option_default(query_file)
        view_mode = _unwrap_typer_option_default(view_mode)
        outcome_field = _unwrap_typer_option_default(outcome_field)
        compare_field = _unwrap_typer_option_default(compare_field)
        hold_constant_fields = _unwrap_typer_option_default(hold_constant_fields)
        split_field = _unwrap_typer_option_default(split_field)
        selected_groups = _unwrap_typer_option_default(selected_groups)
        filters_json = _unwrap_typer_option_default(filters_json)
        discover_exclude_fields = _unwrap_typer_option_default(discover_exclude_fields)
        discover_prefer_fields = _unwrap_typer_option_default(discover_prefer_fields)
        discover_demote_patterns = _unwrap_typer_option_default(discover_demote_patterns)
        discover_max_cards = _unwrap_typer_option_default(discover_max_cards)

        from cookimport.analytics import compare_control_engine as engine

        resolved_action = str(action or "analyze").strip().lower()
        payload: dict[str, Any]
        if query_file is not None:
            try:
                query_payload = json.loads(query_file.read_text(encoding="utf-8"))
            except OSError as exc:
                _fail(f"Unable to read query file: {exc}")
            except json.JSONDecodeError as exc:
                _fail(f"Invalid JSON in query file: {exc}")
            if not isinstance(query_payload, dict):
                _fail("Query file must contain a JSON object.")
            if isinstance(query_payload.get("action"), str):
                resolved_action = str(query_payload.get("action") or "").strip().lower()
                nested_payload = query_payload.get("payload")
                if not isinstance(nested_payload, dict):
                    _fail("Query file action payload must be a JSON object.")
                payload = dict(nested_payload)
            else:
                payload = dict(query_payload)
        else:
            payload = {
                "view_mode": str(view_mode or "discover").strip().lower() or "discover",
                "outcome_field": str(outcome_field or "").strip(),
                "compare_field": str(compare_field or "").strip(),
                "hold_constant_fields": [
                    str(value).strip()
                    for value in (hold_constant_fields or [])
                    if str(value).strip()
                ],
                "split_field": str(split_field or "").strip(),
                "selected_groups": [
                    str(value).strip()
                    for value in (selected_groups or [])
                    if str(value).strip()
                ],
            }
            if filters_json:
                try:
                    parsed_filters = json.loads(filters_json)
                except json.JSONDecodeError as exc:
                    _fail(f"Invalid JSON passed to --filters-json: {exc}")
                if not isinstance(parsed_filters, dict):
                    _fail("--filters-json must decode to a JSON object.")
                payload["filters"] = parsed_filters
            discovery_preferences: dict[str, Any] = {}
            if discover_exclude_fields:
                discovery_preferences["exclude_fields"] = [
                    str(value).strip()
                    for value in discover_exclude_fields
                    if str(value).strip()
                ]
            if discover_prefer_fields:
                discovery_preferences["prefer_fields"] = [
                    str(value).strip()
                    for value in discover_prefer_fields
                    if str(value).strip()
                ]
            if discover_demote_patterns:
                discovery_preferences["demote_patterns"] = [
                    str(value).strip()
                    for value in discover_demote_patterns
                    if str(value).strip()
                ]
            if discover_max_cards is not None:
                discovery_preferences["max_cards"] = int(discover_max_cards)
            if discovery_preferences:
                payload["discovery_preferences"] = discovery_preferences

        if resolved_action == "discover":
            payload["view_mode"] = "discover"

        response: dict[str, Any]
        try:
            records = engine.load_dashboard_records(
                output_root=output_root,
                golden_root=golden_root,
                since_days=since_days,
                scan_reports=scan_reports,
                scan_benchmark_reports=scan_benchmark_reports,
            )
            result = _compare_control_dispatch_action(records, resolved_action, payload)
            response = engine.success_payload(result)
        except engine.CompareControlError as exc:
            response = engine.error_payload(exc.code, exc.message, exc.details)
        except Exception as exc:  # pragma: no cover - defensive fallback
            response = engine.error_payload(
                "internal_error",
                "Unhandled compare-control run error.",
                {"error": str(exc)},
            )

        typer.echo(json.dumps(response, indent=2, sort_keys=True))

    @app.command("agent")
    def compare_control_agent(
        output_root: Path = typer.Option(
            DEFAULT_OUTPUT,
            "--output-root",
            help="Root output folder for staged imports.",
        ),
        golden_root: Path = typer.Option(
            DEFAULT_GOLDEN,
            "--golden-root",
            help="Root folder for golden-set / benchmark data.",
        ),
        since_days: int | None = typer.Option(
            None,
            "--since-days",
            help="Only include runs from the last N days.",
        ),
        scan_reports: bool = typer.Option(
            False,
            "--scan-reports",
            help="Force scanning individual *.excel_import_report.json files.",
        ),
        scan_benchmark_reports: bool = typer.Option(
            False,
            "--scan-benchmark-reports",
            help="Force recursive benchmark eval_report.json scans under --golden-root.",
        ),
    ) -> None:
        """Run a persistent JSONL Compare & Control loop on stdin/stdout."""
        output_root = _unwrap_typer_option_default(output_root)
        golden_root = _unwrap_typer_option_default(golden_root)
        since_days = _unwrap_typer_option_default(since_days)
        scan_reports = _unwrap_typer_option_default(scan_reports)
        scan_benchmark_reports = _unwrap_typer_option_default(scan_benchmark_reports)

        from cookimport.analytics import compare_control_engine as engine

        state: dict[str, Any] = {
            "output_root": output_root,
            "golden_root": golden_root,
            "since_days": since_days,
            "scan_reports": bool(scan_reports),
            "scan_benchmark_reports": bool(scan_benchmark_reports),
            "records": [],
        }

        def _reload_state_records() -> dict[str, Any]:
            state["records"] = engine.load_dashboard_records(
                output_root=state["output_root"],
                golden_root=state["golden_root"],
                since_days=state["since_days"],
                scan_reports=state["scan_reports"],
                scan_benchmark_reports=state["scan_benchmark_reports"],
            )
            return {
                "loaded_rows": len(state["records"]),
                "output_root": str(state["output_root"]),
                "golden_root": str(state["golden_root"]),
                "since_days": state["since_days"],
                "scan_reports": state["scan_reports"],
                "scan_benchmark_reports": state["scan_benchmark_reports"],
            }

        try:
            _reload_state_records()
        except Exception as exc:  # pragma: no cover - defensive fallback
            bootstrap_response = engine.error_payload(
                "initial_load_failed",
                "Unable to initialize compare-control agent state.",
                {"error": str(exc)},
            )
            typer.echo(json.dumps(bootstrap_response, sort_keys=True))

        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            request_id: Any = None
            response: dict[str, Any]
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise engine.CompareControlError(
                        "invalid_request",
                        "Request line must decode to a JSON object.",
                    )
                request_id = request.get("id")
                action = str(request.get("action") or "").strip().lower()
                if not action:
                    raise engine.CompareControlError(
                        "missing_action",
                        "Request must include an action string.",
                    )
                payload_raw = request.get("payload")
                payload = payload_raw if isinstance(payload_raw, dict) else {}

                if action == "load":
                    if "output_root" in payload:
                        state["output_root"] = Path(str(payload.get("output_root") or "")).expanduser()
                    if "golden_root" in payload:
                        state["golden_root"] = Path(str(payload.get("golden_root") or "")).expanduser()
                    if "since_days" in payload:
                        raw_since_days = payload.get("since_days")
                        if raw_since_days in (None, "", "null"):
                            state["since_days"] = None
                        else:
                            try:
                                state["since_days"] = int(raw_since_days)
                            except (TypeError, ValueError) as exc:
                                raise engine.CompareControlError(
                                    "invalid_since_days",
                                    "since_days must be an integer or null.",
                                    {"since_days": raw_since_days},
                                ) from exc
                    if "scan_reports" in payload:
                        state["scan_reports"] = bool(payload.get("scan_reports"))
                    if "scan_benchmark_reports" in payload:
                        state["scan_benchmark_reports"] = bool(payload.get("scan_benchmark_reports"))
                    response = engine.success_payload(_reload_state_records())
                elif action == "reset":
                    response = engine.success_payload(_reload_state_records())
                else:
                    result = _compare_control_dispatch_action(
                        state["records"],
                        action,
                        payload,
                    )
                    response = engine.success_payload(result)
            except json.JSONDecodeError as exc:
                response = engine.error_payload(
                    "invalid_json",
                    "Request line is not valid JSON.",
                    {"error": str(exc)},
                )
            except engine.CompareControlError as exc:
                response = engine.error_payload(exc.code, exc.message, exc.details)
            except Exception as exc:  # pragma: no cover - defensive fallback
                response = engine.error_payload(
                    "internal_error",
                    "Unhandled compare-control agent error.",
                    {"error": str(exc)},
                )

            if request_id is not None:
                response["id"] = request_id
            typer.echo(json.dumps(response, sort_keys=True))

    exports = {
        "compare_control_discovery_preferences": compare_control_discovery_preferences,
        "compare_control_dashboard_state": compare_control_dashboard_state,
        "compare_control_run": compare_control_run,
        "compare_control_agent": compare_control_agent,
    }
    globals().update(exports)
    return exports
