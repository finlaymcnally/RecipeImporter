"""Idempotent DB writes for tag assignments."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def insert_tag_assignments(db_url: str, recipe_id: str, tag_ids: list[str]) -> int:
    """Insert tag assignments idempotently. Returns count of newly inserted rows."""
    if not tag_ids:
        return 0

    try:
        import psycopg
    except ImportError:
        raise RuntimeError(
            "psycopg is required for DB access. Install with: pip install 'psycopg[binary]'"
        )

    inserted = 0
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for tag_id in tag_ids:
                cur.execute(
                    """
                    INSERT INTO public.recipe_tag_assignments (recipe_id, tag_id, created_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (recipe_id, tag_id) DO NOTHING
                    """,
                    (recipe_id, tag_id),
                )
                inserted += cur.rowcount
        conn.commit()

    logger.info("Inserted %d/%d tag assignments for recipe %s", inserted, len(tag_ids), recipe_id)
    return inserted


def verify_tag_ids_exist(db_url: str, tag_ids: list[str]) -> list[str]:
    """Check that all tag_ids exist in public.recipe_tags. Returns missing IDs."""
    if not tag_ids:
        return []

    try:
        import psycopg
    except ImportError:
        raise RuntimeError(
            "psycopg is required for DB access. Install with: pip install 'psycopg[binary]'"
        )

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM public.recipe_tags WHERE id = ANY(%s)",
                (tag_ids,),
            )
            found = {str(row[0]) for row in cur.fetchall()}

    return [tid for tid in tag_ids if tid not in found]
