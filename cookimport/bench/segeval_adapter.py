from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any


class OptionalSegmentationDependencyError(RuntimeError):
    pass


_INSTALL_GUIDANCE = (
    "Install optional segmentation metrics dependency with: "
    "python -m pip install -e \".[segmentation_eval]\""
)

_METRIC_FUNCTION_CANDIDATES: dict[str, tuple[str, ...]] = {
    "pk": ("pk",),
    "windowdiff": ("window_diff", "windowdiff"),
    "boundary_similarity": ("boundary_similarity",),
}


def _import_segeval_module() -> Any:
    try:
        return importlib.import_module("segeval")
    except ModuleNotFoundError as exc:
        raise OptionalSegmentationDependencyError(
            "Requested optional segmentation metrics require the `segeval` package. "
            + _INSTALL_GUIDANCE
        ) from exc


def _resolve_metric_fn(segeval_module: Any, metric_name: str) -> Callable[..., Any]:
    candidates = _METRIC_FUNCTION_CANDIDATES.get(metric_name, ())
    for candidate_name in candidates:
        fn = getattr(segeval_module, candidate_name, None)
        if callable(fn):
            return fn
    raise OptionalSegmentationDependencyError(
        f"`segeval` does not expose the required function for metric {metric_name!r}. "
        + _INSTALL_GUIDANCE
    )


def _labels_to_masses(labels: list[str]) -> tuple[int, ...]:
    if not labels:
        return tuple()
    masses: list[int] = []
    run_length = 1
    for index in range(1, len(labels)):
        if labels[index] == labels[index - 1]:
            run_length += 1
            continue
        masses.append(run_length)
        run_length = 1
    masses.append(run_length)
    return tuple(masses)


def compute_optional_segmentation_metrics(
    *,
    labels_gold: list[str],
    labels_pred: list[str],
    requested_metrics: list[str],
) -> dict[str, float]:
    if len(labels_gold) != len(labels_pred):
        raise ValueError(
            "Gold/pred projected label sequences must have equal length for optional segmentation metrics."
        )
    if not requested_metrics:
        return {}

    segeval_module = _import_segeval_module()
    gold_masses = _labels_to_masses(labels_gold)
    pred_masses = _labels_to_masses(labels_pred)

    if not gold_masses and not pred_masses:
        return {name: 0.0 for name in requested_metrics}

    metrics: dict[str, float] = {}
    for metric_name in requested_metrics:
        metric_fn = _resolve_metric_fn(segeval_module, metric_name)
        try:
            value = metric_fn(gold_masses, pred_masses)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"`segeval` metric computation failed for {metric_name!r}: {exc}"
            ) from exc
        metrics[metric_name] = float(value)
    return metrics
