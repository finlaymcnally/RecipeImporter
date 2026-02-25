from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import zipfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import typer
from bs4 import BeautifulSoup, FeatureNotFound

from cookimport.core.blocks import Block
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    epub_extractor_choices_for_help,
    normalize_epub_extractor_name,
)
from cookimport.core.reporting import compute_file_hash
from cookimport.parsing.block_roles import assign_block_roles
from cookimport.parsing.epub_auto_select import (
    selected_auto_score,
    select_epub_extractor_auto,
)
from cookimport.plugins import epub as epub_plugin

from .archive import (
    SpineEntry,
    coerce_json_safe,
    members_for_unpack,
    parse_epub_archive,
    read_zip_member,
)
from .epubcheck import find_epubcheck_jar, run_epubcheck
from .models import (
    CandidateDebug,
    EpubCandidateReport,
    EpubInspectReport,
    EpubSpineItemReport,
)

try:
    from epub_utils import Document as EpubUtilsDocument  # type: ignore
except Exception:  # pragma: no cover - optional debug dependency
    EpubUtilsDocument = None


epub_app = typer.Typer(help="EPUB inspection and pipeline debugging tools.")

_CLASS_KEYWORDS = ("ingredient", "instruction", "direction", "method", "recipe")


def _fail(message: str) -> None:
    typer.secho(message, err=True, fg=typer.colors.RED)
    raise typer.Exit(1)


def _require_epub_path(path: Path) -> Path:
    if not path.exists():
        _fail(f"EPUB file not found: {path}")
    if not path.is_file():
        _fail(f"Expected a file path, got: {path}")
    if path.suffix.lower() != ".epub":
        _fail(f"Expected an .epub file, got: {path}")
    return path


def _normalize_epub_extractor(value: str) -> str:
    normalized = normalize_epub_extractor_name(value)
    if normalized not in EPUB_EXTRACTOR_CANONICAL_SET:
        _fail(
            f"Invalid EPUB extractor: {value!r}. "
            f"Expected one of: {epub_extractor_choices_for_help()}."
        )
    return normalized


def _normalize_auto_candidates(value: str) -> tuple[str, ...]:
    raw_parts = [part.strip().lower() for part in str(value).split(",")]
    candidates: list[str] = []
    seen: set[str] = set()
    allowed = EPUB_EXTRACTOR_CANONICAL_SET
    for part in raw_parts:
        if not part or part in seen:
            continue
        normalized = normalize_epub_extractor_name(part)
        if normalized not in allowed:
            _fail(
                f"Invalid candidate extractor: {part!r}. "
                "Expected comma-separated values from: "
                f"{epub_extractor_choices_for_help()}."
            )
        seen.add(normalized)
        candidates.append(normalized)
    if not candidates:
        _fail("No extractor candidates were provided.")
    return tuple(candidates)


def _normalize_html_parser_version(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"v1", "v2"}:
        _fail(
            f"Invalid EPUB Unstructured HTML parser version: {value!r}. "
            "Expected one of: v1, v2."
        )
    return normalized


def _normalize_preprocess_mode(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"none", "br_split_v1", "semantic_v1"}:
        _fail(
            f"Invalid EPUB Unstructured preprocess mode: {value!r}. "
            "Expected one of: none, br_split_v1, semantic_v1."
        )
    return normalized


def _normalize_dump_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"xhtml", "plain"}:
        _fail(f"Invalid dump format: {value!r}. Expected xhtml or plain.")
    return normalized


def _prepare_output_dir(path: Path, *, force: bool) -> Path:
    path = path.resolve()
    if path.exists():
        if not path.is_dir():
            _fail(f"Output path exists and is not a directory: {path}")
        if any(path.iterdir()) and not force:
            _fail(f"Output directory is not empty: {path}. Re-run with --force to overwrite.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    payload = "\n".join(
        json.dumps(coerce_json_safe(row), sort_keys=True, ensure_ascii=False) for row in rows
    )
    path.write_text(payload + "\n", encoding="utf-8")


def _soup_from_html(html_text: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html_text, "lxml")
    except FeatureNotFound:  # pragma: no cover - fallback path
        return BeautifulSoup(html_text, "html.parser")


def _extract_doc_title(soup: BeautifulSoup) -> str | None:
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        return title_tag.get_text(" ", strip=True)
    heading = soup.find(["h1", "h2", "h3"])
    if heading and heading.get_text(strip=True):
        return heading.get_text(" ", strip=True)
    return None


