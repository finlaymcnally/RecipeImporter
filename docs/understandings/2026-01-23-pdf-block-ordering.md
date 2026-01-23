---
summary: "PyMuPDF block sorting interleaves columns; PDF recipes need column grouping."
read_when:
  - When debugging PDF imports with multi-column or tiled page layouts
---

PyMuPDF `page.get_text("blocks", sort=True)` orders blocks by Y then X, which interleaves left/right columns on tiled pages. In Hix1.pdf page 4, the sorted blocks alternate between x0 ~55 (left column) and x0 ~288 (right column), mixing two recipes. The PDF importer now uses line-level extraction and column clustering (x0 gap) to group blocks per column before recipe segmentation.

OCR in Hix1.pdf also misreads leading "1" as "l" (e.g., `l tbsp`). Ingredient detection needs to treat `l`/`I` + unit at line start as quantity-like to avoid skipping these lines.
