from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

_CATALOG_PATH = Path(__file__).with_name("knowledge_tag_catalog.json")
_KEY_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_knowledge_tag_key(value: object) -> str:
    cleaned = _KEY_NORMALIZE_PATTERN.sub("-", str(value or "").strip().lower())
    return cleaned.strip("-")


def empty_grounding_payload() -> dict[str, Any]:
    return {
        "tag_keys": [],
        "category_keys": [],
        "proposed_tags": [],
    }


@dataclass(frozen=True, slots=True)
class KnowledgeTagCategory:
    key: str
    display_name: str
    sort_order: int
    is_multi_select: bool


@dataclass(frozen=True, slots=True)
class KnowledgeTag:
    key: str
    display_name: str
    category_key: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class KnowledgeTagCatalog:
    catalog_version: str
    categories: tuple[KnowledgeTagCategory, ...]
    tags: tuple[KnowledgeTag, ...]

    def has_category_key(self, key: object) -> bool:
        return normalize_knowledge_tag_key(key) in self.category_by_key

    def has_tag_key(self, key: object) -> bool:
        return normalize_knowledge_tag_key(key) in self.tag_by_key

    @property
    def category_by_key(self) -> dict[str, KnowledgeTagCategory]:
        return {category.key: category for category in self.categories}

    @property
    def tag_by_key(self) -> dict[str, KnowledgeTag]:
        return {tag.key: tag for tag in self.tags}

    def task_scope_payload(self) -> dict[str, Any]:
        return {
            "catalog_version": self.catalog_version,
            "categories": [
                {
                    "key": category.key,
                    "display_name": category.display_name,
                }
                for category in self.categories
            ],
            "tags": [
                {
                    "key": tag.key,
                    "display_name": tag.display_name,
                    "category_key": tag.category_key,
                }
                for tag in self.tags
            ],
        }


def _catalog_from_payload(payload: Mapping[str, Any]) -> KnowledgeTagCatalog:
    categories = tuple(
        KnowledgeTagCategory(
            key=str(row.get("key") or "").strip(),
            display_name=str(row.get("display_name") or "").strip(),
            sort_order=int(row.get("sort_order") or 0),
            is_multi_select=bool(row.get("is_multi_select")),
        )
        for row in (payload.get("categories") or [])
        if isinstance(row, Mapping) and str(row.get("key") or "").strip()
    )
    tags = tuple(
        KnowledgeTag(
            key=str(row.get("key") or "").strip(),
            display_name=str(row.get("display_name") or "").strip(),
            category_key=str(row.get("category_key") or "").strip(),
            sort_order=int(row.get("sort_order") or 0),
        )
        for row in (payload.get("tags") or [])
        if isinstance(row, Mapping)
        and str(row.get("key") or "").strip()
        and str(row.get("category_key") or "").strip()
    )
    return KnowledgeTagCatalog(
        catalog_version=str(payload.get("catalog_version") or "").strip()
        or "cookbook-tag-catalog",
        categories=categories,
        tags=tags,
    )


@lru_cache(maxsize=1)
def load_knowledge_tag_catalog_payload() -> dict[str, Any]:
    payload = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{_CATALOG_PATH} must contain one JSON object")
    return dict(payload)


@lru_cache(maxsize=1)
def load_knowledge_tag_catalog() -> KnowledgeTagCatalog:
    return _catalog_from_payload(load_knowledge_tag_catalog_payload())
