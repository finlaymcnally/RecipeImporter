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
to scan a folder and write JSON-LD under `staging/<timestamp>/intermediate drafts/`
and DraftV1 under `staging/<timestamp>/final drafts/`, plus tip snippets under
`staging/<timestamp>/tips/` and reports under `staging/<timestamp>/reports/`.

The text importer treats .docx tables with recognized headers as structured
recipe rows, so Word docs that store recipes in tables retain ingredients and
instructions instead of flattening to plain text.

For text/docx content without explicit "Ingredients" headers, the text importer
can split on "Serves/Yield" lines and infer ingredient vs. instruction blocks
using line-level heuristics.
