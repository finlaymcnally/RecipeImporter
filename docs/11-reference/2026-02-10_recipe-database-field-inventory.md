---
summary: "2026-02-10 snapshot of recipe-related database fields from the public schema."
read_when:
  - "When you need the full list of recipe attributes and related recipe tables"
  - "When updating recipe save/search/tagging/sub-recipe behavior"
---
## Database Model (Consolidated Inventory)
Snapshot date: `2026-02-10`.
Source of truth is the live Postgres schema; this repo does not currently include `db/schema.snapshot.sql`, so treat this file as a dated reference snapshot rather than a guaranteed current schema dump.

### Enums
- `public.quantity_kind_t`: `exact | approximate | unquantified`
- `public.grams_calc_status_t`: `ok | unquantified | missing_measure | invalid_input | no_density`

### `public.recipes`
- `id uuid` (PK)
- `owner_id uuid` (required)
- `title text` (required)
- `slug text` (required)
- `slug_norm text` (generated)
- `yield_units double precision` (default `1`, check `>= 1`)
- `yield_phrase text`
- `yield_unit_name text`
- `yield_detail text`
- `description text`
- `notes text`
- `image_url text`
- `variants text[]`
- `source text` (default `manual`)
- `import_batch_id uuid`
- `source_detail_json jsonb`
- `prep_time_minutes integer` (check `>= 0`)
- `cook_time_minutes integer` (check `>= 0`)
- `total_time_minutes integer` (check `>= 0`)
- `active_time_minutes integer` (check `>= 0`)
- `make_ahead_hours integer` (check `>= 0`)
- `complexity_score smallint` (check `1..5`)
- `cleanup_level text` (`light|medium|heavy`)
- `attention_level text` (`set_and_forget|occasional|constant`)
- `spice_level smallint` (check `0..5`)
- `max_oven_temp_f integer` (check `>= 0`)
- `nutrition_complete boolean` (default `false`)
- `nutrition_breakdown_json jsonb`
- Nutrition totals/per-unit columns:
  `calories_kcal_total`, `calories_kcal_per_unit`, `protein_g_total`, `protein_g_per_unit`, `carbs_g_total`, `carbs_g_per_unit`, `fat_g_total`, `fat_g_per_unit`, `fiber_g_total`, `fiber_g_per_unit`, `sugar_g_total`, `sugar_g_per_unit`, `sodium_mg_total`, `sodium_mg_per_unit`, `saturated_fat_g_total`, `saturated_fat_g_per_unit`
- `search_text text` (projection)
- `search_vector tsvector` (generated)
- `previous_version_json jsonb`
- `archived_at timestamptz`
- `original_recipe_id uuid`
- `forked_from_recipe_id uuid`
- `created_at timestamptz`
- `updated_at timestamptz`

### `public.recipe_steps`
- `id uuid` (PK)
- `recipe_id uuid` (FK, cascade delete)
- `step_number integer` (check `>= 1`)
- `instruction text`
- `created_at timestamptz`
- `updated_at timestamptz`
- Unique: `(recipe_id, step_number)`

### `public.step_ingredient_lines`
- `id uuid` (PK)
- `step_id uuid` (FK, cascade delete)
- `ingredient_id uuid` (nullable FK)
- `linked_recipe_id uuid` (nullable FK)
- `is_optional boolean`
- `quantity_kind quantity_kind_t`
- `raw_text text`
- `input_qty double precision` (check `> 0` when set)
- `input_unit_id uuid` (nullable FK)
- `note text`
- `preparation text`
- `grams_equiv double precision`
- `grams_calc_status grams_calc_status_t`
- `line_order integer` (check `>= 0`)
- `substitute_ingredient_id uuid` (nullable FK)
- `created_at timestamptz`
- `updated_at timestamptz`

Constraints:
- Exactly one reference required: `ingredient_id XOR linked_recipe_id`.
- `grams_calc_status=ok` requires non-null `grams_equiv`.
- Non-null `grams_equiv` must be `> 0`.
- Non-null `grams_equiv` requires `grams_calc_status=ok`.
- Unique: `(step_id, line_order)`.

### Tags/pairings
- `public.recipe_tag_categories`
  - `id`, `key_norm` (unique), `display_name`, `sort_order`, `created_at`
- `public.recipe_tags`
  - `id`, `key_norm` (unique), `display_name`, `category_id`, `sort_order`, `created_at`
- `public.recipe_tag_assignments`
  - `recipe_id`, `tag_id`, `created_at`
  - PK `(recipe_id, tag_id)`
- `public.recipe_pairings`
  - `recipe_id`, `paired_recipe_id`, `created_at`
  - PK `(recipe_id, paired_recipe_id)`
  - check `recipe_id <> paired_recipe_id`
