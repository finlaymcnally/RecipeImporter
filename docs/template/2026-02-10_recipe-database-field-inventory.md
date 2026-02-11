---
summary: "Complete inventory of recipe-related database fields in the current public schema."
read_when:
  - "When you need the full list of recipe attributes and related recipe tables"
  - "When updating recipe save/search/tagging/sub-recipe behavior"
---

# Recipe Database Field Inventory

Source of truth used: `db/schema.snapshot.sql`.

## Scope

This note lists all recipe-related fields in the `public` schema:
- Canonical recipe content
- Step + ingredient line content
- Recipe tags/pairings
- Derived recipe caches
- User recipe personalization/history
- Week-scoped planned recipe drafts
- Import recipe staging row

## Enums Used By Recipe Data

- `public.quantity_kind_t`: `exact | approximate | unquantified`
- `public.grams_calc_status_t`: `ok | unquantified | missing_measure | invalid_input | no_density`

## `public.recipes` (canonical recipe record)

- `id uuid` (PK, default `gen_random_uuid()`)
- `owner_id uuid` (FK -> `auth.users.id`, required)
- `title text` (required)
- `slug text` (required)
- `slug_norm text` (generated: `normalize_key(slug)`)
- `yield_units double precision` (default `1`, check `>= 1`)
- `yield_phrase text` (nullable)
- `yield_unit_name text` (nullable)
- `yield_detail text` (nullable)
- `description text` (nullable)
- `notes text` (nullable)
- `image_url text` (nullable)
- `variants text[]` (nullable)
- `source text` (required, default `'manual'`)
- `import_batch_id uuid` (nullable)
- `source_detail_json jsonb` (nullable)
- `prep_time_minutes integer` (nullable, check `>= 0`)
- `cook_time_minutes integer` (nullable, check `>= 0`)
- `total_time_minutes integer` (nullable, check `>= 0`)
- `active_time_minutes integer` (nullable, check `>= 0`)
- `make_ahead_hours integer` (nullable, check `>= 0`)
- `complexity_score smallint` (nullable, check `1..5`)
- `cleanup_level text` (nullable, check `light|medium|heavy`)
- `attention_level text` (nullable, check `set_and_forget|occasional|constant`)
- `spice_level smallint` (nullable, check `0..5`)
- `max_oven_temp_f integer` (nullable, check `>= 0`)
- `nutrition_complete boolean` (required, default `false`)
- `nutrition_breakdown_json jsonb` (nullable)
- `calories_kcal_total numeric` (nullable)
- `calories_kcal_per_unit numeric` (nullable)
- `protein_g_total numeric` (nullable)
- `protein_g_per_unit numeric` (nullable)
- `carbs_g_total numeric` (nullable)
- `carbs_g_per_unit numeric` (nullable)
- `fat_g_total numeric` (nullable)
- `fat_g_per_unit numeric` (nullable)
- `fiber_g_total numeric` (nullable)
- `fiber_g_per_unit numeric` (nullable)
- `sugar_g_total numeric` (nullable)
- `sugar_g_per_unit numeric` (nullable)
- `sodium_mg_total numeric` (nullable)
- `sodium_mg_per_unit numeric` (nullable)
- `saturated_fat_g_total numeric` (nullable)
- `saturated_fat_g_per_unit numeric` (nullable)
- `search_text text` (required, default empty string; projection text)
- `search_vector tsvector` (generated from `search_text`)
- `previous_version_json jsonb` (nullable; revert snapshot)
- `archived_at timestamptz` (nullable; soft archive marker)
- `original_recipe_id uuid` (nullable FK -> `recipes.id`, on delete set null)
- `forked_from_recipe_id uuid` (nullable FK -> `recipes.id`, on delete set null)
- `created_at timestamptz` (required, default `now()`)
- `updated_at timestamptz` (required, default `now()`)

Notes:
- Unique index exists on `slug_norm` (`recipes_slug_norm_idx`).
- PK: `recipes_pkey (id)`.

## `public.recipe_steps` (ordered instructions)

- `id uuid` (PK, default `gen_random_uuid()`)
- `recipe_id uuid` (FK -> `recipes.id`, required, on delete cascade)
- `step_number integer` (required, check `>= 1`)
- `instruction text` (required)
- `created_at timestamptz` (required, default `now()`)
- `updated_at timestamptz` (required, default `now()`)

Notes:
- Unique per recipe order: `UNIQUE (recipe_id, step_number)`.

## `public.step_ingredient_lines` (ingredients or linked sub-recipes per step)

