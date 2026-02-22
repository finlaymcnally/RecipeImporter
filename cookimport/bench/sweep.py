"""Parameter sweep over bench suite for cheap local autotuning."""

from __future__ import annotations

import datetime as dt
import json
import random
from pathlib import Path
from typing import Any, Callable

from cookimport.bench.knobs import KNOB_REGISTRY, effective_knobs
from cookimport.bench.runner import run_suite
from cookimport.bench.suite import BenchSuite
from cookimport.core.progress_messages import format_task_counter


def _generate_configs(
    budget: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Generate a list of knob configs to try via random search."""
    rng = random.Random(seed)
    configs: list[dict[str, Any]] = []

    # Always include defaults as first config
    defaults = effective_knobs(None)
    configs.append(defaults)

    sweepable = [k for k in KNOB_REGISTRY if k.bounds is not None]

    for _ in range(budget - 1):
        cfg = dict(defaults)
        for knob in sweepable:
            lo, hi = knob.bounds  # type: ignore[misc]
            if knob.kind == "int":
                cfg[knob.name] = rng.randint(int(lo), int(hi))
            elif knob.kind == "float":
                cfg[knob.name] = round(rng.uniform(float(lo), float(hi)), 4)
            elif knob.kind == "bool":
                cfg[knob.name] = rng.choice([True, False])
        configs.append(cfg)

    return configs[:budget]


def run_sweep(
    suite: BenchSuite,
    out_dir: Path,
    *,
    repo_root: Path,
    budget: int = 25,
    seed: int = 42,
    objective: str = "coverage",
    progress_callback: Callable[[str], None] | None = None,
) -> Path:
    """Run a parameter sweep. Returns the sweep output directory."""
    def _notify(msg: str) -> None:
        if progress_callback:
            progress_callback(msg)

    timestamp = dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S")
    sweep_root = out_dir / f"sweep_{timestamp}"
    sweep_root.mkdir(parents=True, exist_ok=True)

    configs = _generate_configs(budget, seed)
    _notify(f"Generated {len(configs)} configurations to evaluate.")

    leaderboard: list[dict[str, Any]] = []
    total_configs = len(configs)

    for config_position, config in enumerate(configs, start=1):
        config_index = config_position - 1
        config_progress = format_task_counter("", config_position, total_configs, noun="config")
        _notify(f"{config_progress}: {config}")
        config_dir = sweep_root / f"config_{config_index:03d}"

        try:
            run_root, metrics = run_suite(
                suite,
                config_dir,
                repo_root=repo_root,
                config=config,
                progress_callback=lambda msg, prefix=config_progress: _notify(
                    f"{prefix} | {msg}"
                ),
            )

            score = metrics.get("recall", 0.0)
            if objective == "precision":
                score = metrics.get("precision", 0.0)
            elif objective == "f1":
                r = metrics.get("recall", 0.0)
                p = metrics.get("precision", 0.0)
                score = (2 * r * p / (r + p)) if (r + p) > 0 else 0.0

            leaderboard.append({
                "config_index": config_index,
                "config": config,
                "score": score,
                "recall": metrics.get("recall", 0.0),
                "precision": metrics.get("precision", 0.0),
                "run_root": str(run_root),
            })
        except Exception as exc:
            _notify(f"{config_progress} failed: {exc}")
            leaderboard.append({
                "config_index": config_index,
                "config": config,
                "score": 0.0,
                "error": str(exc),
            })

    # Sort by score descending
    leaderboard.sort(key=lambda x: x.get("score", 0.0), reverse=True)

    (sweep_root / "leaderboard.json").write_text(
        json.dumps(leaderboard, indent=2, sort_keys=True), encoding="utf-8"
    )

    if leaderboard and "error" not in leaderboard[0]:
        (sweep_root / "best_config.json").write_text(
            json.dumps(leaderboard[0]["config"], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    if leaderboard:
        best_config_position = int(leaderboard[0]["config_index"]) + 1
        best_config_progress = format_task_counter(
            "",
            best_config_position,
            total_configs,
            noun="config",
        )
        _notify(
            f"Sweep complete. Best score={leaderboard[0]['score']:.3f} "
            f"({best_config_progress})"
        )
    else:
        _notify("Sweep complete (no results).")
    return sweep_root
