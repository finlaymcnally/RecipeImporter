from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field

from cookimport.config.run_settings import RunSettings
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    normalize_freeform_label,
)
from cookimport.llm.canonical_line_role_prompt import build_canonical_line_role_prompt
from cookimport.llm.codex_exec import default_codex_exec_cmd, run_codex_json_prompt
from cookimport.parsing.recipe_block_atomizer import AtomicLineCandidate

_PROSE_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'/-]*")
_QUANTITY_LINE_RE = re.compile(
    r"^\s*(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?(?:\s*(?:to|-)\s*\d+(?:\.\d+)?)?)\s+",
    re.IGNORECASE,
)
_INGREDIENT_UNIT_RE = re.compile(
    r"\b(cups?|tbsp|tablespoons?|tsp|teaspoons?|oz|ounces?|lb|lbs|pounds?|"
    r"g|kg|ml|l|cloves?|sticks?|cans?|pinch)\b",
    re.IGNORECASE,
)
_INGREDIENT_NAME_FRAGMENT_RE = re.compile(
    r"^[A-Za-z][A-Za-z'/-]*(?:\s+[A-Za-z][A-Za-z'/-]*){0,2}$"
)
_INGREDIENT_FRAGMENT_STOPWORDS = {
    "and",
    "at",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "step",
    "the",
    "to",
    "with",
}
_TIME_PREFIX_RE = re.compile(
    r"^\s*(?:prep time|cook time|total time|active time|ready in)\b",
    re.IGNORECASE,
)
_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(?:add|bake|beat|blend|boil|braise|bring|combine|cook|cool|cover|drain|"
    r"fold|grill|heat|mix|place|pour|reduce|remove|roast|season|serve|simmer|stir|"
    r"transfer|whisk)\b",
    re.IGNORECASE,
)
_RECIPE_ACTION_CUE_RE = re.compile(
    r"\b(?:add|allow|arrange|bake|beat|blend|boil|braise|bring|chop|clean|coat|"
    r"combine|cook|cool|cover|crush|cut|deglaze|drain|dress|ferment|fill|flip|"
    r"fold|garnish|grill|hang|heat|knead|mix|place|plate|poach|pour|preheat|"
    r"reduce|remove|rinse|roast|sear|season|serve|set|simmer|slice|soak|stir|"
    r"strain|tie|toast|transfer|trim|wash|whisk)\b",
    re.IGNORECASE,
)
_INSTRUCTION_LEADIN_RE = re.compile(
    r"^\s*(?:in|on|with|while|once|when|after|before)\b",
    re.IGNORECASE,
)
_NOTE_PREFIX_RE = re.compile(r"^\s*notes?\s*:\s*", re.IGNORECASE)
_NUMBERED_STEP_RE = re.compile(r"^\s*(?:step\s*)?\d{1,2}[.)]\s+", re.IGNORECASE)
_YIELD_PREFIX_RE = re.compile(
    r"^\s*(?:makes|serves?|servings|yields?)\b",
    re.IGNORECASE,
)
_HOWTO_PREFIX_RE = re.compile(
    r"^\s*(?:to make|to serve|for serving|for garnish|for the)\b",
    re.IGNORECASE,
)
_VARIANT_EXPLICIT_HEADINGS = {"variation", "for a crowd"}
_VARIANT_RECIPE_SUFFIXES = (
    "OMELET",
    "HASH",
    "PANCAKES",
    "WAFFLES",
    "BISCUITS",
    "SCONES",
    "SOUP",
)
_EDITORIAL_NOTE_PREFIXES = (
    "bottom line",
    "the best part",
    "for a long time",
    "your soup is essentially done",
    "whatever liquid you choose",
)
_NON_RECIPE_PROSE_PREFIXES = (
    "to the ",
    "and to ",
    "preface",
    "introduction",
    "contents",
    "acknowledgments",
    "index",
    "conversions",
)
_RECIPE_CONTEXT_RE = re.compile(
    r"\b(?:egg|eggs|omelet|omelette|soup|chicken|stock|broth|sauce|gravy|"
    r"hollandaise|poach|boil|fry|roast|braise|biscuits?|scones?|pancakes?|"
    r"waffles?|hash|onion|garlic|tomato|cheese|pasta|bean|mushroom|broccoli|"
    r"potato|anchov|parsley|bacon|ham|buttermilk|yolk|rice|noodles)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_RE = re.compile(
    r"\b(?:i|i'm|i'd|i've|my|me|we|we're|our)\b",
    re.IGNORECASE,
)
_EXPLICIT_KNOWLEDGE_CUE_RE = re.compile(
    r"\b(?:conduct heat|heat transfer|this means|which means|in other words|"
    r"for example|for instance|as a rule|in general|rule of thumb|ratio|"
    r"temperature|emulsion)\b",
    re.IGNORECASE,
)
_CODEX_LOW_CONFIDENCE_THRESHOLD = 0.90
_YIELD_COUNT_HINT_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"about|approximately|approx\.?|around|up to|at least|at most)\b",
    re.IGNORECASE,
)
_LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT = 4
_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV = "COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT"
_LINE_ROLE_CODEX_RETRY_ATTEMPTS = 3
_LINE_ROLE_CODEX_RETRY_BASE_SECONDS = 1.5
_LINE_ROLE_CACHE_SCHEMA_VERSION = "canonical_line_role_cache.v1"
_LINE_ROLE_CACHE_ROOT_ENV = "COOKIMPORT_LINE_ROLE_CACHE_ROOT"


class CanonicalLineRolePrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    recipe_id: str | None = None
    block_id: str
    block_index: int | None = None
    atomic_index: int
    text: str
    within_recipe_span: bool = False
    label: str
    confidence: float
    decided_by: Literal["rule", "codex", "fallback"]
    candidate_labels: list[str] = Field(default_factory=list)
    reason_tags: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _CodexBatchTask:
    prompt_index: int
    candidates: tuple[AtomicLineCandidate, ...]
    allowed_by_index: dict[int, list[str]]


@dataclass(frozen=True)
class _CodexBatchResult:
    prompt_index: int
    predictions: tuple[CanonicalLineRolePrediction, ...]
    parse_error: bool


def label_atomic_lines(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    artifact_root: Path | None = None,
    source_hash: str | None = None,
    cache_root: Path | None = None,
    codex_timeout_seconds: int = 600,
    codex_batch_size: int = 40,
    codex_cmd: str | None = None,
    codex_runner: Callable[..., Any] | None = None,
) -> list[CanonicalLineRolePrediction]:
    ordered = list(candidates)
    if not ordered:
        return []
    by_atomic_index = {int(candidate.atomic_index): candidate for candidate in ordered}
    mode = _line_role_pipeline_name(settings)
    cache_path: Path | None = None
    if mode == "codex-line-role-v1":
        cache_path = _resolve_line_role_cache_path(
            source_hash=source_hash,
            settings=settings,
            ordered_candidates=ordered,
            artifact_root=artifact_root,
            cache_root=cache_root,
            codex_timeout_seconds=codex_timeout_seconds,
            codex_batch_size=codex_batch_size,
        )
        if cache_path is not None:
            cached_predictions = _load_cached_predictions(
                cache_path=cache_path,
                expected_candidates=ordered,
            )
            if cached_predictions is not None:
                return cached_predictions

    predictions: dict[int, CanonicalLineRolePrediction] = {}
    unresolved: list[AtomicLineCandidate] = []
    for candidate in ordered:
        label, confidence, tags = _deterministic_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        if label is None:
            unresolved.append(candidate)
            continue
        if (
            mode == "codex-line-role-v1"
            and _should_escalate_low_confidence_candidate(
                candidate=candidate,
                deterministic_label=label,
                confidence=confidence,
                by_atomic_index=by_atomic_index,
            )
        ):
            unresolved.append(candidate)
            continue
        predictions[candidate.atomic_index] = CanonicalLineRolePrediction(
            recipe_id=candidate.recipe_id,
            block_id=str(candidate.block_id),
            block_index=int(candidate.block_index),
            atomic_index=int(candidate.atomic_index),
            text=str(candidate.text),
            within_recipe_span=bool(candidate.within_recipe_span),
            label=label,
            confidence=confidence,
            decided_by="rule",
            candidate_labels=list(
                _candidate_allowlist(
                    candidate,
                    by_atomic_index=by_atomic_index,
                )
            ),
            reason_tags=tags,
        )

    parse_error_count = 0
    if mode == "codex-line-role-v1" and unresolved:
        log_state = _PromptLogState(artifact_root=artifact_root)
        batch_tasks: list[_CodexBatchTask] = []
        for batch in _batch(unresolved, max(1, int(codex_batch_size))):
            batch_allowed = {
                candidate.atomic_index: _candidate_allowlist(
                    candidate,
                    by_atomic_index=by_atomic_index,
                )
                for candidate in batch
            }
            batch_tasks.append(
                _CodexBatchTask(
                    prompt_index=log_state.next_index(),
                    candidates=tuple(batch),
                    allowed_by_index=batch_allowed,
                )
            )

        max_inflight = min(
            max(1, _resolve_line_role_codex_max_inflight()),
            len(batch_tasks),
        )
        results_by_prompt_index: dict[int, _CodexBatchResult] = {}
        with ThreadPoolExecutor(max_workers=max_inflight) as executor:
            future_to_prompt_index = {
                executor.submit(
                    _run_codex_batch,
                    task=task,
                    by_atomic_index=by_atomic_index,
                    log_state=log_state,
                    codex_timeout_seconds=codex_timeout_seconds,
                    codex_cmd=codex_cmd,
                    codex_runner=codex_runner,
                ): task.prompt_index
                for task in batch_tasks
            }
            for future in as_completed(future_to_prompt_index):
                result = future.result()
                results_by_prompt_index[result.prompt_index] = result

        for task in batch_tasks:
            batch_result = results_by_prompt_index[task.prompt_index]
            if batch_result.parse_error:
                parse_error_count += 1
            for prediction in batch_result.predictions:
                predictions[prediction.atomic_index] = prediction
        log_state.write_parse_error_summary(parse_error_count=parse_error_count)

    for candidate in unresolved:
        if candidate.atomic_index not in predictions:
            predictions[candidate.atomic_index] = _fallback_prediction(
                candidate,
                reason="deterministic_unresolved",
                by_atomic_index=by_atomic_index,
            )

    sanitized: list[CanonicalLineRolePrediction] = []
    for candidate in ordered:
        current = predictions[candidate.atomic_index]
        sanitized.append(
            _sanitize_prediction(
                prediction=current,
                candidate=candidate,
                by_atomic_index=by_atomic_index,
            )
        )
    _write_cached_predictions(
        cache_path=cache_path,
        predictions=sanitized,
    )
    return sanitized


