# cookimport

This package provides the local CLI and shared pipeline modules for staging
recipe sources into RecipeSage JSON-LD. CLI entrypoints live in
`cookimport/cli.py`, core models live in `cookimport/core/`, and staging output
helpers live in `cookimport/staging/`.

RecipeCandidate supports optional RecipeSage fields like `image`,
`recipeCategory`, `datePublished`, `creditText`, `isBasedOn`, `comment`, and
`aggregateRating`, plus `recipeInstructions` as strings or HowToStep objects.

Run `cookimport inspect <workbook> --write-mapping` to print layout guesses and
write a mapping stub under `staging/mappings/`. Run `cookimport stage <folder>`
to scan a folder and write JSON-LD under `staging/recipesage_jsonld/` plus
reports under `staging/reports/`.
