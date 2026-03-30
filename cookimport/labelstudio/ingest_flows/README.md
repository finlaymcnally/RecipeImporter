# Ingest Flows

`ingest.py` is the live public import/re-export seam. `ingest_support.py` keeps the shared helper
surface, while this package owns the actual Label Studio ingest behavior: `prediction_run.py` owns
offline artifact builds, `upload.py` owns live Label Studio writes, and the sibling modules group
normalization, split, and artifact helpers.
