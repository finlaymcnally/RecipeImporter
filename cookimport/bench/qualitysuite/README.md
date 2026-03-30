# QualitySuite

Runtime ownership lives here:
`planning.py` expands experiments, `runtime.py` executes them, `persistence.py` owns checkpoints,
`summary.py` owns read/report helpers, and `worker_cli.py` owns worker subprocess entrypoints.
