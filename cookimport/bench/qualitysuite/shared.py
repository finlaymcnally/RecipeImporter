"""Quality-suite execution for deterministic all-method quality experiments."""

from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import datetime as dt
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cookimport.bench.quality_eta import (
    estimate_quality_run_eta,
    estimate_quality_run_remaining_seconds,
    format_eta_seconds_short,
)
from cookimport.bench.quality_suite import QualitySuite
from cookimport.bench.speed_suite import resolve_repo_path
from cookimport.config.codex_decision import (
    apply_benchmark_baseline_contract,
    classify_codex_surfaces,
    codex_execution_policy_metadata,
    resolve_codex_execution_policy,
)
from cookimport.config.run_settings import RunSettings
from cookimport.config.run_settings_contracts import (
    RUN_SETTING_CONTRACT_FULL,
    project_run_config_payload,
)
from cookimport.core.progress_messages import format_task_counter
from cookimport.paths import REPO_ROOT

_EXPERIMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SUPPORTED_EXPERIMENT_SCHEMA_VERSION = 2
_SUPPORTED_EXPERIMENT_SCHEMA_VERSIONS = {1, 2}
_SUPPORTED_SEARCH_STRATEGIES = {"exhaustive", "race"}
_ALL_METHOD_ALIGNMENT_CACHE_ROOT_ENV = "COOKIMPORT_ALL_METHOD_ALIGNMENT_CACHE_ROOT"
_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT_ENV = (
    "COOKIMPORT_ALL_METHOD_PREDICTION_REUSE_CACHE_ROOT"
)
_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS_ENV = (
    "COOKIMPORT_QUALITY_AUTO_MAX_PARALLEL_EXPERIMENTS"
)
_QUALITY_LIVE_ETA_POLL_SECONDS_ENV = "COOKIMPORT_QUALITY_LIVE_ETA_POLL_SECONDS"
_QUALITY_LIVE_ETA_POLL_SECONDS_DEFAULT = 15.0
_QUALITY_EXPERIMENT_EXECUTOR_MODE_ENV = "COOKIMPORT_QUALITY_EXPERIMENT_EXECUTOR_MODE"
_QUALITY_EXPERIMENT_EXECUTOR_MODES = {"auto", "thread", "subprocess"}
_QUALITY_WSL_SAFETY_GUARD_DISABLE_ENV = "COOKIMPORT_QUALITY_WSL_DISABLE_SAFETY_GUARD"
_QUALITY_WSL_SAFETY_WORKER_CAP = 2
_QUALITY_WSL_RUNTIME_CAPS = {
    "max_parallel_sources": 1,
    "max_inflight_pipelines": 2,
    "max_concurrent_split_phases": 1,
    "max_eval_tail_pipelines": 2,
    "wing_backlog_target": 1,
}
_QUALITY_EXPERIMENT_WORKER_REQUEST_ARG = "--experiment-worker-request"
_QUALITY_EXPERIMENT_WORKER_REQUEST_FILENAME = "_experiment_worker_request.json"
_QUALITY_EXPERIMENT_WORKER_RESULT_FILENAME = "_experiment_worker_result.json"
_QUALITY_EXPERIMENT_RESULT_FILENAME = "quality_experiment_result.json"
_QUALITY_RUN_CHECKPOINT_FILENAME = "checkpoint.json"
_QUALITY_RUN_PARTIAL_SUMMARY_FILENAME = "summary.partial.json"
_QUALITY_RUN_PARTIAL_REPORT_FILENAME = "report.partial.md"
_SOURCE_EXTENSION_NONE = "__none__"
_ALL_METHOD_RUNTIME_ALLOWED_KEYS = {
    "max_parallel_sources",
    "max_inflight_pipelines",
    "max_concurrent_split_phases",
    "max_eval_tail_pipelines",
    "config_timeout_seconds",
    "retry_failed_configs",
    "scheduler_scope",
    "source_scheduling",
    "source_shard_threshold_seconds",
    "source_shard_max_parts",
    "source_shard_min_variants",
    "wing_backlog_target",
    "smart_scheduler",
}
_RACE_KEEP_RATIO_SECONDARY = 0.5
ProgressCallback = Callable[[str], None]
ProgressCallback = Callable[[str], None]
