# QualitySuite

`quality_runner.py` keeps the public bench entrypoints, but it now delegates runtime ownership here: `planning.py` expands experiments, `runtime.py` executes them, `persistence.py` owns checkpoints, `summary.py` owns read/report helpers, and `worker_cli.py` owns worker subprocess entrypoints.
