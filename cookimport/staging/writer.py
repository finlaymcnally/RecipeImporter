from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from cookimport import __version__
from cookimport.core.models import ConversionReport, ConversionResult, RecipeCandidate
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1
from cookimport.staging.jsonld import recipe_candidate_to_jsonld

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = _SLUG_RE.sub("_", lowered).strip("_")
    return slug or "unknown"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _resolve_file_hash(results: ConversionResult, provenance: dict[str, Any]) -> str:
    file_hash = provenance.get("file_hash") or provenance.get("fileHash")
    if file_hash:
        return str(file_hash)
    workbook_path = provenance.get("file_path") or provenance.get("filePath")
    if workbook_path:
        path = Path(str(workbook_path))
        if path.exists():
            return _hash_file(path)
    if results.workbook_path:
        path = Path(results.workbook_path)
        if path.exists():
            return _hash_file(path)
    return "unknown"


def _resolve_workbook_name(results: ConversionResult, provenance: dict[str, Any]) -> str:
    if results.workbook:
        return results.workbook
    if provenance.get("workbook"):
        return str(provenance["workbook"])
    workbook_path = provenance.get("file_path") or provenance.get("filePath")
    if workbook_path:
        return Path(str(workbook_path)).name
    return "workbook"


def _resolve_sheet_name(provenance: dict[str, Any]) -> str:
    return str(provenance.get("sheet") or "sheet")


def _resolve_row_index(provenance: dict[str, Any]) -> int:
    for key in ("row_index", "rowIndex", "row"):
        if key in provenance:
            try:
                return int(provenance[key])
            except (TypeError, ValueError):
                return 0
    location = provenance.get("location")
    if isinstance(location, dict):
        for key in ("row_index", "rowIndex", "row", "chunk_index", "chunkIndex", "chunk"):
            if key in location:
                try:
                    return int(location[key])
                except (TypeError, ValueError):
                    return 0
    return 0


def _ensure_provenance(candidate: RecipeCandidate) -> dict[str, Any]:
    if candidate.provenance is None:
        candidate.provenance = {}
    return candidate.provenance


def _ensure_candidate_id(
    candidate: RecipeCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
) -> str:
    provenance = _ensure_provenance(candidate)
    existing = provenance.get("@id") or provenance.get("id")
    if existing:
        return str(existing)
    if candidate.identifier:
        provenance["@id"] = candidate.identifier
        provenance.setdefault("converter_version", __version__)
        return candidate.identifier
    stable_id = f"urn:recipeimport:excel:{file_hash}:{sheet_slug}:r{row_index}"
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    return stable_id


def write_intermediate_outputs(results: ConversionResult, out_dir: Path) -> None:
    """Write intermediate RecipeSage JSON-LD outputs.

    These are the raw extracted recipes before transformation to final format.
    Output path: {out_dir}/r{index}.jsonld
    """
    for index, candidate in enumerate(results.recipes):
        provenance = _ensure_provenance(candidate)
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)

        # Ensure stable ID for the candidate
        _ensure_candidate_id(candidate, file_hash, sheet_slug, row_index)

        jsonld = recipe_candidate_to_jsonld(candidate)

        out_path = out_dir / f"r{index}.jsonld"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(jsonld, indent=2, sort_keys=True), encoding="utf-8")


def write_draft_outputs(results: ConversionResult, out_dir: Path) -> None:
    """Write RecipeDraftV1 outputs (final format).

    Output path: {out_dir}/r{index}.json
    """
    for index, candidate in enumerate(results.recipes):
        _ensure_provenance(candidate)
        draft = recipe_candidate_to_draft_v1(candidate)
        out_path = out_dir / f"r{index}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(draft, indent=2, sort_keys=True), encoding="utf-8")


def write_report(report: ConversionReport, out_dir: Path, workbook_name: str) -> Path:
    """Write a conversion report JSON file for a workbook.

    Output path: {out_dir}/{workbook_slug}.excel_import_report.json
    """
    slug = _slugify(workbook_name)
    out_path = out_dir / f"{slug}.excel_import_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(by_alias=True, exclude_none=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
