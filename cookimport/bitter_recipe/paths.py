from __future__ import annotations

import re
from pathlib import Path

from cookimport.paths import DATA_ROOT, INPUT_ROOT, REPO_ROOT
from cookimport.plugins import epub, excel, paprika, pdf, recipesage, text, webschema  # noqa: F401
from cookimport.plugins.registry import best_importer_for_path


BITTER_RECIPE_SETTINGS_PATH = REPO_ROOT / "bitter-recipe.json"
BITTER_RECIPE_ROOT = DATA_ROOT / "bitter-recipe"
BITTER_RECIPE_SENT_ROOT = BITTER_RECIPE_ROOT / "sent-to-labelstudio"
BITTER_RECIPE_PULLED_ROOT = BITTER_RECIPE_ROOT / "pulled-from-labelstudio"
BITTER_RECIPE_LEDGER_ROOT = BITTER_RECIPE_ROOT / "ledger"
BITTER_RECIPE_LEDGER_PATH = BITTER_RECIPE_LEDGER_ROOT / "books.json"

_SLUGIFY_RE = re.compile(r"[^a-z0-9]+")


def source_slug_for_path(path: Path | str) -> str:
    candidate = Path(path)
    stem = candidate.stem.strip().lower()
    slug = _SLUGIFY_RE.sub("_", stem).strip("_")
    return slug or "unknown"


def bitter_recipe_root(root: Path | str | None = None) -> Path:
    return Path(root).expanduser() if root is not None else BITTER_RECIPE_ROOT


def bitter_recipe_sent_root(root: Path | str | None = None) -> Path:
    return bitter_recipe_root(root) / "sent-to-labelstudio"


def bitter_recipe_pulled_root(root: Path | str | None = None) -> Path:
    return bitter_recipe_root(root) / "pulled-from-labelstudio"


def bitter_recipe_ledger_root(root: Path | str | None = None) -> Path:
    return bitter_recipe_root(root) / "ledger"


def bitter_recipe_ledger_path(root: Path | str | None = None) -> Path:
    return bitter_recipe_ledger_root(root) / "books.json"


def list_importable_sources(input_root: Path | str | None = None) -> list[Path]:
    folder = Path(input_root).expanduser() if input_root is not None else INPUT_ROOT
    if not folder.exists():
        return []
    files: list[Path] = []
    for file_path in folder.glob("*"):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        _, score = best_importer_for_path(file_path)
        if score > 0:
            files.append(file_path)
    return sorted(files)
