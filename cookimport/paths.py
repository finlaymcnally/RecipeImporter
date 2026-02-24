from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "data"
INPUT_ROOT = DATA_ROOT / "input"
OUTPUT_ROOT = DATA_ROOT / "output"
GOLDEN_ROOT = DATA_ROOT / "golden"
GOLDEN_SENT_TO_LABELSTUDIO_ROOT = GOLDEN_ROOT / "sent-to-labelstudio"
GOLDEN_PULLED_FROM_LABELSTUDIO_ROOT = GOLDEN_ROOT / "pulled-from-labelstudio"
GOLDEN_BENCHMARK_ROOT = GOLDEN_ROOT / "benchmark-vs-golden"
HISTORY_ROOT = DATA_ROOT / ".history"
HISTORY_FILENAME = "performance_history.csv"


def history_root_for_output(output_root: Path) -> Path:
    """History now lives one level above output roots."""
    return output_root.expanduser().parent / ".history"


def history_csv_for_output(output_root: Path) -> Path:
    return history_root_for_output(output_root) / HISTORY_FILENAME
