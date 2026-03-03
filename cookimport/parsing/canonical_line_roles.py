from __future__ import annotations

import hashlib
import json
import re
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


class CanonicalLineRolePrediction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    block_id: str
    atomic_index: int
    text: str
    label: str
    confidence: float
    decided_by: Literal["rule", "codex", "fallback"]
    reason_tags: list[str] = Field(default_factory=list)


def label_atomic_lines(
    candidates: Sequence[AtomicLineCandidate],
    settings: RunSettings,
    *,
    artifact_root: Path | None = None,
    codex_timeout_seconds: int = 120,
    codex_batch_size: int = 40,
    codex_cmd: str | None = None,
    codex_runner: Callable[..., Any] | None = None,
) -> list[CanonicalLineRolePrediction]:
    ordered = list(candidates)
    if not ordered:
        return []
    by_atomic_index = {int(candidate.atomic_index): candidate for candidate in ordered}

    predictions: dict[int, CanonicalLineRolePrediction] = {}
    unresolved: list[AtomicLineCandidate] = []
    for candidate in ordered:
        label, confidence, tags = _deterministic_label(candidate)
        if label is None:
            unresolved.append(candidate)
            continue
        predictions[candidate.atomic_index] = CanonicalLineRolePrediction(
            block_id=str(candidate.block_id),
            atomic_index=int(candidate.atomic_index),
            text=str(candidate.text),
            label=label,
            confidence=confidence,
            decided_by="rule",
            reason_tags=tags,
        )

    mode = _line_role_pipeline_name(settings)
    parse_error_count = 0
    if mode == "codex-line-role-v1" and unresolved:
        log_state = _PromptLogState(artifact_root=artifact_root)
        for batch in _batch(unresolved, max(1, int(codex_batch_size))):
            batch_allowed = {
                candidate.atomic_index: _candidate_allowlist(
                    candidate,
                    by_atomic_index=by_atomic_index,
                )
                for candidate in batch
            }
            prompt_targets = [
                candidate.model_copy(
                    update={"candidate_labels": list(batch_allowed[candidate.atomic_index])}
                )
                for candidate in batch
            ]
            prompt_text = build_canonical_line_role_prompt(prompt_targets)
            prompt_index = log_state.next_index()
            prompt_path = log_state.prompt_path(prompt_index)
            if prompt_path is not None:
                prompt_path.write_text(prompt_text, encoding="utf-8")
            response_payload = run_codex_json_prompt(
                prompt=prompt_text,
                timeout_seconds=codex_timeout_seconds,
                cmd=codex_cmd or default_codex_exec_cmd(),
                track_usage=False,
                runner=codex_runner,
            )
            raw_response = str(response_payload.get("response") or "")
            response_path = log_state.response_path(prompt_index)
            if response_path is not None:
                response_path.write_text(raw_response, encoding="utf-8")

            parsed_rows, error = _parse_codex_line_role_response(
                raw_response,
                requested=batch,
                allowed_by_index=batch_allowed,
            )
            parsed_path = log_state.parsed_path(prompt_index)
            if error is not None:
                parse_error_count += 1
                for candidate in batch:
                    predictions[candidate.atomic_index] = _fallback_prediction(
                        candidate,
                        reason="codex_parse_error",
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
            else:
                for row in parsed_rows:
                    candidate = by_atomic_index[row["atomic_index"]]
                    predictions[candidate.atomic_index] = CanonicalLineRolePrediction(
                        block_id=str(candidate.block_id),
                        atomic_index=int(candidate.atomic_index),
                        text=str(candidate.text),
                        label=row["label"],
                        confidence=0.75,
                        decided_by="codex",
                        reason_tags=["codex_line_role"],
                    )
                if parsed_path is not None:
                    parsed_path.write_text(
                        json.dumps(parsed_rows, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
            log_state.append_dedup(
                prompt_text=prompt_text,
                response_text=raw_response,
                prompt_index=prompt_index,
            )
        log_state.write_parse_error_summary(parse_error_count=parse_error_count)

    for candidate in unresolved:
        if candidate.atomic_index not in predictions:
            predictions[candidate.atomic_index] = _fallback_prediction(
                candidate,
                reason="deterministic_unresolved",
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
    return sanitized


def _line_role_pipeline_name(settings: RunSettings) -> str:
    value = getattr(settings, "line_role_pipeline", "off")
    if hasattr(value, "value"):
        return str(getattr(value, "value"))
    return str(value or "off")


def _deterministic_label(
    candidate: AtomicLineCandidate,
) -> tuple[str | None, float, list[str]]:
    tags = {str(tag) for tag in candidate.rule_tags}
    if (
        not candidate.within_recipe_span
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        return "KNOWLEDGE", 0.9, ["outside_recipe_span", "prose_like"]
    if "note_prefix" in tags and candidate.within_recipe_span:
        return "RECIPE_NOTES", 0.99, ["note_prefix"]
    if "yield_prefix" in tags:
        return "YIELD_LINE", 0.99, ["yield_prefix"]
    if "howto_heading" in tags:
        return "HOWTO_SECTION", 0.99, ["howto_heading"]
    if "variant_heading" in tags:
        return "RECIPE_VARIANT", 0.98, ["variant_heading"]
    if "ingredient_like" in tags:
        return "INGREDIENT_LINE", 0.98, ["ingredient_like"]
    if "instruction_with_time" in tags:
        return "INSTRUCTION_LINE", 0.96, ["instruction_with_time"]
    if "instruction_like" in tags:
        return "INSTRUCTION_LINE", 0.95, ["instruction_like"]
    if "time_metadata" in tags and _is_primary_time_line(candidate.text):
        return "TIME_LINE", 0.95, ["time_metadata"]
    if "outside_recipe_span" in tags:
        if _looks_prose(candidate.text):
            return "KNOWLEDGE", 0.86, ["outside_recipe_span", "prose_like"]
        return "OTHER", 0.65, ["outside_recipe_span"]
    if "RECIPE_TITLE" in candidate.candidate_labels and _looks_recipe_title(candidate.text):
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
) -> CanonicalLineRolePrediction:
    label = "OTHER"
    for option in candidate.candidate_labels:
        if option in FREEFORM_ALLOWED_LABELS:
            label = option
            break
    return CanonicalLineRolePrediction(
        block_id=str(candidate.block_id),
        atomic_index=int(candidate.atomic_index),
        text=str(candidate.text),
        label=label,
        confidence=0.35,
        decided_by="fallback",
        reason_tags=[reason],
    )


def _sanitize_prediction(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = prediction.label if prediction.label in FREEFORM_ALLOWED_LABELS else "OTHER"
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
    if label == "YIELD_LINE" and _looks_obvious_ingredient(candidate):
        label = "INGREDIENT_LINE"
        decided_by = "fallback"
        reason_tags.append("sanitized_yield_to_ingredient")
    return CanonicalLineRolePrediction(
        block_id=prediction.block_id,
        atomic_index=prediction.atomic_index,
        text=prediction.text,
        label=label,
        confidence=prediction.confidence,
        decided_by=decided_by,
        reason_tags=reason_tags,
    )


def _is_primary_time_line(text: str) -> bool:
    if _TIME_PREFIX_RE.search(text):
        return True
    words = _PROSE_WORD_RE.findall(text)
    if len(words) <= 8 and re.search(r"\b\d+\s*(?:sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b", text, re.IGNORECASE):
        return True
    if _INSTRUCTION_VERB_RE.match(text):
        return False
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
    if not _looks_prose(candidate.text):
        return False
    prev_candidate = by_atomic_index.get(candidate.atomic_index - 1)
    next_candidate = by_atomic_index.get(candidate.atomic_index + 1)
    if prev_candidate is None or next_candidate is None:
        return False
    return _looks_prose(prev_candidate.text) and _looks_prose(next_candidate.text)


def _looks_obvious_ingredient(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if "ingredient_like" in tags:
        return True
    text = str(candidate.text or "")
    if _QUANTITY_LINE_RE.match(text) and _INGREDIENT_UNIT_RE.search(text):
        return True
    return False


def _looks_recipe_title(text: str) -> bool:
    words = _PROSE_WORD_RE.findall(text)
    if not words or len(words) > 12:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    return uppercase_words >= max(2, len(words) // 2)


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
        self._artifact_root = artifact_root
        self._prompt_dir = (
            None
            if artifact_root is None
            else artifact_root / "line-role-pipeline" / "prompts"
        )
        if self._prompt_dir is not None:
            self._prompt_dir.mkdir(parents=True, exist_ok=True)

    def next_index(self) -> int:
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
