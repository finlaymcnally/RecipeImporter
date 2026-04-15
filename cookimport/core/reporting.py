import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cookimport import __version__ as IMPORTER_VERSION
from cookimport.core.models import ConversionReport, ConversionResult

logger = logging.getLogger(__name__)

_REPORT_TOTAL_FIELD_TO_ATTR: tuple[tuple[str, str], ...] = (
    ("totalRecipes", "total_recipes"),
    ("totalStandaloneBlocks", "total_standalone_blocks"),
)


def build_authoritative_stage_report(
    base_report: ConversionReport | None,
) -> ConversionReport:
    """Return a stage-owned report shell without inherited aggregate totals.

    Processed stage runs should recompute aggregate counts from the final
    authoritative `ConversionResult` instead of reusing importer-era totals.
    """

    if base_report is None:
        return ConversionReport()

    payload = base_report.model_dump(
        mode="python",
        exclude_unset=True,
        exclude={
            "run_timestamp",
            "source_file",
            "importer_name",
            "average_confidence",
            "category_confidence",
            "total_recipes",
            "total_standalone_blocks",
            "timing",
            "output_stats",
            "run_config",
            "run_config_hash",
            "run_config_summary",
            "llm_codex_farm",
        },
        exclude_none=True,
    )
    return ConversionReport(**payload)


def _report_counts_from_result(
    result: ConversionResult,
    *,
    standalone_block_count: int = 0,
) -> dict[str, int]:
    return {
        "totalRecipes": len(result.recipes),
        "totalStandaloneBlocks": int(standalone_block_count),
    }


def finalize_report_totals(
    report: ConversionReport,
    result: ConversionResult,
    *,
    standalone_block_count: int = 0,
    diagnostics_path: Path | None = None,
) -> dict[str, Any] | None:
    expected = _report_counts_from_result(
        result,
        standalone_block_count=standalone_block_count,
    )
    current = {
        field_alias: int(getattr(report, attr_name, 0) or 0)
        for field_alias, attr_name in _REPORT_TOTAL_FIELD_TO_ATTR
    }
    fields_set = set(getattr(report, "model_fields_set", set()) or set())
    prepopulated = any(
        attr_name in fields_set
        for _, attr_name in _REPORT_TOTAL_FIELD_TO_ATTR
    )
    mismatched_fields = [
        field_alias
        for field_alias in expected
        if current.get(field_alias) != expected[field_alias]
    ]

    diagnostics_payload: dict[str, Any] | None = None
    if prepopulated and mismatched_fields:
        diagnostics_payload = {
            "schema_version": "report_totals_mismatch.v1",
            "prepopulated": bool(prepopulated),
            "mismatched_fields": mismatched_fields,
            "before": current,
            "expected": expected,
        }
        warning_text = (
            "report_total_mismatch_detected: "
            + ", ".join(mismatched_fields)
            + " (rewritten from in-memory conversion result counts; "
            + ("prepopulated=true" if prepopulated else "prepopulated=false")
            + ")"
        )
        if warning_text not in report.warnings:
            report.warnings.append(warning_text)
        if diagnostics_path is not None:
            diagnostics_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostics_path.write_text(
                json.dumps(diagnostics_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )

    for field_alias, attr_name in _REPORT_TOTAL_FIELD_TO_ATTR:
        setattr(report, attr_name, int(expected[field_alias]))

    return diagnostics_payload

def compute_file_hash(file_path: Path) -> str:
    """Computes SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def generate_recipe_id(source_type: str, source_hash: str, location_id: str) -> str:
    """Generates a stable URN for a recipe."""
    return f"urn:recipeimport:{source_type}:{source_hash}:{location_id}"

class ProvenanceBuilder:
    """Helper to construct the standardized provenance dictionary."""

    def __init__(
        self,
        source_file: str,
        source_hash: str,
        extraction_method: str = "heuristic",
    ):
        self.source_file = source_file
        self.source_hash = source_hash
        self.extraction_method = extraction_method
        self.importer_version = IMPORTER_VERSION
        self.processing_log: List[str] = []

    def log(self, message: str):
        self.processing_log.append(message)

    def build(
        self,
        confidence_score: float | None,
        location: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        provenance = {
            "source_file": self.source_file,
            "source_hash": self.source_hash,
            "importer_version": self.importer_version,
            "extraction_method": self.extraction_method,
            "location": location,
            "processing_log": self.processing_log,
            "generated_at": datetime.now().isoformat(),
        }
        if confidence_score is not None:
            provenance["confidence_score"] = float(confidence_score)
        if extra:
            provenance.update(extra)
        return provenance

def enrich_report_with_stats(
    report: ConversionReport,
    result: ConversionResult,
    source_path: Path,
    *,
    standalone_block_count: int = 0,
    count_diagnostics_path: Path | None = None,
) -> dict[str, Any] | None:
    report.source_file = str(source_path)
    
    # Collect confidence scores
    scores: List[float] = []
    category_scores: Dict[str, List[float]] = {}
    
    for recipe in result.recipes:
        # Check provenance for confidence score
        conf = recipe.provenance.get("confidence_score")
        if conf is not None:
            try:
                score = float(conf)
                scores.append(score)
                
                # Group by category (first category if available)
                if recipe.recipe_category:
                    cat = recipe.recipe_category[0]
                    if cat not in category_scores:
                        category_scores[cat] = []
                    category_scores[cat].append(score)
                else:
                    if "Uncategorized" not in category_scores:
                        category_scores["Uncategorized"] = []
                    category_scores["Uncategorized"].append(score)
            except (ValueError, TypeError):
                pass
                
    if scores:
        report.average_confidence = sum(scores) / len(scores)
        
    for cat, cat_scores in category_scores.items():
        if cat_scores:
            report.category_confidence[cat] = sum(cat_scores) / len(cat_scores)

    return finalize_report_totals(
        report,
        result,
        standalone_block_count=standalone_block_count,
        diagnostics_path=count_diagnostics_path,
    )
