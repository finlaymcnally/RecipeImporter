from __future__ import annotations

import json
import importlib
import multiprocessing
import os
import pickle
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.cli_support import (
    ALL_METHOD_ADAPTIVE_CPU_HOT_PCT,
    ALL_METHOD_ADAPTIVE_SATURATION_BACKLOG_MULTIPLIER,
    ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT,
    ALL_METHOD_MAX_INFLIGHT_DEFAULT,
    ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT,
    ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
    ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
    ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO,
    ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT,
    ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR,
)
from cookimport.core.executor_fallback import preferred_multiprocessing_context
from cookimport.core.slug import slugify_name

from .bench_all_method_reporting import _report_count, _report_optional_metric
from .bench_all_method_types import (
    AllMethodTarget,
    AllMethodVariant,
    _AllMethodGlobalWorkItem,
    _AllMethodSourceEstimate,
    _AllMethodSourceJobPlan,
)
from .settings import _normalize_all_method_source_scheduling


def _bench_all_method_attr(name: str, default: Any = None) -> Any:
    candidates: list[Any] = []
    for module_name in ("cookimport.cli", "cookimport.cli_support.bench_all_method"):
        try:
            module = importlib.import_module(module_name)
        except Exception:  # noqa: BLE001
            continue
        if not hasattr(module, name):
            continue
        value = getattr(module, name)
        if default is None or value is not default:
            return value
        candidates.append(value)
    if candidates:
        return candidates[0]
    return default


