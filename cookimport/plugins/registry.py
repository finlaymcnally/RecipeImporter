from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from cookimport.plugins.base import Importer


@dataclass
class ImporterRegistry:
    _importers: dict[str, Importer] = field(default_factory=dict)

    def register(self, importer: Importer) -> None:
        if importer.name in self._importers:
            raise ValueError(f"Importer already registered: {importer.name}")
        self._importers[importer.name] = importer

    def all(self) -> list[Importer]:
        return list(self._importers.values())

    def get(self, name: str) -> Importer | None:
        return self._importers.get(name)

    def best_for_path(self, path: Path) -> tuple[Importer | None, float]:
        best: Importer | None = None
        best_score = 0.0
        for importer in self._importers.values():
            try:
                score = float(importer.detect(path))
            except Exception:
                continue
            if score > best_score:
                best_score = score
                best = importer
        return best, best_score


_registry = ImporterRegistry()


def register(importer: Importer) -> None:
    _registry.register(importer)


def all_importers() -> list[Importer]:
    return _registry.all()


def get_importer(name: str) -> Importer | None:
    return _registry.get(name)


def best_importer_for_path(path: Path) -> tuple[Importer | None, float]:
    return _registry.best_for_path(path)
