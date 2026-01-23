from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Iterable

import questionary
import typer

from cookimport.core.mapping_io import load_mapping_config, save_mapping_config
from cookimport.core.models import ConversionReport, MappingConfig
from cookimport.plugins import registry
from cookimport.plugins import excel, text, epub, pdf  # noqa: F401
from cookimport.staging.writer import write_draft_outputs, write_intermediate_outputs, write_report

app = typer.Typer(add_completion=False, invoke_without_command=True)

DEFAULT_INPUT = Path(__file__).parent.parent / "data" / "input"
DEFAULT_OUTPUT = Path(__file__).parent.parent / "data" / "output"


def _list_importable_files(folder: Path) -> list[Path]:
    """List files in a folder that have a valid importer."""
    if not folder.exists():
        return []
    files = []
    for f in folder.glob("*"):
        if f.is_file() and not f.name.startswith("."):
            _, score = registry.best_importer_for_path(f)
            if score > 0:
                files.append(f)
    return sorted(files)


def _interactive_mode() -> None:
    """Run the interactive guided flow."""
    typer.secho("\n  Recipe Import Tool\n", fg=typer.colors.CYAN, bold=True)

    input_folder = DEFAULT_INPUT
    output_folder = DEFAULT_OUTPUT

    # Scan for importable files first to know what context to show
    importable_files = _list_importable_files(input_folder)

    choices = []
    if importable_files:
        choices.append(questionary.Choice("Import files from data/input", value="import"))
    choices.append(questionary.Choice("Inspect a single file (preview layout)", value="inspect"))

    action = questionary.select(
        "What would you like to do?",
        choices=choices,
    ).ask()

    if action is None:
        raise typer.Exit(0)

    if action == "inspect":
        if not importable_files:
            typer.secho(
                f"\nNo supported files found in {input_folder}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        file_choices = [
            questionary.Choice(f.name, value=f) for f in importable_files
        ]
        selected_file = questionary.select(
            "Select a file to inspect:",
            choices=file_choices,
        ).ask()

        if selected_file is None:
            raise typer.Exit(0)

        write_map = questionary.confirm(
            "Write a mapping file? (useful for customizing column mappings)",
            default=True,
        ).ask()

        if write_map is None:
            raise typer.Exit(0)

        typer.echo()
        inspect(path=selected_file, out=output_folder, write_mapping=write_map)

    elif action == "import":
        if not importable_files:
            # Should be unreachable given the check above, but safe to keep
            typer.secho(
                f"\nNo supported files found in {input_folder}",
                fg=typer.colors.YELLOW,
            )
            raise typer.Exit(1)

        typer.secho(f"\nFound {len(importable_files)} importable file(s) in {input_folder}", fg=typer.colors.GREEN)

        selection = questionary.select(
            "Which file(s) would you like to import?",
            choices=[
                questionary.Choice("Import All", value="all"),
                *[questionary.Choice(f.name, value=f) for f in importable_files]
            ]
        ).ask()

        if selection is None:
            raise typer.Exit(0)

        typer.echo()
        
        if selection == "all":
            stage(path=input_folder, out=output_folder, mapping=None)
        else:
            stage(path=selection, out=output_folder, mapping=None)

        typer.secho(f"\nOutputs written to: {output_folder}", fg=typer.colors.CYAN)


@app.callback()
def main(ctx: typer.Context) -> None:
    """Recipe Import - Convert Excel files to RecipeSage JSON-LD format."""
    if ctx.invoked_subcommand is None:
        _interactive_mode()