- `id uuid` (PK, default `gen_random_uuid()`)
- `step_id uuid` (FK -> `recipe_steps.id`, required, on delete cascade)
- `ingredient_id uuid` (nullable FK -> `ingredients.id`, on delete restrict)
- `linked_recipe_id uuid` (nullable FK -> `recipes.id`, on delete restrict)
- `is_optional boolean` (required, default `false`)
- `quantity_kind quantity_kind_t` (required, default `exact`)
- `raw_text text` (nullable)
- `input_qty double precision` (nullable, check `> 0` when set)
- `input_unit_id uuid` (nullable FK -> `units.id`)
- `note text` (nullable)
- `preparation text` (nullable)
- `grams_equiv double precision` (nullable, check `> 0` when set)
- `grams_calc_status grams_calc_status_t` (required, default `invalid_input`)
- `line_order integer` (required, check `>= 0`)
- `substitute_ingredient_id uuid` (nullable FK -> `ingredients.id`, on delete restrict)
- `created_at timestamptz` (required, default `now()`)
- `updated_at timestamptz` (required, default `now()`)

Constraints:
- Exactly one ref must be present: `(ingredient_id IS NOT NULL) XOR (linked_recipe_id IS NOT NULL)`.
- If `grams_calc_status = 'ok'`, then `grams_equiv` must be non-null.
- If `grams_equiv` is non-null, `grams_calc_status` must be `ok`.
- Unique per step order: `UNIQUE (step_id, line_order)`.

## `public.recipe_tags` and `public.recipe_tag_assignments`

`recipe_tags` fields:
- `id uuid` (PK)
- `key_norm text` (unique)
- `display_name text`
- `category_id uuid` (nullable FK -> `tag_categories.id`)
- `sort_order integer` (default `0`)
- `created_at timestamptz`

`recipe_tag_assignments` fields:
- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `tag_id uuid` (FK -> `recipe_tags.id`, on delete cascade)
- `created_at timestamptz`

Notes:
- Join PK is composite: `(recipe_id, tag_id)`.

## `public.recipe_pairings` (pairs-well-with links)

- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `paired_recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `created_at timestamptz` (default `now()`)

Constraints:
- Composite PK: `(recipe_id, paired_recipe_id)`.
- Check: `recipe_id <> paired_recipe_id` (no self-pair).

## Derived/Projection Tables

`public.recipe_ingredients_cache`:
- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `pantry_equiv_group_id uuid`
- `is_optional boolean`
- `ingredient_ids uuid[]` (default empty array)
- `updated_at timestamptz`
- PK: `(recipe_id, pantry_equiv_group_id)`

`public.recipe_stats_cache`:
- `recipe_id uuid` (PK, FK -> `recipes.id`, on delete cascade)
- `step_count integer` (default `0`)
- `ingredient_count integer` (default `0`)
- `unique_ingredient_count integer` (default `0`)
- `updated_at timestamptz`

## User-Specific Recipe Tables

`public.user_recipe_favorites`:
- `user_id uuid` (FK -> `auth.users.id`, on delete cascade)
- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `created_at timestamptz`
- PK: `(user_id, recipe_id)`

`public.user_recipe_ratings`:
- `user_id uuid` (FK -> `auth.users.id`, on delete cascade)
- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `rating smallint` (required, check `1..5`)
- `created_at timestamptz`
- `updated_at timestamptz`
- PK: `(user_id, recipe_id)`

`public.user_cook_log`:
- `id uuid` (PK)
- `user_id uuid` (FK -> `auth.users.id`, on delete cascade)
- `recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `cooked_at timestamptz` (default `now()`)
- `notes text` (nullable)
- `servings_made double precision` (nullable)
- `rating smallint` (nullable, check `1..5` when set)
- `created_at timestamptz`

## Week-Scoped Planned Recipe Drafts

`public.meal_plan_planned_recipes`:
- `id uuid` (PK)
- `user_id uuid` (FK -> `auth.users.id`, on delete cascade)
- `week_start_date date`
- `base_recipe_id uuid` (FK -> `recipes.id`, on delete cascade)
- `draft_json jsonb` (nullable recipe draft payload)
- `nutrition_json jsonb` (nullable derived nutrition payload)
- `created_at timestamptz`
- `updated_at timestamptz`

Unique constraint:
- `(user_id, week_start_date, base_recipe_id)`

## Import-Side Recipe Staging Row

`public.import_recipe_staging`:
- `id uuid` (PK)
- `import_batch_id uuid` (nullable FK -> `import_batches.id`, on delete set null)
- `status text` (required, check `needs_review|approved|rejected`)
- `raw_recipe_json jsonb` (required; imported recipe payload before approval)
- `resolver_report_json jsonb` (nullable)
- `created_at timestamptz`
- `updated_at timestamptz`

---

If this inventory drifts from reality, regenerate and review `db/schema.snapshot.sql` first.
