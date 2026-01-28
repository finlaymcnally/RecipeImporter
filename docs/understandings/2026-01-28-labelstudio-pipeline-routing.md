---
summary: "Importer routing and stable ID behavior relevant to label-studio chunking."
read_when:
  - When adding new importer modes that need stable IDs or pipeline auto-selection
---

Importer routing is centralized in `cookimport/plugins/registry.py::best_importer_for_path`, and the CLI (`cookimport/cli.py`) uses this to select the pipeline per input file. Stable IDs for staged outputs are derived from provenance in `cookimport/staging/writer.py`: Excel rows use `row_index`, while text/PDF/EPUB fall back to `provenance.location.chunk_index`. For any new labeling mode, reuse `compute_file_hash` plus location metadata and a text hash to keep chunk IDs deterministic across reruns.
