# Understanding: Variants Extraction and Recipe Segmentation Issues

**Date:** 2026-01-31
**Status:** Fixed

## Overview

Investigation into why "variants" (variations) are missing from final recipe drafts (e.g., `data/output/2026-01-31-00-11-15/final drafts/saltfatacidheat/r10.json`) reveals two primary points of failure: over-eager recipe segmentation in the EPUB importer and narrow pattern matching in the DraftV1 staging logic.

## Findings

### 1. Over-eager Recipe Segmentation (EPUB Importer)

The `EpubImporter` segments an EPUB into recipe candidates by detecting "anchors" (like Yield or Ingredient headers) and then scanning forward/backward to find boundaries.

In the case of `r10.json` (Red Wine Vinaigrette) from *Salt, Fat, Acid, Heat*:
- The recipe was detected from **blocks 1297 to 1305**.
- Block **1306** is a heading `<h5>Variation</h5>`.
- Block **1307** is the actual variation content: `• To make Honey-Mustard Vinaigrette...`.
- Block **1308** is the next recipe title: `Balsamic Vinaigrette`.

The importer's `_find_recipe_end` logic likely saw the `Variation` heading or the proximity of the next recipe and terminated the current candidate *before* the variation blocks. Because these blocks (1306-1307) were excluded from any recipe range, they were captured by the "standalone tip" extractor instead. This is confirmed by their presence in `tips/saltfatacidheat/topic_candidates.json`.

### 2. Narrow Variant Pattern Matching (DraftV1 Staging)

Even if the blocks were correctly included in the recipe candidate, the current `DraftV1` extraction logic in `cookimport/staging/draft_v1.py` is too restrictive.

```python
_VARIANT_PREFIX_RE = re.compile(r"^\s*variations?\b|^\s*variants?\b", re.IGNORECASE)

def _split_variants(instructions: list[str]) -> tuple[list[str], list[str]]:
    variants: list[str] = []
    remaining: list[str] = []
    for instruction in instructions:
        text = instruction.strip()
        if _VARIANT_PREFIX_RE.match(text):
            variants.append(text)
        else:
            remaining.append(instruction)
    return variants, remaining
```

**Limitations:**
- **Single-line focus:** It only identifies instructions that *start* with the prefix.
- **Header/Content Split:** In many books, "Variation" is a header (one block) followed by the actual instructions (subsequent blocks). The current logic would at best capture the "Variation" header line and leave the actual content as a recipe step.
- **Bullet points:** Variation content often starts with bullet points (e.g., `• To make...`) which do not match the regex.

### 3. Interaction with Tip Extraction

The pipeline correctly identifies "Variation" as a tip-worthy header (it is in `_HEADER_LABELS` in `tips.py`), but because these blocks were orphaned from the recipe by the importer, they were never passed through `extract_recipe_specific_notes(candidate)`. Instead, they became standalone topics, losing their association with the "Red Wine Vinaigrette" recipe.

## Conclusion

The "variants" field remains empty because:
1. The blocks are being cut off by the EPUB importer's segmentation logic.
2. The DraftV1 converter only looks for specific line-start prefixes and cannot handle multi-block variations or variations without the explicit prefix on every line.

To fix this, the EPUB importer needs to be more inclusive of trailing "Variation" sections, and the DraftV1 converter needs a more robust way to group headers and their following content into the variants list.

## Fix Applied

### 1. EPUB Importer (`cookimport/plugins/epub.py`)

Added `_is_variation_header()` method to identify standalone variation headers (e.g., "Variation", "Variations", "Variant", "Variants").

Modified `_find_recipe_end()` to check for variation headers and continue including them instead of treating them as section boundaries. Also updated `_is_section_heading()` to exclude variation headers.

### 2. DraftV1 Converter (`cookimport/staging/draft_v1.py`)

Rewrote `_split_variants()` to handle two patterns:
1. **Inline variants** - Single lines starting with "Variation:" prefix (original behavior)
2. **Multi-block variants** - A header-only line (e.g., "Variation" or "Variations") followed by content lines (often with bullet points)

The function now enters a "variant section" mode when it sees a header-only variation line, and collects all subsequent lines until it hits a section header (Ingredients, Instructions, etc.) or the end of the list.

### Tests Added

- `tests/test_draft_v1_variants.py`: Added `test_multiblock_variants_extracted()` and `test_multiblock_variants_with_multiple_bullets()`
- `tests/test_epub_importer.py`: Added `test_find_recipe_end_includes_variation_section()` and `test_is_variation_header()`