def _run_codex_batch(
    *,
    task: _CodexBatchTask,
    by_atomic_index: dict[int, AtomicLineCandidate],
    log_state: "_PromptLogState",
    codex_timeout_seconds: int,
    codex_cmd: str | None,
    codex_runner: Callable[..., Any] | None,
) -> _CodexBatchResult:
    batch = list(task.candidates)
    prompt_targets = [
        candidate.model_copy(
            update={"candidate_labels": list(task.allowed_by_index[candidate.atomic_index])}
        )
        for candidate in batch
    ]
    prompt_text = build_canonical_line_role_prompt(prompt_targets)
    prompt_path = log_state.prompt_path(task.prompt_index)
    if prompt_path is not None:
        prompt_path.write_text(prompt_text, encoding="utf-8")

    raw_response = ""
    codex_failure: str | None = None
    try:
        response_payload = _run_codex_prompt_with_retry(
            prompt=prompt_text,
            timeout_seconds=codex_timeout_seconds,
            cmd=codex_cmd or default_codex_exec_cmd(),
            runner=codex_runner,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback path
        codex_failure = f"codex_call_failed:{exc.__class__.__name__}:{exc}"
    else:
        raw_response = str(response_payload.get("response") or "")

    response_path = log_state.response_path(task.prompt_index)
    if response_path is not None:
        response_path.write_text(raw_response, encoding="utf-8")

    parsed_path = log_state.parsed_path(task.prompt_index)
    if codex_failure is not None:
        fallback_predictions = tuple(
            _fallback_prediction(
                candidate,
                reason="codex_call_failed",
                by_atomic_index=by_atomic_index,
            )
            for candidate in batch
        )
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(
                    {
                        "error": codex_failure,
                        "requested_atomic_indices": [
                            int(candidate.atomic_index) for candidate in batch
                        ],
                        "fallback_applied": True,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        log_state.append_dedup(
            prompt_text=prompt_text,
            response_text=raw_response,
            prompt_index=task.prompt_index,
        )
        return _CodexBatchResult(
            prompt_index=task.prompt_index,
            predictions=fallback_predictions,
            parse_error=True,
        )

    parsed_rows, error = _parse_codex_line_role_response(
        raw_response,
        requested=batch,
        allowed_by_index=task.allowed_by_index,
    )
    if error is not None:
        fallback_predictions = tuple(
            _fallback_prediction(
                candidate,
                reason="codex_parse_error",
                by_atomic_index=by_atomic_index,
            )
            for candidate in batch
        )
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(
                    {
                        "error": error,
                        "requested_atomic_indices": [
                            int(candidate.atomic_index) for candidate in batch
                        ],
                        "fallback_applied": True,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        log_state.append_dedup(
            prompt_text=prompt_text,
            response_text=raw_response,
            prompt_index=task.prompt_index,
        )
        return _CodexBatchResult(
            prompt_index=task.prompt_index,
            predictions=fallback_predictions,
            parse_error=True,
        )

    codex_predictions = tuple(
        CanonicalLineRolePrediction(
            recipe_id=by_atomic_index[row["atomic_index"]].recipe_id,
            block_id=str(by_atomic_index[row["atomic_index"]].block_id),
            block_index=int(by_atomic_index[row["atomic_index"]].block_index),
            atomic_index=int(by_atomic_index[row["atomic_index"]].atomic_index),
            text=str(by_atomic_index[row["atomic_index"]].text),
            within_recipe_span=bool(
                by_atomic_index[row["atomic_index"]].within_recipe_span
            ),
            label=row["label"],
            confidence=0.75,
            decided_by="codex",
            candidate_labels=list(task.allowed_by_index[row["atomic_index"]]),
            reason_tags=["codex_line_role"],
        )
        for row in parsed_rows
    )
    if parsed_path is not None:
        parsed_path.write_text(
            json.dumps(parsed_rows, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    log_state.append_dedup(
        prompt_text=prompt_text,
        response_text=raw_response,
        prompt_index=task.prompt_index,
    )
    return _CodexBatchResult(
        prompt_index=task.prompt_index,
        predictions=codex_predictions,
        parse_error=False,
    )


def _run_codex_prompt_with_retry(
    *,
    prompt: str,
    timeout_seconds: int,
    cmd: str,
    runner: Callable[..., Any] | None,
) -> dict[str, Any]:
    attempts = max(1, int(_LINE_ROLE_CODEX_RETRY_ATTEMPTS))
    backoff_seconds = max(0.0, float(_LINE_ROLE_CODEX_RETRY_BASE_SECONDS))
    last_payload: dict[str, Any] | None = None
    last_exception: Exception | None = None
    for attempt_index in range(attempts):
        try:
            payload = run_codex_json_prompt(
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                cmd=cmd,
                track_usage=False,
                runner=runner,
            )
        except Exception as exc:
            last_exception = exc
            if attempt_index >= attempts - 1:
                raise
            time.sleep(backoff_seconds * (2**attempt_index))
            continue
        last_payload = payload
        if _codex_payload_looks_complete(payload):
            return payload
        if attempt_index >= attempts - 1:
            return payload
        time.sleep(backoff_seconds * (2**attempt_index))

    if last_payload is not None:
        return last_payload
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("codex prompt retries exhausted without payload or exception")


def _codex_payload_looks_complete(payload: dict[str, Any]) -> bool:
    try:
        returncode = int(payload.get("returncode") or 0)
    except (TypeError, ValueError):
        returncode = 1
    if returncode != 0:
        return False
    response = str(payload.get("response") or "").strip()
    return bool(response)


def _resolve_line_role_codex_max_inflight() -> int:
    raw_value = str(os.getenv(_LINE_ROLE_CODEX_MAX_INFLIGHT_ENV) or "").strip()
    if not raw_value:
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    try:
        parsed = int(raw_value)
    except ValueError:
        return _LINE_ROLE_CODEX_MAX_INFLIGHT_DEFAULT
    return max(1, min(parsed, 32))


def _resolve_line_role_cache_path(
    *,
    source_hash: str | None,
    settings: RunSettings,
    ordered_candidates: Sequence[AtomicLineCandidate],
    artifact_root: Path | None,
    cache_root: Path | None,
    codex_timeout_seconds: int,
    codex_batch_size: int,
) -> Path | None:
    normalized_source_hash = str(source_hash or "").strip()
    if not normalized_source_hash:
        return None
    resolved_root = _resolve_line_role_cache_root(
        artifact_root=artifact_root,
        cache_root=cache_root,
    )
    if resolved_root is None:
        return None
    candidate_fingerprint = _canonical_candidate_fingerprint(ordered_candidates)
    key_payload = {
        "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
        "source_hash": normalized_source_hash,
        "run_settings_hash": settings.stable_hash(),
        "candidate_fingerprint": candidate_fingerprint,
        "codex_timeout_seconds": int(codex_timeout_seconds),
        "codex_batch_size": int(codex_batch_size),
    }
    digest = hashlib.sha256(
        json.dumps(
            key_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return resolved_root / digest[:2] / f"{digest}.json"


def _resolve_line_role_cache_root(
    *,
    artifact_root: Path | None,
    cache_root: Path | None,
) -> Path | None:
    if cache_root is not None:
        return cache_root.expanduser()
    override = str(os.getenv(_LINE_ROLE_CACHE_ROOT_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    if artifact_root is None:
        return None
    resolved_artifact_root = artifact_root.expanduser().resolve()
    for parent in (resolved_artifact_root, *resolved_artifact_root.parents):
        if parent.name in {"benchmark-vs-golden", "sent-to-labelstudio"}:
            return parent / ".cache" / "canonical_line_role"
    return resolved_artifact_root / ".cache" / "canonical_line_role"


def _canonical_candidate_fingerprint(
    candidates: Sequence[AtomicLineCandidate],
) -> str:
    payload: list[dict[str, Any]] = []
    for candidate in candidates:
        payload.append(
            {
                "recipe_id": candidate.recipe_id,
                "block_id": candidate.block_id,
                "block_index": candidate.block_index,
                "atomic_index": candidate.atomic_index,
                "text": candidate.text,
                "within_recipe_span": candidate.within_recipe_span,
                "candidate_labels": list(candidate.candidate_labels),
                "prev_text": candidate.prev_text,
                "next_text": candidate.next_text,
                "rule_tags": list(candidate.rule_tags),
            }
        )
    canonical_json = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _load_cached_predictions(
    *,
    cache_path: Path,
    expected_candidates: Sequence[AtomicLineCandidate],
) -> list[CanonicalLineRolePrediction] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != _LINE_ROLE_CACHE_SCHEMA_VERSION:
        return None
    raw_predictions = payload.get("predictions")
    if not isinstance(raw_predictions, list):
        return None
    predictions: list[CanonicalLineRolePrediction] = []
    try:
        for row in raw_predictions:
            predictions.append(CanonicalLineRolePrediction.model_validate(row))
    except Exception:
        return None
    if len(predictions) != len(expected_candidates):
        return None
    for candidate, prediction in zip(expected_candidates, predictions):
        if int(candidate.atomic_index) != int(prediction.atomic_index):
            return None
        if str(candidate.text) != str(prediction.text):
            return None
    return predictions


def _write_cached_predictions(
    *,
    cache_path: Path | None,
    predictions: Sequence[CanonicalLineRolePrediction],
) -> None:
    if cache_path is None:
        return
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _LINE_ROLE_CACHE_SCHEMA_VERSION,
            "predictions": [row.model_dump(mode="json") for row in predictions],
        }
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp_path.replace(cache_path)
    except OSError:
        return


def _line_role_pipeline_name(settings: RunSettings) -> str:
    value = getattr(settings, "line_role_pipeline", "off")
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value or "off")


def _deterministic_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> tuple[str | None, float, list[str]]:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "note_prefix" in tags or _looks_note_text(candidate.text):
        return "RECIPE_NOTES", 0.99, ["note_prefix"]
    if "variant_heading" in tags or _looks_variant_heading_text(candidate.text):
        return "RECIPE_VARIANT", 0.98, ["variant_heading"]
    if _looks_editorial_note(candidate.text):
        if candidate.within_recipe_span:
            return "RECIPE_NOTES", 0.84, ["editorial_note"]
        return "RECIPE_NOTES", 0.84, ["outside_recipe_editorial_note"]
    if (
        not candidate.within_recipe_span
        and _looks_recipe_note_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        return "RECIPE_NOTES", 0.82, ["outside_recipe_note_prose"]
    if (
        not candidate.within_recipe_span
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        if _looks_narrative_prose(candidate.text):
            return "OTHER", 0.74, ["outside_recipe_narrative"]
        if _looks_explicit_knowledge_cue(candidate.text):
            return "KNOWLEDGE", 0.9, [
                "outside_recipe_span",
                "prose_like",
                "explicit_knowledge_cue",
            ]
        return "OTHER", 0.72, ["outside_recipe_span", "prose_default_other"]
    if "yield_prefix" in tags:
        return "YIELD_LINE", 0.99, ["yield_prefix"]
    if "howto_heading" in tags:
        return "HOWTO_SECTION", 0.99, ["howto_heading"]
    if _looks_subsection_heading_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "HOWTO_SECTION", 0.9, ["subsection_heading_context"]
    if "note_like_prose" in tags:
        return "RECIPE_NOTES", 0.91, ["note_like_prose"]
    if "ingredient_like" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", 0.84, ["title_like", "ingredient_heading_override"]
        return "INGREDIENT_LINE", 0.98, ["ingredient_like"]
    if "instruction_with_time" in tags:
        return "INSTRUCTION_LINE", 0.96, ["instruction_with_time"]
    if "instruction_like" in tags:
        return "INSTRUCTION_LINE", 0.95, ["instruction_like"]
    if "time_metadata" in tags and _is_primary_time_line(candidate.text):
        return "TIME_LINE", 0.95, ["time_metadata"]
    if "outside_recipe_span" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", 0.79, ["title_like", "outside_recipe_span"]
        if _looks_prose(candidate.text):
            if _looks_narrative_prose(candidate.text):
                return "OTHER", 0.7, ["outside_recipe_narrative", "outside_recipe_span"]
            if _looks_explicit_knowledge_cue(candidate.text):
                return "KNOWLEDGE", 0.86, [
                    "outside_recipe_span",
                    "prose_like",
                    "explicit_knowledge_cue",
                ]
            return "OTHER", 0.66, ["outside_recipe_span", "prose_default_other"]
        return "OTHER", 0.65, ["outside_recipe_span"]
    if "RECIPE_TITLE" in candidate.candidate_labels and _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_TITLE", 0.8, ["title_like"]
    return None, 0.0, ["needs_disambiguation"]


def _candidate_allowlist(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> list[str]:
    if candidate.candidate_labels:
        labels = [
            label
            for label in candidate.candidate_labels
            if label in FREEFORM_ALLOWED_LABELS
        ]
    else:
        labels = list(FREEFORM_LABELS)
    if _should_offer_recipe_title(candidate) and "RECIPE_TITLE" not in labels:
        labels = ["RECIPE_TITLE", *labels]
    if not labels:
        labels = ["OTHER"]
    if (
        candidate.within_recipe_span
        and "KNOWLEDGE" in labels
        and not _knowledge_allowed_inside_recipe(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        labels = [label for label in labels if label != "KNOWLEDGE"]
        if not labels:
            labels = ["OTHER"]
    return labels


def _fallback_prediction(
    candidate: AtomicLineCandidate,
    *,
    reason: str,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> CanonicalLineRolePrediction:
    if by_atomic_index is None:
        by_atomic_index = {int(candidate.atomic_index): candidate}
    candidate_labels = _candidate_allowlist(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    deterministic_label, deterministic_confidence, deterministic_tags = _deterministic_label(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if deterministic_label is not None and deterministic_label in FREEFORM_ALLOWED_LABELS:
        label = deterministic_label
        confidence = max(0.35, float(deterministic_confidence))
        reason_tags = [reason, "deterministic_recovered", *deterministic_tags]
    else:
        label = "OTHER"
        confidence = 0.35
        reason_tags = [reason, "deterministic_unavailable"]
    return CanonicalLineRolePrediction(
        recipe_id=candidate.recipe_id,
        block_id=str(candidate.block_id),
        block_index=int(candidate.block_index),
        atomic_index=int(candidate.atomic_index),
        text=str(candidate.text),
        within_recipe_span=bool(candidate.within_recipe_span),
        label=label,
        confidence=confidence,
        decided_by="fallback",
        candidate_labels=list(candidate_labels),
        reason_tags=reason_tags,
    )


def _sanitize_prediction(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = prediction.label if prediction.label in FREEFORM_ALLOWED_LABELS else "OTHER"
    candidate_labels = _candidate_allowlist(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if label not in candidate_labels:
        candidate_labels = [label, *candidate_labels]
    reason_tags = list(prediction.reason_tags)
    decided_by = prediction.decided_by
    if (
        label == "KNOWLEDGE"
        and candidate.within_recipe_span
        and not _knowledge_allowed_inside_recipe(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = "OTHER"
        decided_by = "fallback"
        reason_tags.append("sanitized_knowledge_inside_recipe")
    if label == "TIME_LINE" and not _is_primary_time_line(candidate.text):
        label = "INSTRUCTION_LINE" if candidate.within_recipe_span else "OTHER"
        decided_by = "fallback"
        reason_tags.append(
            "sanitized_time_to_instruction"
            if candidate.within_recipe_span
            else "sanitized_time_to_other"
        )
    if (
        label in {"OTHER", "KNOWLEDGE", "RECIPE_NOTES", "INSTRUCTION_LINE", "TIME_LINE"}
        and _should_rescue_neighbor_ingredient_fragment(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = "INGREDIENT_LINE"
        decided_by = "fallback"
        reason_tags.append("sanitized_neighbor_ingredient_fragment")
    if label == "YIELD_LINE":
        if _looks_obvious_ingredient(candidate):
            label = "INGREDIENT_LINE"
            decided_by = "fallback"
            reason_tags.append("sanitized_yield_to_ingredient")
        elif not _looks_strict_yield_header(candidate.text):
            label = _yield_fallback_label(candidate)
            decided_by = "fallback"
            reason_tags.append(
                "sanitized_yield_to_instruction"
                if label == "INSTRUCTION_LINE"
                else "sanitized_yield_non_header"
            )
    return CanonicalLineRolePrediction(
        recipe_id=prediction.recipe_id,
        block_id=prediction.block_id,
        block_index=prediction.block_index,
        atomic_index=prediction.atomic_index,
        text=prediction.text,
        within_recipe_span=prediction.within_recipe_span,
        label=label,
        confidence=prediction.confidence,
        decided_by=decided_by,
        candidate_labels=list(candidate_labels),
        reason_tags=reason_tags,
    )


def _should_escalate_low_confidence_candidate(
    *,
    candidate: AtomicLineCandidate,
    deterministic_label: str | None,
    confidence: float,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if float(confidence) >= _CODEX_LOW_CONFIDENCE_THRESHOLD:
        return False
    if deterministic_label == "RECIPE_TITLE":
        return False
    candidate_allowlist = _candidate_allowlist(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if deterministic_label is not None and deterministic_label not in candidate_allowlist:
        return False
    return len(candidate_allowlist) > 1


def _is_primary_time_line(text: str) -> bool:
    if _TIME_PREFIX_RE.search(text):
        return True
    if _INSTRUCTION_VERB_RE.match(text):
        return False
    words = _PROSE_WORD_RE.findall(text)
    if len(words) <= 8 and re.search(
        r"\b\d+\s*(?:sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b",
        text,
        re.IGNORECASE,
    ):
        return True
    return False


def _looks_prose(text: str) -> bool:
    words = _PROSE_WORD_RE.findall(text)
    if len(words) < 10:
        return False
    if _QUANTITY_LINE_RE.match(text):
        return False
    if _INSTRUCTION_VERB_RE.match(text):
        return False
    return "." in text or "," in text


def _knowledge_allowed_inside_recipe(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if not candidate.within_recipe_span:
        return True
    if not _has_explicit_prose_tag(candidate):
        return False
    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if prev_candidate is None or next_candidate is None:
        return False
    return _has_explicit_prose_tag(prev_candidate) and _has_explicit_prose_tag(
        next_candidate
    )


def _has_explicit_prose_tag(candidate: AtomicLineCandidate) -> bool:
    return "explicit_prose" in {str(tag) for tag in candidate.rule_tags}


def _looks_obvious_ingredient(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "ingredient_like" in tags:
        return True
    text = str(candidate.text or "")
    if _QUANTITY_LINE_RE.match(text) and _INGREDIENT_UNIT_RE.search(text):
        return True
    return False


def _looks_quantity_unit_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if not _QUANTITY_LINE_RE.match(stripped):
        return False
    if not _INGREDIENT_UNIT_RE.search(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    return 1 <= len(words) <= 4


def _looks_short_ingredient_name_fragment(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if re.search(
        r"\b\d+\s*(?:sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b",
        stripped,
        re.IGNORECASE,
    ):
        return False
    if any(ch in stripped for ch in ",;:.!?"):
        return False
    if not _INGREDIENT_NAME_FRAGMENT_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 3):
        return False
    lowered = {word.lower() for word in words}
    return not lowered.issubset(_INGREDIENT_FRAGMENT_STOPWORDS)


def _neighbor_is_ingredient_dominant(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if "ingredient_like" in tags:
        return True
    if _looks_obvious_ingredient(candidate):
        return True
    labels = {str(label).strip().upper() for label in candidate.candidate_labels}
    if "INGREDIENT_LINE" in labels and not (
        {"instruction_like", "instruction_with_time"} & tags
    ):
        return True
    return False


def _should_rescue_neighbor_ingredient_fragment(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if not candidate.within_recipe_span:
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if text[-1:] in {".", "!", "?"}:
        return False

    quantity_fragment = _looks_quantity_unit_fragment(text)
    short_name_fragment = _looks_short_ingredient_name_fragment(text)
    if not (quantity_fragment or short_name_fragment):
        return False

    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    neighbors = [row for row in (prev_candidate, next_candidate) if row is not None]
    if not neighbors:
        return False

    ingredient_neighbor_count = sum(
        1 for row in neighbors if _neighbor_is_ingredient_dominant(row)
    )
    if ingredient_neighbor_count <= 0:
        return False

    if short_name_fragment:
        has_adjacent_quantity_fragment = any(
            _looks_quantity_unit_fragment(str(row.text or "")) for row in neighbors
        )
        if not has_adjacent_quantity_fragment:
            return ingredient_neighbor_count >= 2
    return True


def _looks_recipe_title(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) < 2 or len(words) > 12:
        return False
    if _NOTE_PREFIX_RE.match(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if _HOWTO_PREFIX_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    if uppercase_words >= max(2, len(words) // 2):
        return True
    title_case_words = sum(1 for word in words if word[:1].isupper())
    return title_case_words >= max(2, len(words) - 1)


def _looks_recipe_title_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if not _looks_recipe_title(candidate.text):
        return False
    if by_atomic_index is None:
        return _looks_compact_heading(candidate.text)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if next_candidate is None:
        return _looks_compact_heading(candidate.text)
    next_tags = {str(tag) for tag in next_candidate.rule_tags}
    next_text = str(next_candidate.text or "")
    if _looks_recipe_start_boundary(next_candidate):
        return True
    if _neighbor_is_ingredient_dominant(next_candidate):
        return True
    if _looks_instructional_neighbor(next_candidate):
        return True
    if {
        "instruction_like",
        "instruction_with_time",
        "ingredient_like",
        "yield_prefix",
        "howto_heading",
    } & next_tags:
        return True
    if _looks_narrative_prose(next_text):
        return False
    if "outside_recipe_span" in next_tags and _looks_prose(next_text):
        return False
    return False


def _looks_subsection_heading_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    if not _looks_recipe_title(candidate.text):
        return False
    if not _looks_compact_heading(candidate.text):
        return False

    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if next_candidate is None:
        return False
    if _looks_recipe_start_boundary(next_candidate):
        return False

    prev_flow = _looks_recipe_flow_neighbor(prev_candidate)
    next_instruction = _looks_instructional_neighbor(next_candidate)
    prev_heading = (
        prev_candidate is not None and _looks_compact_heading(prev_candidate.text)
    )
    return next_instruction and (prev_flow or prev_heading)


def _looks_recipe_start_boundary(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "yield_prefix" in tags:
        return True
    return bool(_YIELD_PREFIX_RE.match(str(candidate.text or "")))


def _looks_recipe_flow_neighbor(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if {
        "ingredient_like",
        "instruction_like",
        "instruction_with_time",
        "howto_heading",
        "yield_prefix",
    } & tags:
        return True
    if _looks_obvious_ingredient(candidate):
        return True
    if _looks_instructional_neighbor(candidate):
        return True
    return False


def _looks_instructional_neighbor(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _INSTRUCTION_VERB_RE.match(text):
        return True
    if _RECIPE_ACTION_CUE_RE.match(text):
        return True
    if _FIRST_PERSON_RE.search(text):
        return False
    if _INSTRUCTION_LEADIN_RE.match(text) and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    if "." in text and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    return False


def _looks_compact_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 2 or len(words) > 5:
        return False
    alpha_chars = sum(1 for ch in stripped if ch.isalpha())
    if alpha_chars <= 0:
        return False
    uppercase_chars = sum(1 for ch in stripped if ch.isupper())
    return (uppercase_chars / alpha_chars) >= 0.68


def _should_offer_recipe_title(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if any(
        blocked in tags
        for blocked in {
            "note_prefix",
            "yield_prefix",
            "howto_heading",
            "instruction_like",
            "instruction_with_time",
            "time_metadata",
        }
    ):
        return False
    return _looks_recipe_title(candidate.text)


def _looks_note_text(text: str) -> bool:
    return bool(_NOTE_PREFIX_RE.match(text))


def _looks_variant_heading_text(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_note_text(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if _HOWTO_PREFIX_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    lowered = stripped.lower()
    if lowered in _VARIANT_EXPLICIT_HEADINGS:
        return True
    if lowered.startswith("with "):
        return True
    upper_text = stripped.upper()
    if any(upper_text.endswith(suffix) for suffix in _VARIANT_RECIPE_SUFFIXES):
        alpha_chars = sum(1 for ch in stripped if ch.isalpha())
        uppercase_chars = sum(1 for ch in stripped if ch.isupper())
        uppercase_ratio = (uppercase_chars / alpha_chars) if alpha_chars else 0.0
        return uppercase_ratio >= 0.70
    return False


def _looks_editorial_note(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_note_text(stripped):
        return True
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 8:
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _EDITORIAL_NOTE_PREFIXES):
        return True
    if lowered.startswith("you ") and "want" in lowered and len(words) >= 10:
        return True
    return False


def _looks_recipe_note_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 12:
        return False
    if not _RECIPE_CONTEXT_RE.search(stripped):
        return False
    if _FIRST_PERSON_RE.search(stripped):
        return True
    if "you can" in lowered or "make sure" in lowered:
        return True
    if "don't" in lowered or "it's important" in lowered:
        return True
    if "the key is" in lowered:
        return True
    if any(
        lowered.startswith(prefix)
        for prefix in ("well,", "but ", "whatever liquid you choose")
    ):
        return True
    return False


def _looks_narrative_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return True
    return bool(_FIRST_PERSON_RE.search(stripped) and not _RECIPE_CONTEXT_RE.search(stripped))


def _looks_strict_yield_header(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    match = _YIELD_PREFIX_RE.match(stripped)
    if match is None:
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 10):
        return False
    if len(stripped) > 72:
        return False
    suffix = stripped[match.end() :].strip(" :-")
    if not suffix:
        return False
    return bool(_YIELD_COUNT_HINT_RE.search(suffix))


def _yield_fallback_label(candidate: AtomicLineCandidate) -> str:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if _INSTRUCTION_VERB_RE.match(text) or lowered.startswith("serves "):
        return "INSTRUCTION_LINE" if candidate.within_recipe_span else "OTHER"
    if _looks_recipe_note_prose(text) or _looks_editorial_note(text):
        return "RECIPE_NOTES"
    return "OTHER"


def _looks_explicit_knowledge_cue(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return bool(_EXPLICIT_KNOWLEDGE_CUE_RE.search(stripped))


def _parse_codex_line_role_response(
    raw_response: str,
    *,
    requested: Sequence[AtomicLineCandidate],
    allowed_by_index: dict[int, list[str]],
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return [], f"invalid_json:{exc.msg}"
    if not isinstance(payload, list):
        return [], "payload_not_list"

    requested_indices = [int(candidate.atomic_index) for candidate in requested]
    seen: set[int] = set()
    parsed: list[dict[str, Any]] = []
    for row in payload:
        if not isinstance(row, dict):
            return [], "row_not_object"
        raw_index = row.get("atomic_index")
        try:
            atomic_index = int(raw_index)
        except (TypeError, ValueError):
            return [], "missing_or_invalid_atomic_index"
        if atomic_index in seen:
            return [], "duplicate_atomic_index"
        if atomic_index not in requested_indices:
            return [], "unexpected_atomic_index"
        normalized_label = normalize_freeform_label(str(row.get("label") or ""))
        if normalized_label not in FREEFORM_ALLOWED_LABELS:
            return [], f"unknown_label:{normalized_label}"
        allowed = set(allowed_by_index.get(atomic_index) or [])
        if normalized_label not in allowed:
            return [], f"label_outside_allowlist:{atomic_index}:{normalized_label}"
        seen.add(atomic_index)
        parsed.append({"atomic_index": atomic_index, "label": normalized_label})

    if seen != set(requested_indices):
        return [], "missing_atomic_index_rows"
    ordered_parsed = sorted(parsed, key=lambda row: requested_indices.index(row["atomic_index"]))
    return ordered_parsed, None


def _batch(
    rows: Sequence[AtomicLineCandidate],
    batch_size: int,
) -> list[list[AtomicLineCandidate]]:
    output: list[list[AtomicLineCandidate]] = []
    current: list[AtomicLineCandidate] = []
    for row in rows:
        current.append(row)
        if len(current) >= batch_size:
            output.append(current)
            current = []
    if current:
        output.append(current)
    return output


class _PromptLogState:
    def __init__(self, *, artifact_root: Path | None) -> None:
        self._counter = 0
        self._counter_lock = threading.Lock()
        self._dedup_lock = threading.Lock()
        self._artifact_root = artifact_root
        self._prompt_dir = (
            None
            if artifact_root is None
            else artifact_root / "line-role-pipeline" / "prompts"
        )
        if self._prompt_dir is not None:
            self._prompt_dir.mkdir(parents=True, exist_ok=True)

    def next_index(self) -> int:
        with self._counter_lock:
            self._counter += 1
            return self._counter

    def prompt_path(self, index: int) -> Path | None:
        if self._prompt_dir is None:
            return None
        return self._prompt_dir / f"prompt_{index:04d}.txt"

    def response_path(self, index: int) -> Path | None:
        if self._prompt_dir is None:
            return None
        return self._prompt_dir / f"response_{index:04d}.txt"

    def parsed_path(self, index: int) -> Path | None:
        if self._prompt_dir is None:
            return None
        return self._prompt_dir / f"parsed_{index:04d}.json"

    def append_dedup(
        self,
        *,
        prompt_text: str,
        response_text: str,
        prompt_index: int,
    ) -> None:
        if self._prompt_dir is None:
            return
        with self._dedup_lock:
            dedup_path = self._prompt_dir / "codex_prompt_log.dedup.txt"
            stable_hash = hashlib.sha256(
                f"{prompt_text}\n---\n{response_text}".encode("utf-8")
            ).hexdigest()
            existing_hashes: set[str] = set()
            if dedup_path.exists():
                try:
                    for line in dedup_path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        existing_hashes.add(line.split("\t", 1)[0].strip())
                except OSError:
                    existing_hashes = set()
            if stable_hash in existing_hashes:
                return
            with dedup_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stable_hash}\tprompt_{prompt_index:04d}\n")

    def write_parse_error_summary(self, *, parse_error_count: int) -> None:
        if self._prompt_dir is None:
            return
        summary_path = self._prompt_dir / "parse_errors.json"
        summary_path.write_text(
            json.dumps(
                {
                    "parse_error_count": int(parse_error_count),
                    "parse_error_present": bool(parse_error_count > 0),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