def _system_total_memory_bytes() -> int | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        page_count = int(os.sysconf("SC_PHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        page_size = 0
        page_count = 0
    total = page_size * page_count
    if total > 0:
        return total

    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        try:
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("MemTotal:"):
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                kib = int(parts[1])
                if kib > 0:
                    return kib * 1024
        except (OSError, ValueError):
            return None
    return None


def _canonical_text_chars_for_all_method_target(target: AllMethodTarget) -> int:
    canonical_text_path = target.gold_spans_path.parent / "canonical_text.txt"
    if not canonical_text_path.exists() or not canonical_text_path.is_file():
        return 0
    try:
        return max(0, int(canonical_text_path.stat().st_size))
    except OSError:
        return 0


def _load_prior_all_method_source_runtime_seconds(
    *,
    prior_report_root: Path | None,
    target: AllMethodTarget,
) -> tuple[float | None, int | None]:
    if prior_report_root is None:
        return None, None
    report_path = prior_report_root / "all_method_benchmark_multi_source_report.json"
    if not report_path.exists() or not report_path.is_file():
        return None, None
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None, None
    if not isinstance(payload, dict):
        return None, None
    source_rows = payload.get("sources")
    if not isinstance(source_rows, list):
        return None, None
    source_path = str(target.source_file)
    source_name = target.source_file_name
    for row in source_rows:
        if not isinstance(row, dict):
            continue
        row_source_path = str(row.get("source_file") or "").strip()
        row_source_name = str(row.get("source_file_name") or "").strip()
        if row_source_path != source_path and row_source_name != source_name:
            continue
        timing_summary = row.get("timing_summary")
        if not isinstance(timing_summary, dict):
            continue
        source_seconds = _report_optional_metric(
            timing_summary.get("source_wall_seconds")
        )
        if source_seconds is None or source_seconds <= 0:
            continue
        prior_variants = _report_count(row.get("variant_count_completed"))
        return source_seconds, (prior_variants if prior_variants > 0 else None)
    return None, None


def _estimate_all_method_source_cost(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    prior_report_root: Path | None = None,
) -> _AllMethodSourceEstimate:
    variant_count = max(0, len(variants))
    canonical_text_chars = _canonical_text_chars_for_all_method_target(target)
    heuristic_seconds = max(
        1.0,
        (float(max(1, variant_count)) * 25.0) + (float(canonical_text_chars) / 1200.0),
    )
    prior_seconds, prior_variant_count = _load_prior_all_method_source_runtime_seconds(
        prior_report_root=prior_report_root,
        target=target,
    )
    if prior_seconds is not None:
        scale = 1.0
        if prior_variant_count is not None and prior_variant_count > 0 and variant_count > 0:
            scale = max(0.25, float(variant_count) / float(prior_variant_count))
        estimated = max(1.0, float(prior_seconds) * scale)
        basis = "prior_source_wall_seconds"
        if canonical_text_chars > 0:
            basis += "+canonical_text_chars"
        return _AllMethodSourceEstimate(
            estimated_seconds=estimated,
            estimate_basis=basis,
            canonical_text_chars=canonical_text_chars,
            variant_count=variant_count,
        )

    basis = "heuristic_variants"
    if canonical_text_chars > 0:
        basis += "+canonical_text_chars"
    return _AllMethodSourceEstimate(
        estimated_seconds=heuristic_seconds,
        estimate_basis=basis,
        canonical_text_chars=canonical_text_chars,
        variant_count=variant_count,
    )


def _split_all_method_source_variants(
    *,
    target: AllMethodTarget,
    variants: list[AllMethodVariant],
    estimate: _AllMethodSourceEstimate,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[list[AllMethodVariant]]:
    _ = target
    if not variants:
        return [[]]
    total_variants = len(variants)
    threshold = max(1.0, float(shard_threshold_seconds))
    max_parts = max(1, _report_count(shard_max_parts))
    min_variants = max(1, _report_count(shard_min_variants))
    if max_parts <= 1:
        return [list(variants)]
    if total_variants < min_variants:
        return [list(variants)]
    if estimate.estimated_seconds < threshold:
        return [list(variants)]

    max_parts_by_variants = total_variants // min_variants
    if max_parts_by_variants < 2:
        return [list(variants)]
    shard_total = min(max_parts, max_parts_by_variants)
    if shard_total < 2:
        return [list(variants)]

    shards: list[list[AllMethodVariant]] = []
    base_size = total_variants // shard_total
    remainder = total_variants % shard_total
    cursor = 0
    for shard_index in range(shard_total):
        shard_size = base_size + (1 if shard_index < remainder else 0)
        next_cursor = cursor + shard_size
        shards.append(list(variants[cursor:next_cursor]))
        cursor = next_cursor
    if len(shards) <= 1:
        return [list(variants)]
    return shards


def _tail_pair_all_method_source_jobs(
    plans: list[_AllMethodSourceJobPlan],
) -> list[_AllMethodSourceJobPlan]:
    if len(plans) <= 2:
        return list(plans)
    ranked = sorted(
        plans,
        key=lambda plan: (
            -plan.estimated_seconds,
            plan.source_position,
            plan.shard_index,
            plan.source_slug,
        ),
    )
    left = 0
    right = len(ranked) - 1
    paired: list[_AllMethodSourceJobPlan] = []
    while left <= right:
        paired.append(ranked[left])
        left += 1
        if left <= right:
            paired.append(ranked[right])
            right -= 1
    return paired


def _plan_all_method_source_jobs(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
) -> list[_AllMethodSourceJobPlan]:
    resolved_strategy = _normalize_all_method_source_scheduling(scheduling_strategy)
    resolved_shard_threshold_seconds = max(1.0, float(shard_threshold_seconds))
    resolved_shard_max_parts = max(1, _report_count(shard_max_parts))
    resolved_shard_min_variants = max(1, _report_count(shard_min_variants))

    estimate_source_cost = _bench_all_method_attr(
        "_estimate_all_method_source_cost",
        _estimate_all_method_source_cost,
    )
    slug_counts: dict[str, int] = {}
    plans: list[_AllMethodSourceJobPlan] = []
    for source_position, (target, variants) in enumerate(target_variants):
        estimate = estimate_source_cost(
            target=target,
            variants=variants,
        )
        source_slug_base = slugify_name(target.source_file.stem)
        source_slug_count = slug_counts.get(source_slug_base, 0) + 1
        slug_counts[source_slug_base] = source_slug_count
        source_group_slug = (
            source_slug_base
            if source_slug_count == 1
            else f"{source_slug_base}__{source_slug_count:02d}"
        )
        shard_variants = _split_all_method_source_variants(
            target=target,
            variants=variants,
            estimate=estimate,
            shard_threshold_seconds=resolved_shard_threshold_seconds,
            shard_max_parts=resolved_shard_max_parts,
            shard_min_variants=resolved_shard_min_variants,
        )
        shard_total = max(1, len(shard_variants))
        for shard_index, shard in enumerate(shard_variants):
            shard_slug = (
                source_group_slug
                if shard_total == 1
                else (
                    f"{source_group_slug}__part_{shard_index + 1:02d}_of_{shard_total:02d}"
                )
            )
            shard_weight = (
                float(len(shard)) / float(len(variants))
                if variants
                else (1.0 / float(shard_total))
            )
            shard_estimated_seconds = max(
                1.0,
                float(estimate.estimated_seconds) * max(0.05, shard_weight),
            )
            plans.append(
                _AllMethodSourceJobPlan(
                    source_position=source_position,
                    source_group_key=source_group_slug,
                    source_display_name=target.source_file_name,
                    source_slug=shard_slug,
                    source_file=target.source_file,
                    gold_spans_path=target.gold_spans_path,
                    variants=list(shard),
                    shard_index=shard_index,
                    shard_total=shard_total,
                    estimated_seconds=shard_estimated_seconds,
                    estimate_basis=estimate.estimate_basis,
                )
            )

    if resolved_strategy == ALL_METHOD_SOURCE_SCHEDULING_TAIL_PAIR:
        return _tail_pair_all_method_source_jobs(plans)
    return list(plans)


def _plan_all_method_global_work_items(
    *,
    target_variants: list[tuple[AllMethodTarget, list[AllMethodVariant]]],
    scheduling_strategy: str,
    shard_threshold_seconds: float,
    shard_max_parts: int,
    shard_min_variants: int,
    root_output_dir: Path,
    processed_output_root: Path,
    canonical_alignment_cache_root: Path,
) -> list[_AllMethodGlobalWorkItem]:
    source_job_plans = _plan_all_method_source_jobs(
        target_variants=target_variants,
        scheduling_strategy=scheduling_strategy,
        shard_threshold_seconds=shard_threshold_seconds,
        shard_max_parts=shard_max_parts,
        shard_min_variants=shard_min_variants,
    )
    source_target_by_position: dict[int, AllMethodTarget] = {
        source_position: target
        for source_position, (target, _variants) in enumerate(target_variants)
    }
    source_config_totals: dict[int, int] = {
        source_position: len(variants)
        for source_position, (_target, variants) in enumerate(target_variants)
    }
    source_next_config_index: dict[int, int] = defaultdict(int)
    resolved_cache_root = canonical_alignment_cache_root.expanduser()

    work_items: list[_AllMethodGlobalWorkItem] = []
    global_dispatch_index = 0
    for plan in source_job_plans:
        source_target = source_target_by_position[plan.source_position]
        source_root = root_output_dir / plan.source_group_key
        source_processed_root = processed_output_root / plan.source_group_key
        canonical_alignment_cache_dir = resolved_cache_root / plan.source_group_key
        source_config_total = max(
            0,
            _report_count(source_config_totals.get(plan.source_position)),
        )
        for variant in plan.variants:
            global_dispatch_index += 1
            source_config_index = source_next_config_index[plan.source_position] + 1
            source_next_config_index[plan.source_position] = source_config_index
            work_items.append(
                _AllMethodGlobalWorkItem(
                    global_dispatch_index=global_dispatch_index,
                    source_position=plan.source_position,
                    source_group_key=plan.source_group_key,
                    source_slug=plan.source_slug,
                    source_file=plan.source_file,
                    source_file_name=source_target.source_file_name,
                    gold_spans_path=plan.gold_spans_path,
                    source_root=source_root,
                    source_processed_root=source_processed_root,
                    canonical_alignment_cache_dir=canonical_alignment_cache_dir,
                    config_index=source_config_index,
                    config_total=source_config_total,
                    source_shard_index=plan.shard_index,
                    source_shard_total=plan.shard_total,
                    source_estimated_seconds=plan.estimated_seconds,
                    source_estimate_basis=plan.estimate_basis,
                    variant=variant,
                )
            )
    return work_items


def _resolve_all_method_split_worker_cap(
    *,
    split_phase_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    slots = max(1, _report_count(split_phase_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_worker_cap_by_cpu = max(1, cpu_budget_per_source // slots)

    memory_total_bytes = _bench_all_method_attr(
        "_system_total_memory_bytes",
        _system_total_memory_bytes,
    )()
    split_worker_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        workers_by_memory_per_source = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )
        split_worker_cap_by_memory = max(1, workers_by_memory_per_source // slots)

    split_worker_cap = split_worker_cap_by_cpu
    if split_worker_cap_by_memory is not None:
        split_worker_cap = min(split_worker_cap, split_worker_cap_by_memory)

    return split_worker_cap, {
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
        "split_worker_cap_by_cpu": split_worker_cap_by_cpu,
        "split_worker_cap_by_memory": split_worker_cap_by_memory,
        "split_worker_cap_per_config": split_worker_cap,
    }


def _resolve_all_method_split_phase_slot_cap(
    *,
    requested_split_slots: int,
    source_parallelism_effective: int | None = None,
) -> tuple[int, dict[str, Any]]:
    requested = max(1, _report_count(requested_split_slots))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1

    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    slot_cap_by_cpu = max(1, cpu_budget_per_source)

    memory_total_bytes = _bench_all_method_attr(
        "_system_total_memory_bytes",
        _system_total_memory_bytes,
    )()
    slot_cap_by_memory: int | None = None
    memory_budget_per_source_bytes: int | None = None
    if memory_total_bytes is not None and memory_total_bytes > 0:
        reserve_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_MIN_RESERVE_BYTES,
            int(memory_total_bytes * ALL_METHOD_RESOURCE_GUARD_RESERVE_RATIO),
        )
        usable_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            memory_total_bytes - reserve_bytes,
        )
        memory_budget_per_source_bytes = max(
            ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
            usable_bytes // source_parallelism,
        )
        slot_cap_by_memory = max(
            1,
            memory_budget_per_source_bytes
            // ALL_METHOD_RESOURCE_GUARD_ESTIMATED_SPLIT_WORKER_BYTES,
        )

    effective_slots = min(requested, slot_cap_by_cpu)
    if slot_cap_by_memory is not None:
        effective_slots = min(effective_slots, slot_cap_by_memory)
    effective_slots = max(1, effective_slots)
    cap_mode = "resource_guard" if effective_slots < requested else "configured"

    return effective_slots, {
        "requested_split_phase_slots": requested,
        "effective_split_phase_slots": effective_slots,
        "split_phase_slot_mode": cap_mode,
        "split_phase_slot_cap_by_cpu": slot_cap_by_cpu,
        "split_phase_slot_cap_by_memory": slot_cap_by_memory,
        "cpu_total": cpu_total,
        "cpu_budget_per_source": cpu_budget_per_source,
        "memory_total_bytes": memory_total_bytes,
        "memory_budget_per_source_bytes": memory_budget_per_source_bytes,
    }


def _resolve_all_method_scheduler_admission(
    *,
    counts: dict[str, int],
    pending_count: int,
    total_variants: int,
    configured_inflight_pipelines: int,
    split_phase_slots: int,
    wing_backlog_target: int,
    max_active_during_eval: int,
    adaptive_overcommit_limit: int,
    adaptive_max_guard_target: int,
    smart_scheduler_enabled: bool,
    cpu_utilization_pct: float | None = None,
) -> _AllMethodSchedulerAdmissionDecision:
    total = max(1, _report_count(total_variants))
    split_slots = max(1, _report_count(split_phase_slots))
    configured_inflight = max(1, min(total, _report_count(configured_inflight_pipelines)))
    wing_target_base = max(1, _report_count(wing_backlog_target))
    max_active_eval = max(configured_inflight, min(total, _report_count(max_active_during_eval)))
    overcommit_cap = max(0, _report_count(adaptive_overcommit_limit))
    guard_cap = max(
        split_slots + wing_target_base,
        min(total, _report_count(adaptive_max_guard_target)),
    )
    guard_base = min(total, split_slots + wing_target_base)
    pending = max(0, _report_count(pending_count))
    evaluate_active = max(0, _report_count(counts.get("evaluate_active")))
    split_wait = max(0, _report_count(counts.get("split_wait")))
    heavy_active = max(0, _report_count(counts.get("heavy_active")))
    prep_active = max(0, _report_count(counts.get("prep_active")))
    wing_backlog = max(0, _report_count(counts.get("wing_backlog")))
    eval_tail_open = evaluate_active > 0 and pending > 0
    cpu_hot = (
        cpu_utilization_pct is not None
        and float(cpu_utilization_pct) >= ALL_METHOD_ADAPTIVE_CPU_HOT_PCT
    )

    active_cap = max_active_eval if eval_tail_open and smart_scheduler_enabled else configured_inflight
    guard_target = guard_base
    wing_target = wing_target_base
    reason = "base"
    pressure_boost = 0
    saturation_clamp = False
    cpu_hot_clamp = False

    if not smart_scheduler_enabled:
        return _AllMethodSchedulerAdmissionDecision(
            active_cap=max(1, min(total, active_cap)),
            guard_target=max(1, min(total, guard_target)),
            wing_target=max(1, min(total, wing_target)),
            reason=reason,
            pressure_boost=pressure_boost,
            saturation_clamp=saturation_clamp,
            cpu_hot_clamp=cpu_hot_clamp,
        )

    heavy_gap = max(0, split_slots - heavy_active)
    backlog_starved = pending > 0 and (
        heavy_gap > 0 or (split_wait == 0 and prep_active < split_slots)
    )
    if backlog_starved and not cpu_hot:
        available_overcommit = 0
        if eval_tail_open:
            available_overcommit = max(
                0,
                min(overcommit_cap, max_active_eval - active_cap),
            )
        pressure_boost = min(available_overcommit, max(1, heavy_gap))
        if pressure_boost > 0:
            active_cap += pressure_boost
        wing_boost = max(1, heavy_gap)
        wing_target = min(total, wing_target_base + wing_boost)
        guard_target = min(
            guard_cap,
            split_slots + wing_target + pressure_boost,
        )
        reason = "pressure_boost"

    saturated_backlog_threshold = max(
        wing_target_base + split_slots,
        wing_target_base * ALL_METHOD_ADAPTIVE_SATURATION_BACKLOG_MULTIPLIER,
    )
    if wing_backlog >= saturated_backlog_threshold and heavy_active >= split_slots:
        saturation_clamp = True
        wing_target = wing_target_base
        guard_target = guard_base
        active_cap = min(active_cap, max_active_eval if eval_tail_open else configured_inflight)
        reason = "saturation_clamp"

    if cpu_hot and active_cap > configured_inflight:
        cpu_hot_clamp = True
        active_cap = max(configured_inflight, active_cap - 1)
        reason = "cpu_hot_clamp"

    return _AllMethodSchedulerAdmissionDecision(
        active_cap=max(1, min(total, active_cap)),
        guard_target=max(1, min(total, guard_target)),
        wing_target=max(1, min(total, wing_target)),
        reason=reason,
        pressure_boost=max(0, pressure_boost),
        saturation_clamp=saturation_clamp,
        cpu_hot_clamp=cpu_hot_clamp,
    )


def _resolve_all_method_source_parallelism(
    *,
    total_sources: int,
    requested: int | None = None,
) -> int:
    total = max(1, _report_count(total_sources))
    default_parallel_sources = min(
        _bench_all_method_attr(
            "_all_method_default_parallel_sources_from_cpu",
        )(),
        total,
    )
    requested_parallel_sources = _report_count(requested)
    if requested_parallel_sources <= 0:
        return default_parallel_sources
    cpu_cap = max(1, _report_count(os.cpu_count()))
    return max(1, min(requested_parallel_sources, total, cpu_cap))


def _create_all_method_process_pool_executor(*, max_workers: int):
    context = preferred_multiprocessing_context()
    process_pool_executor_cls = _bench_all_method_attr(
        "ProcessPoolExecutor",
        ProcessPoolExecutor,
    )
    if context is None:
        try:
            start_method = multiprocessing.get_start_method(allow_none=True)
        except TypeError:
            start_method = multiprocessing.get_start_method()
        if not start_method:
            try:
                start_methods = multiprocessing.get_all_start_methods()
            except Exception:  # noqa: BLE001
                start_methods = []
            start_method = start_methods[0] if start_methods else None
        if str(start_method or "").strip() == "fork":
            try:
                available_methods = multiprocessing.get_all_start_methods()
            except Exception:  # noqa: BLE001
                available_methods = []
            if "spawn" in available_methods:
                try:
                    context = multiprocessing.get_context("spawn")
                except Exception:  # noqa: BLE001
                    context = None
    if context is None:
        return process_pool_executor_cls(max_workers=max_workers)
    try:
        return process_pool_executor_cls(max_workers=max_workers, mp_context=context)
    except TypeError:
        return process_pool_executor_cls(max_workers=max_workers)


def _probe_all_method_process_pool_executor() -> tuple[bool, str | None]:
    """Return whether process-based config workers are usable in this runtime."""
    try:
        with _create_all_method_process_pool_executor(max_workers=1) as executor:
            future = executor.submit(int, 1)
            future.result(timeout=5)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _probe_all_method_process_worker_picklable() -> tuple[bool, str | None]:
    """Ensure the benchmark config worker can be pickled when process pooling is active."""
    worker = _bench_all_method_attr("_run_all_method_prediction_once")
    if worker is None:
        return False, "_run_all_method_prediction_once unavailable"
    try:
        pickle.dumps(worker)
    except Exception as exc:  # noqa: BLE001
        detail = str(exc).strip()
        if detail:
            return False, f"{type(exc).__name__}: {detail}"
        return False, type(exc).__name__
    return True, None


def _resolve_all_method_scheduler_limits(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
) -> tuple[int, int]:
    total = max(1, _report_count(total_variants))

    inflight_default = min(ALL_METHOD_MAX_INFLIGHT_DEFAULT, total)
    if max_inflight_pipelines is None:
        inflight = inflight_default
    else:
        requested_inflight = _report_count(max_inflight_pipelines)
        if requested_inflight <= 0:
            inflight = inflight_default
        else:
            inflight = max(1, min(requested_inflight, total))

    split_default = min(ALL_METHOD_MAX_SPLIT_PHASE_SLOTS_DEFAULT, inflight)
    if max_concurrent_split_phases is None:
        split_slots = split_default
    else:
        requested_split_slots = _report_count(max_concurrent_split_phases)
        if requested_split_slots <= 0:
            split_slots = split_default
        else:
            split_slots = max(1, min(requested_split_slots, inflight))

    return inflight, split_slots


@dataclass(frozen=True)
class _AllMethodSchedulerRuntime:
    configured_inflight_pipelines: int
    split_phase_slots_requested: int
    split_phase_slots: int
    split_phase_slot_mode: str
    split_phase_slot_cap_by_cpu: int
    split_phase_slot_cap_by_memory: int | None
    wing_backlog_target: int
    eval_tail_headroom_configured: int
    eval_tail_headroom_effective: int
    eval_tail_headroom_mode: str
    smart_scheduler_enabled: bool
    max_active_during_eval: int
    effective_inflight_pipelines: int
    adaptive_overcommit_limit: int
    adaptive_max_guard_target: int
    source_parallelism_effective: int
    cpu_budget_per_source: int
    cpu_budget_total: int


@dataclass(frozen=True)
class _AllMethodSchedulerAdmissionDecision:
    active_cap: int
    guard_target: int
    wing_target: int
    reason: str
    pressure_boost: int
    saturation_clamp: bool
    cpu_hot_clamp: bool


def _resolve_all_method_config_timeout_seconds(
    config_timeout_seconds: int | None,
) -> int | None:
    if config_timeout_seconds is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    parsed = _bench_all_method_attr(
        "_coerce_non_negative_int",
    )(config_timeout_seconds)
    if parsed is None:
        return ALL_METHOD_CONFIG_TIMEOUT_SECONDS_DEFAULT
    if parsed == 0:
        return None
    return parsed


def _resolve_all_method_retry_failed_configs(retry_failed_configs: int | None) -> int:
    if retry_failed_configs is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    parsed = _bench_all_method_attr(
        "_coerce_non_negative_int",
    )(retry_failed_configs)
    if parsed is None:
        return ALL_METHOD_RETRY_FAILED_CONFIGS_DEFAULT
    return parsed


def _resolve_all_method_scheduler_runtime(
    *,
    total_variants: int,
    max_inflight_pipelines: int | None = None,
    max_concurrent_split_phases: int | None = None,
    max_eval_tail_pipelines: int | None = None,
    wing_backlog_target: int | None = None,
    smart_scheduler: bool | None = None,
    source_parallelism_effective: int | None = None,
) -> _AllMethodSchedulerRuntime:
    inflight, split_slots_requested = _resolve_all_method_scheduler_limits(
        total_variants=total_variants,
        max_inflight_pipelines=max_inflight_pipelines,
        max_concurrent_split_phases=max_concurrent_split_phases,
    )
    total = max(1, _report_count(total_variants))
    source_parallelism = _report_count(source_parallelism_effective)
    if source_parallelism <= 0:
        source_parallelism = 1
    cpu_total = max(1, int(os.cpu_count() or 1))
    cpu_budget_total = max(1, cpu_total - 1)
    cpu_budget_per_source = max(1, cpu_budget_total // source_parallelism)
    split_slots, split_slot_guard = _resolve_all_method_split_phase_slot_cap(
        requested_split_slots=split_slots_requested,
        source_parallelism_effective=source_parallelism,
    )
    wing_default = max(1, split_slots)
    wing_target_requested = _report_count(wing_backlog_target)
    wing_target = wing_target_requested if wing_target_requested > 0 else wing_default
    wing_target = max(1, min(total, wing_target))

    eval_tail_requested = _report_count(max_eval_tail_pipelines)
    eval_tail_mode = "configured" if eval_tail_requested > 0 else "auto"
    if eval_tail_requested > 0:
        eval_tail_configured = max(0, eval_tail_requested)
    else:
        eval_tail_configured = max(0, cpu_budget_per_source - inflight)

    # Eval-tail headroom is bounded to per-source CPU budget and available variants.
    eval_tail_effective = max(
        0,
        min(
            eval_tail_configured,
            cpu_budget_per_source,
            max(0, total - inflight),
        ),
    )
    smart_enabled = (
        True
        if smart_scheduler is None
        else _bench_all_method_attr("_coerce_bool_setting")(smart_scheduler, default=True)
    )

    max_active_during_eval = inflight
    if smart_enabled:
        max_active_during_eval = min(total, inflight + eval_tail_effective)
    adaptive_overcommit_limit = max(
        0,
        min(split_slots, max(0, max_active_during_eval - inflight)),
    )
    adaptive_max_guard_target = min(
        total,
        split_slots + wing_target + adaptive_overcommit_limit,
    )

    return _AllMethodSchedulerRuntime(
        configured_inflight_pipelines=inflight,
        split_phase_slots_requested=split_slots_requested,
        split_phase_slots=split_slots,
        split_phase_slot_mode=str(split_slot_guard.get("split_phase_slot_mode") or "configured"),
        split_phase_slot_cap_by_cpu=_report_count(
            split_slot_guard.get("split_phase_slot_cap_by_cpu")
        ),
        split_phase_slot_cap_by_memory=(
            _report_count(split_slot_guard.get("split_phase_slot_cap_by_memory"))
            if split_slot_guard.get("split_phase_slot_cap_by_memory") is not None
            else None
        ),
        wing_backlog_target=wing_target,
        eval_tail_headroom_configured=eval_tail_configured,
        eval_tail_headroom_effective=eval_tail_effective,
        eval_tail_headroom_mode=eval_tail_mode,
        smart_scheduler_enabled=smart_enabled,
        max_active_during_eval=max_active_during_eval,
        effective_inflight_pipelines=max_active_during_eval if smart_enabled else inflight,
        adaptive_overcommit_limit=adaptive_overcommit_limit,
        adaptive_max_guard_target=adaptive_max_guard_target,
        source_parallelism_effective=source_parallelism,
        cpu_budget_per_source=cpu_budget_per_source,
        cpu_budget_total=cpu_budget_total,
    )
