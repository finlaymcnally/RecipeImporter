from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

from cookimport.core.models import ConversionResult, MappingConfig, WorkbookInspection

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings


class Importer(Protocol):
    """Interface for source-specific importers.

    Importers are source normalizers: they expose canonical ordered source blocks
    and optional non-authoritative source support. Downstream shared stages own
    recipe versus non-recipe truth.
    """

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
        run_settings: RunSettings | None = None,
    ) -> ConversionResult:
        ...