def _plain_text_from_soup(soup: BeautifulSoup) -> str:
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _preview_text(text: str, *, limit: int = 120) -> str:
    flattened = re.sub(r"\s+", " ", text).strip()
    if len(flattened) <= limit:
        return flattened
    return flattened[: limit - 3].rstrip() + "..."


def _render_block_preview_md(
    blocks: list[Block],
    *,
    source_path: Path,
    extractor: str,
    stats: dict[str, Any],
) -> str:
    lines: list[str] = [
        "# EPUB Blocks Preview",
        "",
        f"- Source: `{source_path}`",
        f"- Extractor: `{extractor}`",
        f"- Total blocks: `{stats['block_count']}`",
        f"- Total text chars: `{stats['total_text_chars']}`",
        "",
    ]
    for index, block in enumerate(blocks):
        features = dict(block.features)
        key_pairs: list[str] = []
        for key in (
            "spine_index",
            "block_role",
            "heading_level",
            "is_heading",
            "is_ingredient_header",
            "is_instruction_header",
            "is_yield",
            "md_line_start",
            "md_line_end",
        ):
            if key in features:
                key_pairs.append(f"{key}={features[key]}")
        role = features.get("block_role") or "unknown"
        lines.append(f"## [{index}] type={block.type} role={role}")
        if key_pairs:
            lines.append(f"features: {', '.join(key_pairs)}")
        lines.append(_preview_text(block.text, limit=240) or "<empty>")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_candidates_preview_md(report: EpubCandidateReport) -> str:
    lines: list[str] = [
        "# EPUB Candidate Preview",
        "",
        f"- Extractor: `{report.extractor}`",
        f"- Block count: `{report.block_count}`",
        f"- Candidate count: `{len(report.candidates)}`",
        "",
    ]
    if report.warnings:
        lines.append("## Warnings")
        for warning in report.warnings:
            lines.append(f"- {warning}")
        lines.append("")
    for candidate in report.candidates:
        lines.append(
            f"## Candidate {candidate.index} [{candidate.start_block}, {candidate.end_block}) "
            f"score={candidate.score:.3f}"
        )
        if candidate.title_guess:
            lines.append(f"title_guess: {candidate.title_guess}")
        lines.append(
            "anchors: "
            + ", ".join(f"{key}={value}" for key, value in sorted(candidate.anchors.items()))
        )
        lines.append("start_context:")
        for snippet in candidate.start_context:
            lines.append(f"- {snippet}")
        lines.append("end_context:")
        for snippet in candidate.end_context:
            lines.append(f"- {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_race_summary(payload: dict[str, Any], *, out_path: Path) -> str:
    selected_backend = str(payload.get("effective_extractor") or "").strip() or "<none>"
    selected_score = payload.get("selected_score")
    selected_score_label = (
        f"{float(selected_score):.3f}"
        if selected_score is not None
        else "n/a"
    )
    lines: list[str] = [
        f"Race report: {out_path}",
        f"Selected extractor: {selected_backend} (score={selected_score_label})",
        "Candidates:",
    ]
    for candidate in payload.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        backend = str(candidate.get("backend") or "<unknown>")
        status = str(candidate.get("status") or "unknown")
        average_score = candidate.get("average_score")
        if average_score is not None:
            try:
                score_label = f"{float(average_score):.3f}"
            except (TypeError, ValueError):
                score_label = str(average_score)
        else:
            score_label = "n/a"
        marker = "*" if backend == selected_backend else " "
        line = f" {marker} {backend}: {status}, average_score={score_label}"
        error = candidate.get("error")
        if error:
            line += f", error={error}"
        lines.append(line)
    return "\n".join(lines)


def _spine_item_report(entry: SpineEntry, html_text: str) -> EpubSpineItemReport:
    soup = _soup_from_html(html_text)
    text = _plain_text_from_soup(soup)
    word_count = len(re.findall(r"\S+", text))
    tag_counter = Counter(tag.name for tag in soup.find_all(True))
    class_hits = Counter()
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        haystack = classes.lower()
        for keyword in _CLASS_KEYWORDS:
            if keyword in haystack:
                class_hits[keyword] += 1
    return EpubSpineItemReport(
        index=entry.index,
        idref=entry.idref,
        href=entry.href,
        media_type=entry.media_type,
        linear=entry.linear,
        doc_title=_extract_doc_title(soup),
        text_chars=len(text),
        word_count=word_count,
        top_tags=dict(tag_counter.most_common(8)),
        class_keyword_hits=dict(class_hits),
    )


def _inspect_backend_label(
    path: Path,
    metadata: dict[str, str],
    warnings: list[str],
) -> str:
    if EpubUtilsDocument is None:
        return "zip"
    try:
        doc = EpubUtilsDocument(str(path))
        title = getattr(doc, "title", None)
        if isinstance(title, str) and title.strip() and "title" not in metadata:
            metadata["title"] = title.strip()
        return "epub_utils+zip"
    except Exception as exc:  # pragma: no cover - optional dependency path
        warnings.append(f"epub-utils was available but failed to load document: {exc}")
        return "zip"


def _render_inspect_summary(report: EpubInspectReport) -> str:
    lines: list[str] = [
        f"EPUB: {report.path}",
        f"Size: {report.file_size_bytes} bytes",
        f"SHA256: {report.sha256}",
        f"Inspector backend: {report.inspector_backend}",
        f"Container rootfile: {report.container_rootfile_path or 'unknown'}",
        f"Package: {report.package_path or 'unknown'}",
    ]
    if report.metadata:
        summary = " ".join(f'{key}="{value}"' for key, value in sorted(report.metadata.items()))
        lines.append(f"Metadata: {summary}")
    lines.append(f"Spine: {len(report.spine)} items")
    for entry in report.spine:
        warning_suffix = " WARN empty" if entry.text_chars == 0 else ""
        top_tags = " ".join(f"{k}={v}" for k, v in entry.top_tags.items())
        lines.append(
            f"  [{entry.index}] {entry.href or '<missing>'} title={entry.doc_title!r} "
            f"chars={entry.text_chars} words={entry.word_count}{warning_suffix}"
        )
        if top_tags:
            lines.append(f"    tags: {top_tags}")
        if entry.class_keyword_hits:
            hits = " ".join(f"{k}={v}" for k, v in sorted(entry.class_keyword_hits.items()))
            lines.append(f"    class_hits: {hits}")
        for warning in entry.warnings:
            lines.append(f"    warning: {warning}")
    if report.warnings:
        lines.append("Warnings:")
        for warning in report.warnings:
            lines.append(f"  - {warning}")
    return "\n".join(lines)


def _safe_zip_target(out_dir: Path, member_name: str) -> Path:
    member_name = member_name.replace("\\", "/").lstrip("/")
    target = (out_dir / member_name).resolve()
    root = out_dir.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Blocked path traversal member: {member_name}")
    return target


def _open_path(path: Path) -> None:
    opener = shutil.which("open") or shutil.which("xdg-open")
    if opener is None:
        typer.echo(f"Open command unavailable. File path: {path}")
        return
    os.spawnlp(os.P_NOWAIT, opener, opener, str(path))


@contextmanager
def _temporary_unstructured_options(
    *,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> Iterable[None]:
    previous_parser = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION")
    previous_skip = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
    previous_preprocess = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE")
    os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = html_parser_version
    os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = (
        "true" if skip_headers_footers else "false"
    )
    os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = preprocess_mode
    try:
        yield
    finally:
        if previous_parser is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION"] = previous_parser
        if previous_skip is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS"] = previous_skip
        if previous_preprocess is None:
            os.environ.pop("C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE", None)
        else:
            os.environ["C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE"] = previous_preprocess


def _extract_pipeline_blocks(
    *,
    path: Path,
    extractor: str,
    start_spine: int | None,
    end_spine: int | None,
    html_parser_version: str,
    skip_headers_footers: bool,
    preprocess_mode: str,
) -> tuple[epub_plugin.EpubImporter, list[Block]]:
    importer = epub_plugin.EpubImporter()
    importer._overrides = None  # noqa: SLF001
    with _temporary_unstructured_options(
        html_parser_version=html_parser_version,
        skip_headers_footers=skip_headers_footers,
        preprocess_mode=preprocess_mode,
    ):
        try:
            blocks = importer._extract_docpack(  # noqa: SLF001
                path,
                start_spine=start_spine,
                end_spine=end_spine,
                extractor=extractor,
            )
        finally:
            importer._overrides = None  # noqa: SLF001
    assign_block_roles(blocks)
    return importer, blocks


def _build_blocks_stats(blocks: list[Block]) -> dict[str, Any]:
    role_counts = Counter(str(block.features.get("block_role") or "unknown") for block in blocks)
    type_counts = Counter(str(block.type) for block in blocks)
    total_chars = sum(len(block.text) for block in blocks)
    empty_count = sum(1 for block in blocks if not block.text.strip())
    warnings: list[str] = []
    if not blocks:
        warnings.append("No blocks extracted from EPUB.")
    elif total_chars == 0:
        warnings.append("Extracted blocks contain no text characters.")
    if blocks and (empty_count / len(blocks)) > 0.8:
        warnings.append("More than 80% of blocks are empty after extraction.")
    return {
        "block_count": len(blocks),
        "total_text_chars": total_chars,
        "empty_block_count": empty_count,
        "types": dict(type_counts),
        "block_roles": dict(role_counts),
        "warnings": warnings,
    }


@epub_app.command("inspect")
def inspect_epub(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Optional output folder for inspect_report.json.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print report JSON to stdout instead of a human-readable summary.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    info = parse_epub_archive(source)

    spine_reports: list[EpubSpineItemReport] = []
    warnings = list(info.warnings)
    with zipfile.ZipFile(source) as zip_handle:
        for entry in info.spine:
            entry_warnings: list[str] = []
            if not entry.path:
                entry_warnings.append("Missing resolved spine path.")
                spine_report = EpubSpineItemReport(
                    index=entry.index,
                    idref=entry.idref,
                    href=entry.href,
                    media_type=entry.media_type,
                    linear=entry.linear,
                    warnings=entry_warnings,
                )
                spine_reports.append(spine_report)
                continue
            try:
                html_bytes = read_zip_member(zip_handle, entry.path)
            except KeyError:
                entry_warnings.append(f"Spine entry not present in archive: {entry.path}")
                spine_report = EpubSpineItemReport(
                    index=entry.index,
                    idref=entry.idref,
                    href=entry.href,
                    media_type=entry.media_type,
                    linear=entry.linear,
                    warnings=entry_warnings,
                )
                spine_reports.append(spine_report)
                continue
            html_text = html_bytes.decode("utf-8", errors="replace")
            spine_report = _spine_item_report(entry, html_text)
            spine_report.warnings.extend(entry_warnings)
            spine_reports.append(spine_report)

    metadata = dict(info.metadata)
    inspector_backend = _inspect_backend_label(source, metadata, warnings)
    report = EpubInspectReport(
        path=str(source),
        file_size_bytes=source.stat().st_size,
        sha256=compute_file_hash(source),
        inspector_backend=inspector_backend,
        container_rootfile_path=info.container_rootfile_path,
        package_path=info.package_path,
        metadata=metadata,
        spine=spine_reports,
        warnings=warnings,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )

    if out is not None:
        output_dir = _prepare_output_dir(out, force=force)
        _write_json(output_dir / "inspect_report.json", report.model_dump())
        typer.secho(f"Wrote inspect report: {output_dir / 'inspect_report.json'}", fg=typer.colors.GREEN)

    if json_output:
        typer.echo(json.dumps(report.model_dump(), indent=2, sort_keys=True))
    else:
        typer.echo(_render_inspect_summary(report))


@epub_app.command("dump")
def dump_epub_spine(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    spine_index: int = typer.Option(..., "--spine-index", min=0, help="Spine index to dump."),
    format: str = typer.Option(
        "xhtml",
        "--format",
        help="Dump format: xhtml or plain.",
    ),
    out: Path = typer.Option(..., "--out", help="Output directory for dumped files."),
    open_file: bool = typer.Option(
        False,
        "--open",
        help="Open dumped file with system default app.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    output_format = _normalize_dump_format(format)
    info = parse_epub_archive(source)
    if spine_index >= len(info.spine):
        _fail(f"Spine index {spine_index} out of range; EPUB has {len(info.spine)} entries.")
    entry = info.spine[spine_index]
    if not entry.path:
        _fail(f"Spine index {spine_index} has no resolvable archive path.")

    with zipfile.ZipFile(source) as zip_handle:
        try:
            html_bytes = read_zip_member(zip_handle, entry.path)
        except KeyError:
            _fail(f"Spine entry not found in archive: {entry.path}")
    html_text = html_bytes.decode("utf-8", errors="replace")

    output_dir = _prepare_output_dir(out, force=force)
    if output_format == "xhtml":
        payload = html_text
        output_path = output_dir / f"spine_{spine_index:04d}.xhtml"
    else:
        payload = _plain_text_from_soup(_soup_from_html(html_text))
        output_path = output_dir / f"spine_{spine_index:04d}.txt"
    output_path.write_text(payload, encoding="utf-8")

    doc_title = _extract_doc_title(_soup_from_html(html_text))
    dump_meta = {
        "source_file": str(source),
        "spine_index": spine_index,
        "idref": entry.idref,
        "href": entry.href,
        "archive_path": entry.path,
        "media_type": entry.media_type,
        "doc_title": doc_title,
        "output_path": str(output_path),
        "format": output_format,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(output_dir / "dump_meta.json", dump_meta)

    typer.secho(f"Wrote {output_path}", fg=typer.colors.GREEN)
    if open_file:
        _open_path(output_path)


@epub_app.command("unpack")
def unpack_epub(
    path: Path = typer.Argument(..., help="EPUB file to unpack."),
    out: Path = typer.Option(..., "--out", help="Output directory."),
    only_spine: bool = typer.Option(
        False,
        "--only-spine",
        help="Extract only container/package/nav/spine XHTML members.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    output_dir = _prepare_output_dir(out, force=force)
    info = parse_epub_archive(source)

    extracted: list[str] = []
    with zipfile.ZipFile(source) as zip_handle:
        members = members_for_unpack(
            info,
            only_spine=only_spine,
            available_members=zip_handle.namelist(),
        )
        for member in members:
            target = _safe_zip_target(output_dir, member)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                payload = read_zip_member(zip_handle, member)
            except KeyError:
                continue
            target.write_bytes(payload)
            extracted.append(member)

    unpack_meta = {
        "source_file": str(source),
        "only_spine": only_spine,
        "extracted_count": len(extracted),
        "members": extracted,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _write_json(output_dir / "unpack_meta.json", unpack_meta)
    typer.secho(f"Unpacked {len(extracted)} files to {output_dir}", fg=typer.colors.GREEN)


@epub_app.command("blocks")
def debug_epub_blocks(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    out: Path = typer.Option(..., "--out", help="Output directory for block artifacts."),
    extractor: str = typer.Option(
        "unstructured",
        "--extractor",
        help="EPUB extractor: unstructured, beautifulsoup, markdown, or markitdown.",
    ),
    start_spine: int | None = typer.Option(
        None,
        "--start-spine",
        min=0,
        help="Optional inclusive spine start index.",
    ),
    end_spine: int | None = typer.Option(
        None,
        "--end-spine",
        min=1,
        help="Optional exclusive spine end index.",
    ),
    html_parser_version: str = typer.Option(
        "v1",
        "--html-parser-version",
        help="Unstructured HTML parser version (v1 or v2).",
    ),
    skip_headers_footers: bool = typer.Option(
        False,
        "--skip-headers-footers/--no-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers.",
    ),
    preprocess_mode: str = typer.Option(
        "br_split_v1",
        "--preprocess-mode",
        help="Unstructured preprocess mode: none, br_split_v1, semantic_v1.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    selected_extractor = _normalize_epub_extractor(extractor)
    selected_parser = _normalize_html_parser_version(html_parser_version)
    selected_preprocess = _normalize_preprocess_mode(preprocess_mode)
    if (
        start_spine is not None
        and end_spine is not None
        and end_spine <= start_spine
    ):
        _fail("--end-spine must be greater than --start-spine.")

    output_dir = _prepare_output_dir(out, force=force)
    _importer, blocks = _extract_pipeline_blocks(
        path=source,
        extractor=selected_extractor,
        start_spine=start_spine,
        end_spine=end_spine,
        html_parser_version=selected_parser,
        skip_headers_footers=skip_headers_footers,
        preprocess_mode=selected_preprocess,
    )

    rows = [
        {
            "index": index,
            "text": block.text,
            "type": str(block.type),
            "font_weight": block.font_weight,
            "features": coerce_json_safe(dict(block.features)),
        }
        for index, block in enumerate(blocks)
    ]
    stats = _build_blocks_stats(blocks)
    stats["extractor"] = selected_extractor
    stats["start_spine"] = start_spine
    stats["end_spine"] = end_spine
    stats["html_parser_version"] = selected_parser
    stats["skip_headers_footers"] = bool(skip_headers_footers)
    stats["preprocess_mode"] = selected_preprocess

    _write_jsonl(output_dir / "blocks.jsonl", rows)
    _write_json(output_dir / "blocks_stats.json", stats)
    (output_dir / "blocks_preview.md").write_text(
        _render_block_preview_md(
            blocks,
            source_path=source,
            extractor=selected_extractor,
            stats=stats,
        ),
        encoding="utf-8",
    )

    typer.secho(f"Wrote block artifacts to {output_dir}", fg=typer.colors.GREEN)
    typer.echo(f"Blocks: {stats['block_count']}")
    typer.echo(f"Total chars: {stats['total_text_chars']}")
    typer.echo(f"Type counts: {stats['types']}")
    typer.echo(f"Role counts: {stats['block_roles']}")
    for warning in stats.get("warnings", []):
        typer.secho(f"Warning: {warning}", fg=typer.colors.YELLOW)


@epub_app.command("candidates")
def debug_epub_candidates(
    path: Path = typer.Argument(..., help="EPUB file to inspect."),
    out: Path = typer.Option(..., "--out", help="Output directory for candidate artifacts."),
    extractor: str = typer.Option(
        "unstructured",
        "--extractor",
        help="EPUB extractor: unstructured, beautifulsoup, markdown, or markitdown.",
    ),
    start_spine: int | None = typer.Option(
        None,
        "--start-spine",
        min=0,
        help="Optional inclusive spine start index.",
    ),
    end_spine: int | None = typer.Option(
        None,
        "--end-spine",
        min=1,
        help="Optional exclusive spine end index.",
    ),
    html_parser_version: str = typer.Option(
        "v1",
        "--html-parser-version",
        help="Unstructured HTML parser version (v1 or v2).",
    ),
    skip_headers_footers: bool = typer.Option(
        False,
        "--skip-headers-footers/--no-skip-headers-footers",
        help="Enable Unstructured skip_headers_and_footers.",
    ),
    preprocess_mode: str = typer.Option(
        "br_split_v1",
        "--preprocess-mode",
        help="Unstructured preprocess mode: none, br_split_v1, semantic_v1.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    selected_extractor = _normalize_epub_extractor(extractor)
    selected_parser = _normalize_html_parser_version(html_parser_version)
    selected_preprocess = _normalize_preprocess_mode(preprocess_mode)
    if (
        start_spine is not None
        and end_spine is not None
        and end_spine <= start_spine
    ):
        _fail("--end-spine must be greater than --start-spine.")

    output_dir = _prepare_output_dir(out, force=force)
    importer, blocks = _extract_pipeline_blocks(
        path=source,
        extractor=selected_extractor,
        start_spine=start_spine,
        end_spine=end_spine,
        html_parser_version=selected_parser,
        skip_headers_footers=skip_headers_footers,
        preprocess_mode=selected_preprocess,
    )
    candidate_ranges = importer._detect_candidates(blocks)  # noqa: SLF001
    candidates: list[CandidateDebug] = []
    for index, (start_block, end_block, score) in enumerate(candidate_ranges):
        candidate_blocks = blocks[start_block:end_block]
        title_guess, _consumed = importer._extract_title(candidate_blocks)  # noqa: SLF001
        anchors = {
            "saw_ingredient_header": any(
                bool(block.features.get("is_ingredient_header")) for block in candidate_blocks
            ),
            "saw_instruction_header": any(
                bool(block.features.get("is_instruction_header")) for block in candidate_blocks
            ),
            "saw_yield": any(bool(block.features.get("is_yield")) for block in candidate_blocks),
        }
        candidates.append(
            CandidateDebug(
                index=index,
                start_block=start_block,
                end_block=end_block,
                score=float(score),
                title_guess=title_guess,
                anchors=anchors,
                start_context=[_preview_text(block.text, limit=180) for block in candidate_blocks[:5]],
                end_context=[_preview_text(block.text, limit=180) for block in candidate_blocks[-5:]],
            )
        )

    warnings: list[str] = []
    if not blocks:
        warnings.append("No blocks extracted from EPUB.")
    if not candidates:
        warnings.append("No recipe candidate ranges were detected.")
        if not any(bool(block.features.get("is_ingredient_header")) for block in blocks):
            warnings.append("No ingredient headers were detected in extracted blocks.")
        if not any(bool(block.features.get("is_instruction_header")) for block in blocks):
            warnings.append("No instruction headers were detected in extracted blocks.")
        if not any(bool(block.features.get("is_yield")) for block in blocks):
            warnings.append("No yield anchors were detected in extracted blocks.")

    report = EpubCandidateReport(
        extractor=selected_extractor,
        block_count=len(blocks),
        candidates=candidates,
        warnings=warnings,
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        options={
            "start_spine": start_spine,
            "end_spine": end_spine,
            "html_parser_version": selected_parser,
            "skip_headers_footers": bool(skip_headers_footers),
            "preprocess_mode": selected_preprocess,
        },
    )

    _write_json(output_dir / "candidates.json", report.model_dump())
    (output_dir / "candidates_preview.md").write_text(
        _render_candidates_preview_md(report),
        encoding="utf-8",
    )

    typer.secho(f"Wrote candidate artifacts to {output_dir}", fg=typer.colors.GREEN)
    if candidates:
        for candidate in candidates:
            typer.echo(
                f"Candidate {candidate.index}: blocks [{candidate.start_block}, "
                f"{candidate.end_block}) score={candidate.score:.3f} title={candidate.title_guess!r}"
            )
    else:
        typer.secho("No candidates detected.", fg=typer.colors.YELLOW)
        for warning in warnings:
            typer.echo(f"- {warning}")


@epub_app.command("validate")
def validate_epub(
    path: Path = typer.Argument(..., help="EPUB file to validate."),
    jar: Path | None = typer.Option(
        None,
        "--jar",
        help="Path to epubcheck.jar. If omitted, auto-discovery is used.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Optional output directory for epubcheck.txt and epubcheck.json.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Return non-zero exit code when EPUBCheck is unavailable or reports errors.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    jar_path = find_epubcheck_jar(jar)
    if jar_path is None:
        message = (
            "EPUBCheck jar not found. Provide --jar /path/to/epubcheck.jar, set "
            "C3IMP_EPUBCHECK_JAR, or place a jar under tools/epubcheck/."
        )
        if strict:
            _fail(message)
        typer.secho(message, fg=typer.colors.YELLOW)
        return

    summary, output_text = run_epubcheck(source, jar_path)
    payload = {
        "source_file": str(source),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        **summary,
    }

    if out is not None:
        output_dir = _prepare_output_dir(out, force=force)
        (output_dir / "epubcheck.txt").write_text(output_text, encoding="utf-8")
        _write_json(output_dir / "epubcheck.json", payload)
        typer.secho(f"Wrote EPUBCheck artifacts to {output_dir}", fg=typer.colors.GREEN)

    typer.echo(
        "EPUBCheck: "
        f"errors={payload['error_count']} warnings={payload['warning_count']} "
        f"exit_code={payload['java_exit_code']}"
    )

    if strict and (
        int(payload["java_exit_code"]) != 0 or int(payload["error_count"]) > 0
    ):
        raise typer.Exit(1)


@epub_app.command("race")
def race_epub_extractors(
    path: Path = typer.Argument(..., help="EPUB file to race candidate extractors on."),
    out: Path = typer.Option(..., "--out", help="Output directory for race artifacts."),
    candidates: str = typer.Option(
        "unstructured,markdown,beautifulsoup",
        "--candidates",
        help="Comma-separated candidate extractors for auto race.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print race report JSON to stdout.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Allow writing into a non-empty --out directory.",
    ),
) -> None:
    source = _require_epub_path(path)
    candidate_extractors = _normalize_auto_candidates(candidates)
    output_dir = _prepare_output_dir(out, force=force)

    try:
        resolution = select_epub_extractor_auto(
            source,
            candidate_extractors=candidate_extractors,
        )
    except Exception as exc:  # noqa: BLE001
        _fail(f"Extractor race failed: {exc}")

    payload = {
        **dict(resolution.artifact),
        "source_file": str(source),
        "source_hash": compute_file_hash(source),
        "selected_score": selected_auto_score(resolution.artifact),
    }
    out_path = output_dir / "epub_race_report.json"
    _write_json(out_path, payload)
    typer.secho(f"Wrote race report: {out_path}", fg=typer.colors.GREEN)
    typer.echo(_render_race_summary(payload, out_path=out_path))
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
