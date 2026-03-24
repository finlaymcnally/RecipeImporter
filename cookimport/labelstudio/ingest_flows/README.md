# Ingest Flows

`ingest.py` keeps the public import paths, but it now delegates to this package: `prediction_run.py` owns offline artifact builds, `upload.py` owns live Label Studio writes, and the helper modules group normalization, split, and artifact helpers.
