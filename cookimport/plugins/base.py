from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from cookimport.core.models import ConversionResult, MappingConfig, WorkbookInspection


class Importer(Protocol):
    """Interface for source-specific importers."""

    name: str

    def detect(self, path: Path) -> float:
        ...

    def inspect(self, path: Path) -> WorkbookInspection:
        ...

    def convert(
        self,
        path: Path,
        mapping: MappingConfig | None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> ConversionResult:
        ...
