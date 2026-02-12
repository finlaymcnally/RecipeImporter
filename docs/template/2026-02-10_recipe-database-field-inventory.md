---
summary: "Complete inventory of recipe-related database fields in the current public schema."
read_when:
  - "When you need the full list of recipe attributes and related recipe tables"
  - "When updating recipe save/search/tagging/sub-recipe behavior"
---
## Database Model (Consolidated Inventory)
Source of truth: `db/schema.snapshot.sql`.

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
- `public.recipe_tags`
  - `id`, `key_norm` (unique), `display_name`, `category_id`, `sort_order`, `created_at`
- `public.recipe_tag_assignments`
  - `recipe_id`, `tag_id`, `created_at`
  - PK `(recipe_id, tag_id)`
- `public.recipe_pairings`
  - `recipe_id`, `paired_recipe_id`, `created_at`
  - PK `(recipe_id, paired_recipe_id)`
  - check `recipe_id <> paired_recipe_id`

### Seeded tag categories + ideas (current catalog)
Source: `supabase/seeds/catalog.sql` (generated seed; mirrored into `supabase/seed.sql`).

- Seeded categories: `20`
- Seeded recipe tags: `203`
- **Cooking Style** (`cooking-style`) [9]: Air Fryer, Grill, Instant Pot, No-Cook, One-Pot, Oven Only, Sheet Pan, Slow Cooker, Stovetop Only
- **Effort Level** (`effort`) [8]: Advanced Techniques, Beginner Friendly, Hands-Off Friendly, Minimal Chopping, Minimal Prep, Quick, Quick Cleanup, Weekend
- **Storage & Meal Prep** (`storage`) [5]: Batch Cooking, Better Next Day, Freezer Friendly, Make Ahead, Meal Prep Friendly
- **Meal Type** (`meal`) [0]
- **Meal Type** (`meal-type`) [6]: Breakfast, Brunch, Dessert, Dinner, Lunch, Snack
- **Course** (`course`) [7]: Appetizer, Condiment, Dressing, Drink, Main Dish, Sauce, Side Dish
- **Dish Type** (`dish-type`) [14]: Baked Goods, Bowl, Casserole, Curry, Pasta, Pizza, Rice Dish, Salad, Sandwich, Soup, Stew, Stir Fry, Tacos, Wrap
- **Occasion** (`occasion`) [9]: BBQ/Cookout, Date Night, Dinner Party, Game Day, Packable/Lunchbox, Picnic, Potluck, Special Occasion, Weeknight
- **Holiday** (`holiday`) [9]: Christmas, Diwali, Easter, Fourth of July, Halloween, Hanukkah, Lunar New Year, Thanksgiving, Valentine's Day
- **Season** (`season`) [5]: Fall, Spring, Summer, Winter, Year Round
- **Vibe** (`vibe`) [6]: Comfort Food, Crowd Pleaser, Healthy, Indulgent, Kid Friendly, Light & Fresh
- **Cuisine** (`cuisine`) [19]: African, American, Cajun/Creole, Caribbean, Chinese, French, Fusion, Greek, Indian, Italian, Japanese, Korean, Latin American, Mediterranean, Mexican, Middle Eastern, Spanish, Thai, Vietnamese
- **Flavor Profile** (`flavor-profile`) [13]: Bright, Creamy, Crispy/Crunchy, Earthy, Herby, Mild, Rich, Savory, Smoky, Spicy, Sweet, Tangy, Umami-Forward
- **Heat Source** (`heat-source`) [5]: Black Pepper Heat, Chili/Pepper Heat, Ginger Heat, Horseradish/Wasabi Heat, No Heat
- **Dietary** (`dietary`) [19]: Dairy-Free, Egg-Free, Gluten-Free, Halal, High-Fiber, High-Protein, Keto, Kosher, Low-Carb, Low-FODMAP, Low-Sodium, Nut-Free, Paleo, Pescatarian, Poultry, Soy-Free, Vegan, Vegetarian, Whole30
- **Main Protein** (`main-protein`) [15]: Beans, Beef, Chicken, Chickpeas, Eggs, Fish, Lamb, Lentils, Other Shellfish, Pork, Seitan, Shrimp, Tempeh, Tofu, Turkey
- **Main Carb** (`main-carb`) [10]: Bread, Couscous, No Major Carb, Pasta/Noodles, Polenta, Potatoes, Quinoa, Rice, Sweet Potatoes, Tortillas
- **Cooking Method** (`cooking-method`) [15]: Bake, Braise, Broil, Deep Fry, Fry, Grill, Poach, Pressure Cook, Raw/No-Cook, Roast, Sauté, Simmer, Smoke, Sous Vide, Steam
- **Techniques** (`techniques`) [13]: Blanch, Caramelize, Deglaze, Emulsify, Fold, Julienne, Marinate, Mince, Proof/Rise, Reduce, Rest, Sear, Temper
- **Equipment Required** (`equipment`) [16]: Air Fryer, Blender, Cast Iron, Dutch Oven, Food Processor, Grill, Immersion Blender, Instant Pot/Pressure Cooker, Kitchen Torch, Mandoline, No Special Equipment, Slow Cooker, Smoker, Sous Vide Circulator, Stand Mixer, Wok