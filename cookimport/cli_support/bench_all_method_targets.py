from __future__ import annotations

import importlib
from pathlib import Path

import questionary
import typer

from .bench_all_method_types import AllMethodTarget, AllMethodUnmatchedGold


def _bench_all_method_module():
    return importlib.import_module("cookimport.cli_support.bench_all_method")


def _bench_all_method_attr(name: str):
    return getattr(_bench_all_method_module(), name)


def _prune_empty_dirs(start: Path, *, stop_exclusive: Path | None = None) -> None:
    """Best-effort cleanup of empty directories after moving benchmark artifacts."""
    current = start
    while True:
        if stop_exclusive is not None and current == stop_exclusive:
            break
        try:
            current.rmdir()
        except OSError:
            break
        if current.parent == current:
            break
        current = current.parent


def _display_gold_export_path(path: Path, output_dir: Path) -> str:
    # Keep interactive gold selection readable: prefer the book folder name
    # over the full pulled-from-labelstudio relative path.
    if path.parent.name == "exports" and path.parent.parent.name:
        return path.parent.parent.name
    for root in (output_dir, _bench_all_method_attr("DEFAULT_GOLDEN")):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _display_benchmark_target_name(
    *,
    gold_display: str | None,
    source_file_name: str | None,
) -> str:
    concise_gold_display = str(gold_display or "").strip()
    if concise_gold_display:
        return concise_gold_display
    source_name = str(source_file_name or "").strip()
    if source_name:
        return Path(source_name).stem or source_name
    return "benchmark-target"


def _display_prediction_run_path(path: Path, output_dir: Path) -> str:
    for root in (output_dir, _bench_all_method_attr("DEFAULT_GOLDEN")):
        try:
            return str(path.relative_to(root))
        except ValueError:
            continue
    return str(path)


def _resolve_all_method_targets(
    output_dir: Path,
) -> tuple[list[AllMethodTarget], list[AllMethodUnmatchedGold]]:
    from cookimport.bench.speed_suite import (
        match_gold_exports_to_inputs,
        resolve_repo_path,
    )

    bench_all_method = _bench_all_method_module()
    candidates = bench_all_method._discover_freeform_gold_exports(output_dir)
    matched_rows, unmatched_rows = match_gold_exports_to_inputs(
        candidates,
        input_root=_bench_all_method_attr("DEFAULT_INPUT"),
        gold_root=output_dir,
        importable_files=bench_all_method._list_importable_files(
            _bench_all_method_attr("DEFAULT_INPUT")
        ),
    )

    matched_targets = [
        AllMethodTarget(
            gold_spans_path=resolve_repo_path(
                row.gold_spans_path,
                repo_root=_bench_all_method_attr("REPO_ROOT"),
            ),
            source_file=resolve_repo_path(
                row.source_file,
                repo_root=_bench_all_method_attr("REPO_ROOT"),
            ),
            source_file_name=Path(row.source_file).name,
            gold_display=_display_gold_export_path(
                resolve_repo_path(
                    row.gold_spans_path,
                    repo_root=_bench_all_method_attr("REPO_ROOT"),
                ),
                output_dir,
            ),
        )
        for row in matched_rows
    ]

    unmatched_targets: list[AllMethodUnmatchedGold] = []
    for row in unmatched_rows:
        if not isinstance(row, dict):
            continue
        gold_spans_raw = str(row.get("gold_spans_path") or "").strip()
        if not gold_spans_raw:
            continue
        gold_spans_path = resolve_repo_path(
            gold_spans_raw,
            repo_root=_bench_all_method_attr("REPO_ROOT"),
        )
        source_hint_raw = row.get("source_hint")
        source_hint = (
            str(source_hint_raw).strip() if source_hint_raw is not None else None
        )
        if source_hint == "":
            source_hint = None
        unmatched_targets.append(
            AllMethodUnmatchedGold(
                gold_spans_path=gold_spans_path,
                reason=str(row.get("reason") or "Unmatched gold export."),
                source_hint=source_hint,
                gold_display=str(
                    row.get("gold_display")
                    or _display_gold_export_path(gold_spans_path, output_dir)
                ),
            )
        )

    return matched_targets, unmatched_targets


def _resolve_benchmark_gold_and_source(
    *,
    gold_spans: Path | None,
    source_file: Path | None,
    output_dir: Path,
    allow_cancel: bool = False,
) -> tuple[Path, Path] | None:
    bench_all_method = _bench_all_method_module()

    def _abort(message: str) -> tuple[Path, Path] | None:
        if allow_cancel:
            typer.secho(message, fg=typer.colors.YELLOW)
            return None
        bench_all_method._fail(message)
        return None

    selected_gold = gold_spans
    if selected_gold is None:
        candidates = bench_all_method._discover_freeform_gold_exports(output_dir)
        if not candidates:
            return _abort(
                "No freeform gold exports found. Run `cookimport labelstudio-export` first."
            )
        selected_gold = bench_all_method._menu_select(
            "Select a freeform gold export:",
            menu_help=(
                "Choose the labeled freeform export to benchmark against. "
                "Newest exports are listed first."
            ),
            choices=[
                questionary.Choice(
                    _display_gold_export_path(path, output_dir),
                    value=path,
                )
                for path in candidates[:30]
            ],
        )
        if selected_gold in {None, _bench_all_method_attr("BACK_ACTION")}:
            return _abort("Benchmark cancelled.")
    if isinstance(selected_gold, str):
        selected_gold = Path(selected_gold)
    if not isinstance(selected_gold, Path):
        return _abort("Benchmark cancelled.")
    if not selected_gold.exists():
        return _abort(f"Gold spans file not found: {selected_gold}")

    selected_source = source_file
    inferred_source = None
    if selected_source is None:
        inferred_source = bench_all_method._infer_source_file_from_freeform_gold(
            selected_gold
        )
    if selected_source is None and inferred_source is not None:
        selected_source = inferred_source
    if selected_source is None:
        importable_files = bench_all_method._list_importable_files(
            _bench_all_method_attr("DEFAULT_INPUT")
        )
        if importable_files:
            source_choice = bench_all_method._menu_select(
                "Select source file to benchmark:",
                menu_help=(
                    "Choose the source file used to generate prediction tasks "
                    "for comparison to the selected gold export."
                ),
                choices=[
                    *[questionary.Choice(path.name, value=path) for path in importable_files],
                    questionary.Choice("Enter a custom path", value="custom"),
                ],
            )
            if source_choice in {None, _bench_all_method_attr("BACK_ACTION")}:
                return _abort("Benchmark cancelled.")
            if source_choice == "custom":
                source_path = bench_all_method._prompt_text("Enter source file path:")
                if not source_path:
                    return _abort("Benchmark cancelled.")
                selected_source = Path(source_path)
            else:
                selected_source = source_choice
        else:
            source_path = bench_all_method._prompt_text("Enter source file path:")
            if not source_path:
                return _abort("Benchmark cancelled.")
            selected_source = Path(source_path)
    if not selected_source.exists() or not selected_source.is_file():
        return _abort(f"Source file not found: {selected_source}")
    try:
        bench_all_method._require_importer(selected_source)
    except typer.Exit:
        if allow_cancel:
            return None
        raise

    return selected_gold, selected_source
