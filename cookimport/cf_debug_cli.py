from __future__ import annotations

from pathlib import Path

import typer

from cookimport.bench.followup_bundle import (
    write_ablation_matrix,
    write_case_export,
    write_followup_pack,
    write_line_role_audit,
    write_page_context,
    write_prompt_link_audit,
    write_selector_manifest,
    write_uncertainty_export,
)


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Deterministic follow-up exporters and audits for benchmark upload bundles.",
)


def _select_cases_command_text(
    *,
    bundle: Path,
    out: Path,
    top_neg: int,
    top_pos: int,
    outside_span: int,
    stage: list[str],
    include_case_id: list[str],
    include_recipe_id: list[str],
    include_line_range: list[str],
) -> str:
    parts = [
        "cf-debug",
        "select-cases",
        "--bundle",
        str(bundle),
        "--out",
        str(out),
        "--top-neg",
        str(top_neg),
        "--top-pos",
        str(top_pos),
        "--outside-span",
        str(outside_span),
    ]
    for value in stage:
        parts.extend(["--stage", value])
    for value in include_case_id:
        parts.extend(["--include-case-id", value])
    for value in include_recipe_id:
        parts.extend(["--include-recipe-id", value])
    for value in include_line_range:
        parts.extend(["--include-line-range", value])
    return " ".join(parts)


@app.command("select-cases")
def select_cases(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
    top_neg: int = typer.Option(0, "--top-neg", min=0),
    top_pos: int = typer.Option(0, "--top-pos", min=0),
    outside_span: int = typer.Option(0, "--outside-span", min=0),
    stage: list[str] | None = typer.Option(None, "--stage"),
    include_case_id: list[str] | None = typer.Option(None, "--include-case-id"),
    include_recipe_id: list[str] | None = typer.Option(None, "--include-recipe-id"),
    include_line_range: list[str] | None = typer.Option(None, "--include-line-range"),
) -> None:
    stage_values = stage or []
    include_case_values = include_case_id or []
    include_recipe_values = include_recipe_id or []
    include_line_range_values = include_line_range or []
    write_selector_manifest(
        bundle_dir=bundle,
        out_path=out,
        command=_select_cases_command_text(
            bundle=bundle,
            out=out,
            top_neg=top_neg,
            top_pos=top_pos,
            outside_span=outside_span,
            stage=stage_values,
            include_case_id=include_case_values,
            include_recipe_id=include_recipe_values,
            include_line_range=include_line_range_values,
        ),
        stage_filters=stage_values,
        top_neg=top_neg,
        top_pos=top_pos,
        outside_span=outside_span,
        include_case_ids=include_case_values,
        include_recipe_ids=include_recipe_values,
        include_line_ranges=include_line_range_values,
    )
    typer.echo(str(out))


@app.command("export-cases")
def export_cases(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_case_export(bundle_dir=bundle, selectors_path=selectors, out_dir=out)
    typer.echo(str(out))


@app.command("audit-line-role")
def audit_line_role(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_line_role_audit(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("audit-prompt-links")
def audit_prompt_links(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_prompt_link_audit(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("export-page-context")
def export_page_context(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_page_context(bundle_dir=bundle, selectors_path=selectors, out_path=out)
    typer.echo(str(out))


@app.command("export-uncertainty")
def export_uncertainty(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    confidence_threshold: float = typer.Option(0.9, "--confidence-threshold"),
) -> None:
    write_uncertainty_export(
        bundle_dir=bundle,
        selectors_path=selectors,
        out_path=out,
        confidence_threshold=confidence_threshold,
    )
    typer.echo(str(out))


@app.command("pack")
def pack(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    selectors: Path = typer.Option(..., "--selectors", exists=True, file_okay=True, dir_okay=False),
    out: Path = typer.Option(..., "--out"),
    readme: bool = typer.Option(True, "--readme/--no-readme"),
    confidence_threshold: float = typer.Option(0.9, "--confidence-threshold"),
) -> None:
    write_followup_pack(
        bundle_dir=bundle,
        selectors_path=selectors,
        out_dir=out,
        include_readme=readme,
        confidence_threshold=confidence_threshold,
    )
    typer.echo(str(out))


@app.command("ablate")
def ablate(
    bundle: Path = typer.Option(..., "--bundle", exists=True, file_okay=False, dir_okay=True),
    out: Path = typer.Option(..., "--out"),
) -> None:
    write_ablation_matrix(bundle_dir=bundle, out_path=out)
    typer.echo(str(out))
