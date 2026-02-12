"""Tag catalog models and loaders.

The catalog is the source of truth for allowed tags. Rules are keyed by
tag ``key_norm`` so they naturally adapt when the catalog changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TagCategory:
    id: str  # uuid string
    key_norm: str
    display_name: str
    sort_order: int = 0


@dataclass(frozen=True)
class Tag:
    id: str  # uuid string
    key_norm: str
    display_name: str
    category_id: str  # uuid string
    sort_order: int = 0


@dataclass
class TagCatalog:
    categories_by_id: dict[str, TagCategory] = field(default_factory=dict)
    categories_by_key: dict[str, TagCategory] = field(default_factory=dict)
    tags_by_id: dict[str, Tag] = field(default_factory=dict)
    tags_by_key: dict[str, Tag] = field(default_factory=dict)
    tags_by_category_id: dict[str, list[Tag]] = field(default_factory=dict)

    def get_tag_id(self, key_norm: str) -> str | None:
        tag = self.tags_by_key.get(key_norm)
        return tag.id if tag else None

    def get_category_key(self, category_id: str) -> str | None:
        cat = self.categories_by_id.get(category_id)
        return cat.key_norm if cat else None

    def category_key_for_tag(self, tag_key_norm: str) -> str | None:
        tag = self.tags_by_key.get(tag_key_norm)
        if tag is None:
            return None
        return self.get_category_key(tag.category_id)

    @property
    def category_count(self) -> int:
        return len(self.categories_by_id)

    @property
    def tag_count(self) -> int:
        return len(self.tags_by_id)


def _build_catalog(categories: list[TagCategory], tags: list[Tag]) -> TagCatalog:
    catalog = TagCatalog()
    for cat in categories:
        catalog.categories_by_id[cat.id] = cat
        catalog.categories_by_key[cat.key_norm] = cat
    for tag in tags:
        catalog.tags_by_id[tag.id] = tag
        catalog.tags_by_key[tag.key_norm] = tag
        catalog.tags_by_category_id.setdefault(tag.category_id, []).append(tag)
    # Sort tags within each category by sort_order
    for tag_list in catalog.tags_by_category_id.values():
        tag_list.sort(key=lambda t: t.sort_order)
    return catalog


# ---------------------------------------------------------------------------
# DB loader
# ---------------------------------------------------------------------------

def load_catalog_from_db(db_url: str) -> TagCatalog:
    """Load the full tag catalog from Postgres."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError(
            "psycopg is required for DB access. Install with: pip install 'psycopg[binary]'"
        )

    categories: list[TagCategory] = []
    tags: list[Tag] = []

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, key_norm, display_name, sort_order "
                "FROM public.recipe_tag_categories ORDER BY sort_order"
            )
            for row in cur.fetchall():
                categories.append(TagCategory(
                    id=str(row[0]),
                    key_norm=row[1],
                    display_name=row[2],
                    sort_order=row[3] or 0,
                ))

            cur.execute(
                "SELECT id, key_norm, display_name, category_id, sort_order "
                "FROM public.recipe_tags ORDER BY sort_order"
            )
            for row in cur.fetchall():
                tags.append(Tag(
                    id=str(row[0]),
                    key_norm=row[1],
                    display_name=row[2],
                    category_id=str(row[3]),
                    sort_order=row[4] or 0,
                ))

    catalog = _build_catalog(categories, tags)
    logger.info("Loaded %d categories, %d tags from DB", catalog.category_count, catalog.tag_count)
    return catalog


# ---------------------------------------------------------------------------
# JSON loader / exporter
# ---------------------------------------------------------------------------

def _catalog_fingerprint(payload: dict[str, Any]) -> str:
    """SHA-256 over a deterministic JSON serialization."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def export_catalog_to_json(catalog: TagCatalog, path: Path) -> str:
    """Write the catalog to a JSON file. Returns the fingerprint."""
    categories_list = sorted(
        [
            {"id": c.id, "key_norm": c.key_norm, "display_name": c.display_name, "sort_order": c.sort_order}
            for c in catalog.categories_by_id.values()
        ],
        key=lambda c: c["sort_order"],
    )
    tags_list = sorted(
        [
            {
                "id": t.id,
                "key_norm": t.key_norm,
                "display_name": t.display_name,
                "category_id": t.category_id,
                "sort_order": t.sort_order,
            }
            for t in catalog.tags_by_id.values()
        ],
        key=lambda t: t["sort_order"],
    )

    data_for_hash = {"categories": categories_list, "tags": tags_list}
    fingerprint = _catalog_fingerprint(data_for_hash)

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "category_count": catalog.category_count,
        "tag_count": catalog.tag_count,
        "catalog_fingerprint": fingerprint,
        "categories": categories_list,
        "tags": tags_list,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    logger.info("Exported catalog to %s (fingerprint=%s)", path, fingerprint[:12])
    return fingerprint


def load_catalog_from_json(path: Path) -> TagCatalog:
    """Load the tag catalog from a JSON export file."""
    with open(path) as f:
        data = json.load(f)

    categories = [
        TagCategory(
            id=c["id"],
            key_norm=c["key_norm"],
            display_name=c["display_name"],
            sort_order=c.get("sort_order", 0),
        )
        for c in data["categories"]
    ]
    tags = [
        Tag(
            id=t["id"],
            key_norm=t["key_norm"],
            display_name=t["display_name"],
            category_id=t["category_id"],
            sort_order=t.get("sort_order", 0),
        )
        for t in data["tags"]
    ]

    catalog = _build_catalog(categories, tags)
    fp = data.get("catalog_fingerprint", "unknown")
    logger.info(
        "Loaded %d categories, %d tags from %s (fingerprint=%s)",
        catalog.category_count, catalog.tag_count, path, fp[:12],
    )
    return catalog


def get_catalog_fingerprint_from_json(path: Path) -> str:
    """Read just the fingerprint from a catalog JSON without loading everything."""
    with open(path) as f:
        data = json.load(f)
    return data.get("catalog_fingerprint", "unknown")
