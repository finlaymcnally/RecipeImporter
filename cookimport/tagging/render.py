"""Output formatting for tag suggestions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cookimport.tagging.engine import TagSuggestion


def render_suggestions_text(
    title: str,
    suggestions: list[TagSuggestion],
    explain: bool = False,
) -> str:
    """Render tag suggestions as human-readable text."""
    lines = [f"Recipe: {title}"]
    if not suggestions:
        lines.append("  (no tags suggested)")
        return "\n".join(lines)

    lines.append("Suggested tags:")
    for s in suggestions:
        line = f"  - {s.category_key}/{s.tag_key} ({s.confidence:.2f})"
        if explain and s.evidence:
            line += "  " + "; ".join(s.evidence)
        lines.append(line)
    return "\n".join(lines)


def serialize_suggestions_json(
    suggestions: list[TagSuggestion],
    recipe_id: str | None = None,
    title: str | None = None,
    catalog_fingerprint: str | None = None,
    new_tag_proposals: list[dict[str, str]] | None = None,
    llm_validation: dict[str, Any] | None = None,
    llm_pipeline_id: str | None = None,
) -> dict[str, Any]:
    """Convert suggestions to a JSON-serializable dict."""
    deterministic_count = sum(1 for suggestion in suggestions if suggestion.source != "llm")
    llm_count = sum(1 for suggestion in suggestions if suggestion.source == "llm")
    return {
        "recipe_id": recipe_id,
        "title": title,
        "catalog_fingerprint": catalog_fingerprint,
        "tagged_at": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "total": len(suggestions),
            "deterministic": deterministic_count,
            "llm": llm_count,
        },
        "suggestions": [
            {
                "tag_key": s.tag_key,
                "category_key": s.category_key,
                "confidence": round(s.confidence, 4),
                "evidence": s.evidence,
                "source": s.source,
                "llm_pipeline_id": s.llm_pipeline_id,
            }
            for s in suggestions
        ],
        "new_tag_proposals": list(new_tag_proposals or []),
        "llm_validation": dict(llm_validation or {}),
        "llm_pipeline_id": llm_pipeline_id,
    }


def write_tags_json(
    path: Path,
    suggestions: list[TagSuggestion],
    recipe_id: str | None = None,
    title: str | None = None,
    catalog_fingerprint: str | None = None,
    new_tag_proposals: list[dict[str, str]] | None = None,
    llm_validation: dict[str, Any] | None = None,
    llm_pipeline_id: str | None = None,
) -> None:
    """Write *.tags.json for a single recipe."""
    data = serialize_suggestions_json(
        suggestions,
        recipe_id,
        title,
        catalog_fingerprint,
        new_tag_proposals=new_tag_proposals,
        llm_validation=llm_validation,
        llm_pipeline_id=llm_pipeline_id,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_run_report(
    path: Path,
    recipes_processed: int,
    per_recipe: list[dict[str, Any]],
    catalog_fingerprint: str | None = None,
    llm_report: dict[str, Any] | None = None,
) -> None:
    """Write a summary run report JSON."""
    # Aggregate stats
    total_tags = sum(len(r.get("suggestions", [])) for r in per_recipe)
    deterministic_tags = 0
    llm_tags = 0
    zero_tag_recipes = [r["title"] for r in per_recipe if not r.get("suggestions")]
    new_tag_proposal_count = sum(len(r.get("new_tag_proposals", [])) for r in per_recipe)

    # Per-category counts
    cat_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}
    for r in per_recipe:
        for s in r.get("suggestions", []):
            cat = s.get("category_key", "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            source = str(s.get("source") or "deterministic")
            source_counts[source] = source_counts.get(source, 0) + 1
            if source == "llm":
                llm_tags += 1
            else:
                deterministic_tags += 1

    report = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "catalog_fingerprint": catalog_fingerprint,
        "recipes_processed": recipes_processed,
        "total_tags_suggested": total_tags,
        "deterministic_tags_suggested": deterministic_tags,
        "llm_tags_suggested": llm_tags,
        "new_tag_proposals": new_tag_proposal_count,
        "avg_tags_per_recipe": round(total_tags / max(1, recipes_processed), 2),
        "per_category_counts": dict(sorted(cat_counts.items())),
        "per_source_counts": dict(sorted(source_counts.items())),
        "zero_tag_recipe_count": len(zero_tag_recipes),
        "zero_tag_recipes": zero_tag_recipes[:50],  # Cap for readability
        "per_recipe": per_recipe,
    }
    if llm_report:
        report["llm"] = dict(llm_report)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
