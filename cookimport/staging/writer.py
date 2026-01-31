from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from cookimport import __version__
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeCandidate,
    TipCandidate,
    TipTags,
    TopicCandidate,
)
from cookimport.staging.draft_v1 import recipe_candidate_to_draft_v1
from cookimport.staging.jsonld import recipe_candidate_to_jsonld

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = _SLUG_RE.sub("_", lowered).strip("_")
    return slug or "unknown"


def _slugify_location(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "location"
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", cleaned).strip("_")
    return slug or "location"


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


def _resolve_tip_index(provenance: dict[str, Any]) -> int | None:
    for key in ("tip_index", "tipIndex", "tip"):
        if key in provenance:
            try:
                return int(provenance[key])
            except (TypeError, ValueError):
                return None
    return None


def _ensure_tip_id(
    tip: TipCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
    tip_index: int,
) -> str:
    provenance = tip.provenance or {}
    existing = provenance.get("@id") or provenance.get("id") or tip.identifier
    if existing:
        tip.identifier = str(existing)
        return tip.identifier
    stable_id = f"urn:recipeimport:tip:{file_hash}:{sheet_slug}:t{row_index}:{tip_index}"
    tip.identifier = stable_id
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    tip.provenance = provenance
    return stable_id


def _ensure_topic_id(
    topic: TopicCandidate,
    file_hash: str,
    sheet_slug: str,
    row_index: int,
    topic_index: int,
) -> str:
    provenance = topic.provenance or {}
    existing = provenance.get("@id") or provenance.get("id") or topic.identifier
    if existing:
        topic.identifier = str(existing)
        return topic.identifier
    stable_id = f"urn:recipeimport:topic:{file_hash}:{sheet_slug}:tc{row_index}:{topic_index}"
    topic.identifier = stable_id
    provenance["@id"] = stable_id
    provenance.setdefault("converter_version", __version__)
    topic.provenance = provenance
    return stable_id


def _ensure_source(results: ConversionResult, candidate: RecipeCandidate) -> None:
    if not candidate.source:
        if results.workbook_path:
            candidate.source = Path(results.workbook_path).name
        elif results.workbook:
            candidate.source = results.workbook


def write_intermediate_outputs(results: ConversionResult, out_dir: Path) -> None:
    """Write intermediate RecipeSage JSON-LD outputs.

    These are the raw extracted recipes before transformation to final format.
    Output path: {out_dir}/r{index}.jsonld
    """
    for index, candidate in enumerate(results.recipes):
        _ensure_source(results, candidate)
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
        _ensure_source(results, candidate)
        _ensure_provenance(candidate)
        draft = recipe_candidate_to_draft_v1(candidate)
        out_path = out_dir / f"r{index}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(draft, indent=2, sort_keys=True), encoding="utf-8")


def write_tip_outputs(results: ConversionResult, out_dir: Path) -> None:
    """Write tip/knowledge outputs.

    Output path: {out_dir}/t{index}.json
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    general_tips = [
        tip for tip in results.tips if tip.scope == "general" and tip.standalone
    ]
    for index, tip in enumerate(general_tips):
        provenance = tip.provenance or {}
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        tip_index = _resolve_tip_index(provenance)
        if tip_index is None:
            tip_index = index
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)

        _ensure_tip_id(tip, file_hash, sheet_slug, row_index, tip_index)

        payload = tip.model_dump(by_alias=True, exclude_none=True)
        out_path = out_dir / f"t{index}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    summary_path = out_dir / "tips.md"
    if general_tips:
        lines = ["# Tip Summary", ""]
        for group in _group_tip_summaries(general_tips):
            indices = ", ".join(group["indices"])
            anchor_text = _format_tip_anchors(
                _collect_tip_anchors(group["tips"])  # type: ignore[arg-type]
            )
            header = f"- {indices}{anchor_text}"
            lines.append(header)
            group_header = group.get("header")
            if group_header:
                lines.append(f"  {group_header}")
            for tip_text in group["texts"]:
                lines.append(f"  {tip_text}")
        summary_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    else:
        summary_path.write_text("# Tip Summary\n\n(No tips generated.)\n", encoding="utf-8")


def write_topic_candidate_outputs(results: ConversionResult, out_dir: Path) -> None:
    """Write topic-candidate outputs for evaluation and LLM prefiltering.

    Output path: {out_dir}/topic_candidates.json, {out_dir}/topic_candidates.md
    """
    if not results.topic_candidates:
        return
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads: list[dict[str, Any]] = []
    for index, topic in enumerate(results.topic_candidates):
        provenance = topic.provenance or {}
        sheet_name = _resolve_sheet_name(provenance)
        row_index = _resolve_row_index(provenance)
        topic_index = _resolve_tip_index(provenance)
        if topic_index is None:
            topic_index = index
        sheet_slug = _slugify(sheet_name)
        file_hash = _resolve_file_hash(results, provenance)
        _ensure_topic_id(topic, file_hash, sheet_slug, row_index, topic_index)
        payloads.append(topic.model_dump(by_alias=True, exclude_none=True))

    json_path = out_dir / "topic_candidates.json"
    json_path.write_text(json.dumps(payloads, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        "# Topic Candidates",
        "",
        "_These are standalone atom-level snippets captured before tip classification. Use for evaluation/LLM prefiltering._",
        "",
    ]
    for index, topic in enumerate(results.topic_candidates):
        anchors = _format_tip_anchors(_collect_tip_anchors([topic]))
        provenance = topic.provenance or {}
        atom_meta = provenance.get("atom") if isinstance(provenance, dict) else None
        atom_kind = None
        if isinstance(atom_meta, dict):
            atom_kind = atom_meta.get("kind")
        kind_suffix = f" ({atom_kind})" if atom_kind else ""
        lines.append(f"- tc{index}{anchors}{kind_suffix}")
        header = _normalize_topic_header(topic.header or provenance.get("topic_header"))
        if header and header != topic.text:
            lines.append(f"  {header}")
        lines.append(f"  {topic.text}")
        if isinstance(atom_meta, dict):
            context_prev = _truncate_context(atom_meta.get("context_prev"))
            context_next = _truncate_context(atom_meta.get("context_next"))
            if context_prev:
                lines.append(f"  prev: {context_prev}")
            if context_next:
                lines.append(f"  next: {context_next}")
    md_path = out_dir / "topic_candidates.md"
    md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


_GENERIC_TIP_HEADERS = {
    "tip",
    "tips",
    "note",
    "notes",
    "hint",
    "hints",
    "pro tip",
    "pro tips",
}


def _normalize_topic_header(header: Any) -> str | None:
    if not header:
        return None
    cleaned = str(header).strip()
    if not cleaned:
        return None
    if cleaned.lower() in _GENERIC_TIP_HEADERS:
        return None
    return cleaned


def _truncate_context(value: Any, limit: int = 140) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split())
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)] + "..."


def _group_tip_summaries(tips: list[TipCandidate]) -> list[dict[str, object]]:
    groups: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for index, tip in enumerate(tips):
        key = _tip_summary_key(tip)
        if current is None or current["key"] != key:
            header = _tip_summary_header(tip)
            current = {
                "key": key,
                "indices": [f"t{index}"],
                "texts": [tip.text],
                "tips": [tip],
                "header": header,
            }
            groups.append(current)
        else:
            current["indices"].append(f"t{index}")
            current["texts"].append(tip.text)
            current["tips"].append(tip)
    return groups


def _tip_summary_key(tip: TipCandidate) -> tuple:
    provenance = tip.provenance or {}
    location = provenance.get("location", {}) if isinstance(provenance, dict) else {}
    header = _tip_summary_header(tip)
    block_index = location.get("block_index")
    start_block = location.get("start_block")
    end_block = location.get("end_block")
    chunk_index = location.get("chunk_index")
    return (
        tip.source_recipe_id,
        block_index,
        start_block,
        end_block,
        chunk_index,
        header,
    )


def _tip_summary_header(tip: TipCandidate) -> str | None:
    provenance = tip.provenance or {}
    header = (
        provenance.get("topic_header")
        or provenance.get("topicHeader")
        or provenance.get("tip_header")
        or provenance.get("tipHeader")
    )
    if not header:
        return None
    cleaned = str(header).strip()
    if not cleaned:
        return None
    if cleaned.lower() in _GENERIC_TIP_HEADERS:
        return None
    return cleaned


def _collect_tip_anchors(tips: list[TipCandidate | TopicCandidate]) -> dict[str, list[str]]:
    anchors = {
        "dishes": [],
        "ingredients": [],
        "techniques": [],
        "cooking_methods": [],
        "tools": [],
    }

    def add_unique(target: list[str], values: list[str]) -> None:
        for value in values:
            if value not in target:
                target.append(value)

    for tip in tips:
        tags = tip.tags
        add_unique(anchors["dishes"], list(tags.dishes))
        ingredient_values = (
            list(tags.meats)
            + list(tags.vegetables)
            + list(tags.herbs)
            + list(tags.spices)
            + list(tags.dairy)
            + list(tags.grains)
            + list(tags.legumes)
            + list(tags.fruits)
            + list(tags.sweeteners)
            + list(tags.oils_fats)
        )
        add_unique(anchors["ingredients"], ingredient_values)
        add_unique(anchors["techniques"], list(tags.techniques))
        add_unique(anchors["cooking_methods"], list(tags.cooking_methods))
        add_unique(anchors["tools"], list(tags.tools))

    return anchors


def _format_tip_anchors(anchors: dict[str, list[str]]) -> str:
    parts: list[str] = []
    if anchors.get("dishes"):
        parts.append(f"dish: {', '.join(anchors['dishes'])}")
    if anchors.get("ingredients"):
        parts.append(f"ingredients: {', '.join(anchors['ingredients'])}")
    if anchors.get("techniques"):
        parts.append(f"techniques: {', '.join(anchors['techniques'])}")
    if anchors.get("cooking_methods"):
        parts.append(f"methods: {', '.join(anchors['cooking_methods'])}")
    if anchors.get("tools"):
        parts.append(f"tools: {', '.join(anchors['tools'])}")
    if not parts:
        return ""
    return " [" + "; ".join(parts) + "]"


def write_raw_artifacts(results: ConversionResult, out_dir: Path) -> None:
    """Write raw artifacts captured during conversion.

    Output path: {out_dir}/raw/{importer}/{source_hash}/{location_id}.{ext}
    """
    if not results.raw_artifacts:
        return

    for artifact in results.raw_artifacts:
        _write_raw_artifact(artifact, out_dir)


def _write_raw_artifact(artifact: RawArtifact, out_dir: Path) -> None:
    importer_slug = _slugify(artifact.importer)
    source_hash = artifact.source_hash or "unknown"
    location = _slugify_location(artifact.location_id)
    ext = (artifact.extension or "txt").lstrip(".")

    target_dir = out_dir / "raw" / importer_slug / source_hash
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{location}.{ext}"

    payload = artifact.content
    if isinstance(payload, (dict, list)):
        target_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding=artifact.encoding or "utf-8",
        )
        return
    if isinstance(payload, bytes):
        target_path.write_bytes(payload)
        return
    text_payload = "" if payload is None else str(payload)
    target_path.write_text(text_payload, encoding=artifact.encoding or "utf-8")


def write_report(report: ConversionReport, out_dir: Path, workbook_name: str) -> Path:
    """Write a conversion report JSON file for a workbook.

    Output path: {out_dir}/{workbook_slug}.import_report.json
    """
    slug = _slugify(workbook_name)
    out_path = out_dir / f"{slug}.import_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(by_alias=True, exclude_none=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return out_path
