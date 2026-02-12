"""Offline prediction-run builder for benchmark suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from cookimport.labelstudio.ingest import generate_pred_run_artifacts


def build_pred_run_for_source(
    source_path: Path,
    out_dir: Path,
    *,
    config: dict | None = None,
    progress_callback: Callable[[str], None] | None = None,
    **kwargs: Any,
) -> Path:
    """Build a prediction run for a single source file, fully offline.

    Returns the pred-run directory path.
    """
    cfg = config or {}
    result = generate_pred_run_artifacts(
        path=source_path,
        output_dir=out_dir,
        pipeline=cfg.get("pipeline", "auto"),
        chunk_level="both",
        task_scope="pipeline",
        context_window=1,
        segment_blocks=cfg.get("segment_blocks", 40),
        segment_overlap=cfg.get("segment_overlap", 5),
        workers=cfg.get("workers", 1),
        pdf_split_workers=cfg.get("pdf_split_workers", 1),
        epub_split_workers=cfg.get("epub_split_workers", 1),
        pdf_pages_per_job=cfg.get("pdf_pages_per_job", 50),
        epub_spine_items_per_job=cfg.get("epub_spine_items_per_job", 10),
        progress_callback=progress_callback,
        **kwargs,
    )
    return Path(result["run_root"])
