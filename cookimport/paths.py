from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
INPUT_ROOT = DATA_ROOT / "input"
OUTPUT_ROOT = DATA_ROOT / "output"
GOLDEN_ROOT = DATA_ROOT / "golden"
GOLDEN_SENT_TO_LABELSTUDIO_ROOT = GOLDEN_ROOT / "sent-to-labelstudio"
GOLDEN_PULLED_FROM_LABELSTUDIO_ROOT = GOLDEN_ROOT / "pulled-from-labelstudio"
GOLDEN_BENCHMARK_ROOT = GOLDEN_ROOT / "benchmark-vs-golden"
HISTORY_ROOT = REPO_ROOT / ".history"
HISTORY_FILENAME = "performance_history.csv"
BOOK_CACHE_ROOT_ENV = "COOKIMPORT_BOOK_CACHE_ROOT"
BOOK_CACHE_ROOT = REPO_ROOT / ".cache" / "cookimport" / "book-cache"


def history_root_for_output(output_root: Path) -> Path:
    """Return canonical history root for a given output root.

    Repo-local outputs write shared history under ``<repo>/.history`` so the
    metrics CSV can be tracked in git. External output roots keep sibling
    history at ``<output_root parent>/.history``.
    """
    resolved_output = output_root.expanduser().resolve(strict=False)
    try:
        resolved_output.relative_to(REPO_ROOT.resolve(strict=False))
    except ValueError:
        return output_root.expanduser().parent / ".history"
    return HISTORY_ROOT


def history_csv_for_output(output_root: Path) -> Path:
    return history_root_for_output(output_root) / HISTORY_FILENAME


def resolve_book_cache_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    env_override = str(os.getenv(BOOK_CACHE_ROOT_ENV, "") or "").strip()
    if env_override:
        return Path(env_override).expanduser()
    return BOOK_CACHE_ROOT
