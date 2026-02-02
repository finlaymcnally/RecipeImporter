import time
import contextlib
from dataclasses import dataclass, field
from typing import Dict, Generator

@dataclass
class TimingStats:
    """Holds timing statistics for a processing run."""
    total_seconds: float = 0.0
    ocr_seconds: float = 0.0
    parsing_seconds: float = 0.0
    writing_seconds: float = 0.0
    
    # Store custom checkpoints
    checkpoints: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, float]:
        """Convert stats to a dictionary suitable for JSON serialization."""
        return {
            "total_seconds": self.total_seconds,
            "ocr_seconds": self.ocr_seconds,
            "parsing_seconds": self.parsing_seconds,
            "writing_seconds": self.writing_seconds,
            "checkpoints": self.checkpoints
        }

class TimingContext:
    """Context manager to measure time and update a TimingStats object."""
    
    def __init__(self, stats: TimingStats, category: str = "total"):
        self.stats = stats
        self.category = category
        self.start_time = 0.0

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.monotonic() - self.start_time
        
        if self.category == "total":
            self.stats.total_seconds += duration
        elif self.category == "ocr":
            self.stats.ocr_seconds += duration
        elif self.category == "parsing":
            self.stats.parsing_seconds += duration
        elif self.category == "writing":
            self.stats.writing_seconds += duration
        else:
            # Accumulate in checkpoints for custom categories
            current = self.stats.checkpoints.get(self.category, 0.0)
            self.stats.checkpoints[self.category] = current + duration

@contextlib.contextmanager
def measure(stats: TimingStats, category: str) -> Generator[None, None, None]:
    """Helper to use TimingContext as a context manager."""
    ctx = TimingContext(stats, category)
    with ctx:
        yield