def _fail(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _require_importer(path: Path):
    importer, score = registry.best_importer_for_path(path)
    if importer is None or score <= 0:
        _fail("No importer available for this path.")
    return importer


def _iter_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith("."):
            yield path


def _resolve_mapping_path(workbook: Path, out: Path, override: Path | None) -> Path | None:
    if override is not None:
        return override
    sidecar_yaml = workbook.with_suffix(".mapping.yaml")
    sidecar_json = workbook.with_suffix(".mapping.json")
    if sidecar_yaml.exists():
        return sidecar_yaml
    if sidecar_json.exists():
        return sidecar_json
    staged = out / "mappings" / f"{workbook.stem}.mapping.yaml"
    if staged.exists():
        return staged
    return None


def _slugify_name(name: str) -> str:
    """Convert a name to a filesystem-safe slug."""
    import re
    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"


@app.command()
def stage(
    path: Path = typer.Argument(..., help="File or folder containing source files."),
    out: Path = typer.Option(Path("staging"), "--out", help="Output folder."),
    mapping: Path | None = typer.Option(None, "--mapping", help="Mapping file path."),
) -> None:
    """Stage recipes from a source file or folder.

    Outputs are organized as:
      {out}/{timestamp}/intermediate drafts/{filename}/  - RecipeSage JSON-LD
      {out}/{timestamp}/final drafts/{filename}/         - RecipeDraftV1 format
      {out}/{timestamp}/reports/                         - Conversion reports
    """
    if not path.exists():
        _fail(f"Path not found: {path}")
    if mapping is not None and not mapping.exists():
        _fail(f"Mapping file not found: {mapping}")

    imported = 0
    errors: list[str] = []
    mapping_override: MappingConfig | None = None
    if mapping is not None:
        mapping_override = load_mapping_config(mapping)

    # Create timestamped output folder for this run
    timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M%S")
    out = out / timestamp
    out.mkdir(parents=True, exist_ok=True)

    files_to_process = list(_iter_files(path))
    
    if not files_to_process:
        typer.secho("No files found to process.", fg=typer.colors.YELLOW)
        return

    for file_path in files_to_process:
        importer, score = registry.best_importer_for_path(file_path)
        if importer is None or score <= 0:
            typer.secho(f"Skipping {file_path.name}: No suitable importer found.", fg=typer.colors.YELLOW)
            continue
            
        try:
            workbook_slug = _slugify_name(file_path.stem)
            
            # New structure:
            # out/timestamp/intermediate drafts/workbook_slug/
            # out/timestamp/final drafts/workbook_slug/
            # out/timestamp/reports/
            
            intermediate_dir = out / "intermediate drafts" / workbook_slug
            final_dir = out / "final drafts" / workbook_slug
            reports_dir = out / "reports"

            mapping_path = _resolve_mapping_path(file_path, out, mapping) # Passed out for legacy compat
            mapping_config = mapping_override
            if mapping_config is None and mapping_path is not None:
                mapping_config = load_mapping_config(mapping_path)
            if mapping_config is None:
                inspection = importer.inspect(file_path)
                mapping_config = inspection.mapping_stub

            result = importer.convert(file_path, mapping_config)

            # Write intermediate JSON-LD files
            write_intermediate_outputs(result, intermediate_dir)

            # Write final DraftV1 files
            write_draft_outputs(result, final_dir)

            # Write conversion report
            write_report(result.report, reports_dir, file_path.stem)

            imported += 1
            typer.secho(
                f"  {file_path.name}: {len(result.recipes)} recipes",
                fg=typer.colors.GREEN,
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{file_path.name}: {exc}")
            workbook_slug = _slugify_name(file_path.stem)
            reports_dir = out / "reports"
            report = ConversionReport(errors=[str(exc)])
            write_report(report, reports_dir, file_path.stem)
            continue

    typer.secho(f"\nStaged {imported} file(s).", fg=typer.colors.GREEN)
    if errors:
        typer.secho("Errors encountered:", fg=typer.colors.YELLOW)
        for message in errors:
            typer.secho(f"- {message}", fg=typer.colors.YELLOW)


@app.command()
def inspect(
    path: Path = typer.Argument(..., help="Workbook file to inspect."),
    out: Path = typer.Option(Path("staging"), "--out", help="Output folder."),
    write_mapping: bool = typer.Option(
        False,
        "--write-mapping",
        help="Write a mapping stub alongside staged outputs.",
    ),
) -> None:
    """Inspect a single workbook and print layout guesses."""
    if not path.exists():
        _fail(f"Path not found: {path}")
    if not path.is_file():
        _fail("Inspect expects a workbook file.")

    importer = _require_importer(path)
    inspection = importer.inspect(path)
    typer.secho(f"Workbook: {path.name}", fg=typer.colors.CYAN)
    for sheet in inspection.sheets:
        layout = sheet.layout or "unknown"
        header_row = sheet.header_row or 0
        confidence = sheet.confidence if sheet.confidence is not None else 0.0
        note = " (low confidence)" if sheet.low_confidence else ""
        typer.echo(f"- {sheet.name}: {layout} header_row={header_row} score={confidence:.2f}{note}")
    if write_mapping and inspection.mapping_stub is not None:
        mapping_path = out / "mappings" / f"{path.stem}.mapping.yaml"
        save_mapping_config(mapping_path, inspection.mapping_stub)
        typer.secho(f"Wrote mapping stub to {mapping_path}", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()