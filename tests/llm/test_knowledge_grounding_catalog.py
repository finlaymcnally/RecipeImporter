from __future__ import annotations

from scripts.sync_cookbook_tag_catalog import build_catalog_payload

from cookimport.llm.knowledge_tag_catalog import load_knowledge_tag_catalog


def test_checked_in_knowledge_tag_catalog_loads() -> None:
    catalog = load_knowledge_tag_catalog()

    assert len(catalog.categories) == 21
    assert len(catalog.tags) == 203
    assert catalog.has_category_key("ingredients") is True
    assert catalog.has_category_key("techniques") is True
    assert catalog.has_tag_key("emulsify") is True


def test_sync_builder_parses_sql_seed_shape() -> None:
    sql_text = """
-- Generated: 2026-01-28T04:58:49.080Z
INSERT INTO public.tag_categories (id, key_norm, display_name, sort_order, is_multi_select)
VALUES
  ('cat-1', 'techniques', 'Techniques', 10, true),
  ('cat-2', 'flavor-profile', 'Flavor Profile', 20, true)
ON CONFLICT (key_norm) DO UPDATE SET
  display_name = EXCLUDED.display_name;

INSERT INTO public.recipe_tags (id, key_norm, display_name, category_id, sort_order)
VALUES
  ('tag-1', 'emulsify', 'Emulsify', 'cat-1', 1),
  ('tag-2', 'bright', 'Bright', 'cat-2', 2)
ON CONFLICT (key_norm) DO UPDATE SET
  display_name = EXCLUDED.display_name;
"""

    payload = build_catalog_payload(
        sql_text=sql_text,
        source_sql_path="/tmp/catalog.sql",
    )

    assert payload["source_sql_generated_at"] == "2026-01-28T04:58:49.080Z"
    assert payload["category_count"] == 2
    assert payload["tag_count"] == 2
    assert payload["categories"][0]["key"] == "techniques"
    assert payload["tags"] == [
        {
            "category_key": "flavor-profile",
            "display_name": "Bright",
            "id": "tag-2",
            "key": "bright",
            "sort_order": 2,
        },
        {
            "category_key": "techniques",
            "display_name": "Emulsify",
            "id": "tag-1",
            "key": "emulsify",
            "sort_order": 1,
        },
    ]
