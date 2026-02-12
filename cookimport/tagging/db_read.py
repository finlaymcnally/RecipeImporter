"""Fetch recipe data from DB and build RecipeSignalPack."""

from __future__ import annotations

import logging

from cookimport.tagging.signals import RecipeSignalPack

logger = logging.getLogger(__name__)


def fetch_recipe_bundle(db_url: str, recipe_id: str) -> RecipeSignalPack:
    """Fetch recipe + steps + ingredient lines from DB and return a RecipeSignalPack."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError(
            "psycopg is required for DB access. Install with: pip install 'psycopg[binary]'"
        )

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Recipe-level fields
            cur.execute(
                """
                SELECT title, description, notes,
                       prep_time_minutes, cook_time_minutes, total_time_minutes,
                       yield_phrase, max_oven_temp_f, spice_level,
                       attention_level, cleanup_level
                FROM public.recipes
                WHERE id = %s
                """,
                (recipe_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"Recipe {recipe_id} not found")

            title, description, notes = row[0] or "", row[1] or "", row[2] or ""
            prep_time = row[3]
            cook_time = row[4]
            total_time = row[5]
            yield_phrase = row[6]
            max_oven_temp_f = row[7]
            spice_level = row[8]
            attention_level = row[9]
            cleanup_level = row[10]

            # Steps (ordered)
            cur.execute(
                """
                SELECT id, instruction
                FROM public.recipe_steps
                WHERE recipe_id = %s
                ORDER BY step_number
                """,
                (recipe_id,),
            )
            step_rows = cur.fetchall()
            instructions = [r[1] for r in step_rows if r[1]]
            step_ids = [str(r[0]) for r in step_rows]

            # Ingredient lines (for all steps, ordered)
            ingredients: list[str] = []
            if step_ids:
                cur.execute(
                    """
                    SELECT raw_text
                    FROM public.step_ingredient_lines
                    WHERE step_id = ANY(%s)
                    ORDER BY step_id, line_order
                    """,
                    (step_ids,),
                )
                ingredients = [r[0] for r in cur.fetchall() if r[0]]

    return RecipeSignalPack(
        recipe_id=recipe_id,
        title=title,
        description=description,
        notes=notes,
        ingredients=ingredients,
        instructions=instructions,
        prep_time_minutes=prep_time,
        cook_time_minutes=cook_time,
        total_time_minutes=total_time,
        yield_phrase=yield_phrase,
        max_oven_temp_f=max_oven_temp_f,
        spice_level=spice_level,
        attention_level=attention_level,
        cleanup_level=cleanup_level,
    )
