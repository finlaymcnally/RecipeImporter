# Ingest Flows

This package owns the actual Label Studio ingest behavior: `prediction_run.py` owns offline
artifact builds, `upload.py` owns live Label Studio writes, and the sibling modules group
normalization, split, and artifact helpers. `ingest_support.py` keeps the shared helper surface
used by these owner modules.
