from __future__ import annotations

import sys

from cookimport.cli import DEFAULT_INPUT, DEFAULT_OUTPUT, _fail, _load_settings, app, stage


def main() -> None:
    args = sys.argv[1:]
    settings = _load_settings()
    common_args = {
        "out": DEFAULT_OUTPUT,
        "mapping": None,
        "overrides": None,
        "workers": settings.get("workers", 7),
        "pdf_split_workers": settings.get("pdf_split_workers", 7),
        "epub_split_workers": settings.get("epub_split_workers", 7),
        "ocr_device": settings.get("ocr_device", "auto"),
        "ocr_batch_size": settings.get("ocr_batch_size", 1),
        "pdf_pages_per_job": settings.get("pdf_pages_per_job", 50),
        "epub_spine_items_per_job": settings.get("epub_spine_items_per_job", 10),
        "warm_models": settings.get("warm_models", False),
    }
    if not args:
        stage(path=DEFAULT_INPUT, limit=None, **common_args)
        return
    if len(args) == 1:
        try:
            limit = int(args[0])
        except ValueError:
            limit = None
        if limit is not None:
            if limit <= 0:
                _fail("Limit must be a positive integer.")
            stage(path=DEFAULT_INPUT, limit=limit, **common_args)
            return
    app()
