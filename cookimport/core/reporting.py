import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cookimport import __version__ as IMPORTER_VERSION
from cookimport.core.models import ConversionReport, ConversionResult

logger = logging.getLogger(__name__)

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
        confidence_score: float,
        location: Dict[str, Any],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        provenance = {
            "source_file": self.source_file,
            "source_hash": self.source_hash,
            "importer_version": self.importer_version,
            "extraction_method": self.extraction_method,
            "confidence_score": confidence_score,
            "location": location,
            "processing_log": self.processing_log,
            "generated_at": datetime.now().isoformat(),
        }
        if extra:
            provenance.update(extra)
        return provenance

class ReportBuilder:
    """Context manager to accumulate events and write the import report."""

    def __init__(self, source_path: Path, output_dir: Path):
        self.source_path = source_path
        self.output_dir = output_dir
        self.start_time = 0.0
        self.candidates: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.llm_usage: Dict[str, Any] = {"total_tokens": 0, "cost_estimate": 0.0}
        self.success_count = 0
        self.low_confidence_count = 0

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        
        # If an unhandled exception occurred, log it before writing report
        if exc_type:
            self.errors.append({
                "type": "fatal_error",
                "message": str(exc_val),
                "traceback": str(exc_tb) # You might want to format this better
            })

        self._write_report(duration)

    def add_candidate(self, recipe_id: str, status: str, confidence: float, name: str):
        self.candidates.append({
            "id": recipe_id,
            "name": name,
            "status": status,
            "confidence": confidence
        })
        if status == "valid":
            self.success_count += 1
        elif status == "needs_review":
            self.low_confidence_count += 1

    def add_error(self, error_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        error_entry = {
            "type": error_type,
            "message": message
        }
        if context:
            error_entry["context"] = context
        self.errors.append(error_entry)

    def track_llm_usage(self, tokens: int, cost: float):
        self.llm_usage["total_tokens"] += tokens
        self.llm_usage["cost_estimate"] += cost

    def _write_report(self, duration: float):
        summary = {
            "total_candidates": len(self.candidates),
            "success_count": self.success_count,
            "low_confidence_count": self.low_confidence_count,
            "error_count": len(self.errors),
            "duration_seconds": duration,
            "timestamp": datetime.now().isoformat()
        }

        report = {
            "source_file": str(self.source_path),
            "summary": summary,
            "candidates": self.candidates,
            "errors": self.errors,
            "llm_usage": self.llm_usage
        }

        # Ensure output directory exists
        reports_dir = self.output_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = reports_dir / f"{self.source_path.name}.report.json"
        
        try:
            with open(report_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2)
            logger.info(f"Report written to {report_file}")
        except Exception as e:
            logger.error(f"Failed to write report: {e}")

def enrich_report_with_stats(report: ConversionReport, result: ConversionResult, source_path: Path) -> None:
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
                
    for tip in result.tips:
        if tip.confidence is not None:
            scores.append(tip.confidence)
            if "Tips" not in category_scores:
                category_scores["Tips"] = []
            category_scores["Tips"].append(tip.confidence)

    if scores:
        report.average_confidence = sum(scores) / len(scores)
        
    for cat, cat_scores in category_scores.items():
        if cat_scores:
            report.category_confidence[cat] = sum(cat_scores) / len(cat_scores)
