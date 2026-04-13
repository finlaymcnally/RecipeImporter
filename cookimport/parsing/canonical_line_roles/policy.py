from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from cookimport.labelstudio.label_config_freeform import FREEFORM_ALLOWED_LABELS
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    build_atomic_index_lookup,
)

from . import (
    _BOOK_FRAMING_EXHORTATION_CUE_RE,
    _COPYRIGHT_LEGAL_RE,
    _EDITORIAL_NOTE_PREFIXES,
    _ENDORSEMENT_BLURB_CUE_RE,
    _EXPLICIT_KNOWLEDGE_CUE_RE,
    _FIRST_PERSON_RE,
    _FIRST_PERSON_SINGULAR_RE,
    _FRONT_MATTER_EXCLUSION_HEADINGS,
    _FRONT_MATTER_NAVIGATION_HEADINGS,
    _HOW_TO_TITLE_PREFIX_RE,
    _HOWTO_PREFIX_RE,
    _INGREDIENT_FRAGMENT_STOPWORDS,
    _INGREDIENT_NAME_FRAGMENT_RE,
    _INGREDIENT_UNIT_RE,
    _INSTRUCTION_LEADIN_RE,
    _INSTRUCTION_VERB_RE,
    _KNOWLEDGE_DOMAIN_CUE_RE,
    _KNOWLEDGE_EXPLANATION_CUE_RE,
    _KNOWLEDGE_HEADING_FORM_RE,
    _LINE_ROLE_MODEL_PAYLOAD_VERSION,
    _NAVIGATION_SECTION_RE,
    _NON_RECIPE_PROSE_PREFIXES,
    _NOTE_PREFIX_RE,
    _NUMBERED_STEP_RE,
    _PAGE_FURNITURE_RE,
    _PEDAGOGICAL_KNOWLEDGE_CUE_RE,
    _PEDAGOGICAL_KNOWLEDGE_HEADING_RE,
    _PROSE_WORD_RE,
    _PUBLISHER_PROMO_RE,
    _PUBLISHING_METADATA_RE,
    _QUANTITY_LINE_RE,
    _RECIPE_ACTION_CUE_RE,
    _RECIPE_CONTEXT_RE,
    _RECIPE_NOTE_ADVISORY_CUE_RE,
    _RECIPEISH_OUTSIDE_SPAN_LABELS,
    _SECOND_PERSON_RE,
    _SERVING_NOTE_PREFIX_RE,
    _STORAGE_NOTE_PREFIX_RE,
    _TIME_PREFIX_RE,
    _TITLE_CONNECTOR_WORDS,
    _unique_string_list,
    _VARIANT_EXPLICIT_HEADINGS,
    _VARIANT_GENERIC_HEADINGS,
    _VARIANT_RECIPE_SUFFIXES,
    _YIELD_COUNT_HINT_RE,
    _YIELD_PREFIX_RE,
)
from .contracts import (
    CANONICAL_LINE_ROLE_ALLOWED_LABELS,
    CanonicalLineRolePrediction,
    RECIPE_LOCAL_LINE_ROLE_LABELS,
    sanitize_pre_grouping_line_role_candidates,
)
from .prompt_inputs import (
    serialize_line_role_debug_context_row,
    serialize_line_role_file_row,
    serialize_line_role_model_context_row,
    serialize_line_role_model_row,
)

_RECIPE_LOCAL_LABELS = set(RECIPE_LOCAL_LINE_ROLE_LABELS)

def _prediction_has_reason_tag(
    prediction: CanonicalLineRolePrediction,
    fragment: str,
) -> bool:
    return any(fragment in str(tag) for tag in prediction.reason_tags)


def _is_within_recipe_span(candidate: AtomicLineCandidate | CanonicalLineRolePrediction) -> bool:
    return candidate.within_recipe_span is True


def _is_outside_recipe_span(candidate: AtomicLineCandidate | CanonicalLineRolePrediction) -> bool:
    return candidate.within_recipe_span is False


def _apply_prediction_decision_metadata(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = str(prediction.label or "NONRECIPE_CANDIDATE")

    reasons: list[str] = []
    if _prediction_has_reason_tag(prediction, "deterministic_unresolved") or _prediction_has_reason_tag(
        prediction,
        "deterministic_unavailable",
    ):
        reasons.append("deterministic_unresolved")
    if prediction.decided_by == "fallback":
        reasons.append("fallback_decision")
    if _is_outside_recipe_span(candidate) and label in _RECIPEISH_OUTSIDE_SPAN_LABELS:
        reasons.append("outside_span_structured_label")
    if _prediction_has_reason_tag(prediction, "sanitized_"):
        reasons.append("sanitized_label_adjustment")
    if str(prediction.label or "").strip().upper() == "NONRECIPE_EXCLUDE":
        reasons.append("nonrecipe_excluded")

    payload = prediction.model_dump(mode="python")
    payload["escalation_reasons"] = _unique_string_list(reasons)
    return CanonicalLineRolePrediction.model_validate(payload)

def _build_line_role_deterministic_baseline(
    *,
    ordered_candidates: Sequence[AtomicLineCandidate],
) -> dict[int, CanonicalLineRolePrediction]:
    by_atomic_index = {
        int(candidate.atomic_index): candidate for candidate in ordered_candidates
    }
    baseline: dict[int, CanonicalLineRolePrediction] = {}
    for candidate in ordered_candidates:
        label, tags = _deterministic_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        if label is None:
            prediction = _fallback_prediction(
                candidate,
                reason="deterministic_unresolved",
                by_atomic_index=by_atomic_index,
            )
        else:
            prediction = CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                row_id=candidate.row_id,
                block_id=str(candidate.block_id),
                block_index=int(candidate.block_index),
                atomic_index=int(candidate.atomic_index),
                row_ordinal=int(candidate.row_ordinal),
                start_char_in_block=int(candidate.start_char_in_block),
                end_char_in_block=int(candidate.end_char_in_block),
                text=str(candidate.text),
                within_recipe_span=candidate.within_recipe_span,
                label=label,
                decided_by="rule",
                reason_tags=list(tags),
            )
        prediction = _apply_repo_baseline_semantic_policy(
            prediction=prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        prediction = _normalize_prediction_metadata(
            prediction=prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        baseline[int(candidate.atomic_index)] = _apply_prediction_decision_metadata(
            prediction=prediction,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
    return baseline


def build_line_role_debug_input_payload(
    *,
    shard_id: str,
    candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: Mapping[int, CanonicalLineRolePrediction],
    by_atomic_index: Mapping[int, AtomicLineCandidate] | None = None,
) -> dict[str, Any]:
    sanitized_candidates = sanitize_pre_grouping_line_role_candidates(candidates)
    rows = [
        serialize_line_role_file_row(
            candidate=candidate,
            escalation_reasons=deterministic_baseline[
                int(candidate.atomic_index)
            ].escalation_reasons,
        )
        for candidate in sanitized_candidates
    ]
    payload = {
        "shard_id": shard_id,
        "phase_key": "line_role",
        "rows": rows,
    }
    context_before_candidate, context_after_candidate = _build_line_role_boundary_context_candidates(
        candidates=sanitized_candidates,
        by_atomic_index=by_atomic_index,
    )
    if context_before_candidate is not None:
        payload["context_before_rows"] = [
            serialize_line_role_debug_context_row(candidate=context_before_candidate)
        ]
    if context_after_candidate is not None:
        payload["context_after_rows"] = [
            serialize_line_role_debug_context_row(candidate=context_after_candidate)
        ]
    return payload


def build_line_role_model_input_payload(
    *,
    shard_id: str,
    candidates: Sequence[AtomicLineCandidate],
    deterministic_baseline: Mapping[int, CanonicalLineRolePrediction],
    by_atomic_index: Mapping[int, AtomicLineCandidate] | None = None,
) -> dict[str, Any]:
    del deterministic_baseline
    payload = {
        "v": _LINE_ROLE_MODEL_PAYLOAD_VERSION,
        "shard_id": shard_id,
        "rows": [
            serialize_line_role_model_row(candidate=candidate)
            for candidate in candidates
        ],
    }
    context_before_candidate, context_after_candidate = _build_line_role_boundary_context_candidates(
        candidates=candidates,
        by_atomic_index=by_atomic_index,
    )
    if context_before_candidate is not None:
        payload["context_before_rows"] = [
            serialize_line_role_model_context_row(candidate=context_before_candidate)
        ]
    if context_after_candidate is not None:
        payload["context_after_rows"] = [
            serialize_line_role_model_context_row(candidate=context_after_candidate)
        ]
    return payload


def _build_line_role_boundary_context_candidates(
    *,
    candidates: Sequence[AtomicLineCandidate],
    by_atomic_index: Mapping[int, AtomicLineCandidate] | None = None,
) -> tuple[AtomicLineCandidate | None, AtomicLineCandidate | None]:
    if not candidates:
        return None, None
    resolved_lookup = by_atomic_index or build_atomic_index_lookup(candidates)
    first_atomic_index = int(candidates[0].atomic_index)
    last_atomic_index = int(candidates[-1].atomic_index)
    return (
        resolved_lookup.get(first_atomic_index - 1),
        resolved_lookup.get(last_atomic_index + 1),
    )


def _looks_front_matter_navigation_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _FRONT_MATTER_NAVIGATION_HEADINGS:
        return True
    if lowered.startswith("how to use this book"):
        return True
    return bool(_NAVIGATION_SECTION_RE.match(stripped))


def _looks_navigation_title_list_entry(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_front_matter_navigation_heading(stripped):
        return True
    if (
        _NOTE_PREFIX_RE.match(stripped)
        or _YIELD_PREFIX_RE.match(stripped)
        or _TIME_PREFIX_RE.search(stripped)
        or _QUANTITY_LINE_RE.match(stripped)
        or _NUMBERED_STEP_RE.match(stripped)
        or stripped[-1:] in {".", "!", "?"}
    ):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 8:
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if ":" in stripped:
        return True
    if len(words) == 1:
        return words[0][:1].isupper()
    return _looks_recipe_title(stripped) or _looks_compact_heading(stripped)


def _looks_chapter_taxonomy_heading_candidate(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_front_matter_navigation_heading(stripped):
        return True
    if _looks_table_of_contents_entry(stripped):
        return True
    if _looks_navigation_title_list_entry(stripped):
        return True
    if _looks_note_text(stripped) or _YIELD_PREFIX_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped) or _NUMBERED_STEP_RE.match(stripped):
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        return False
    if _looks_non_heading_howto_prose(stripped):
        return False
    if _looks_prose(stripped) and _looks_book_framing_or_exhortation_prose(stripped):
        return False
    if stripped.endswith("?"):
        words = _PROSE_WORD_RE.findall(stripped)
        if 2 <= len(words) <= 5 and re.match(r"^(what|how|why)\b", stripped, re.IGNORECASE):
            return True
    return _looks_obvious_knowledge_heading(stripped) or _looks_knowledge_heading_shape(
        stripped
    )


def _looks_page_furniture(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _PAGE_FURNITURE_RE.match(stripped) is not None


def _looks_publishing_metadata(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _PUBLISHING_METADATA_RE.search(stripped) is not None


def _looks_publisher_promo(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_publishing_metadata(stripped) or _looks_copyright_legal(stripped):
        return False
    if _PUBLISHER_PROMO_RE.search(stripped):
        return True
    lowered = stripped.lower()
    return (
        "thank you for downloading" in lowered
        or ("join our" in lowered and "mailing list" in lowered)
        or ("send you more of what you like to read" in lowered)
        or ("click below to sign up" in lowered)
    )


def _looks_copyright_legal(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return _COPYRIGHT_LEGAL_RE.search(stripped) is not None


def _looks_front_matter_exclusion_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered in _FRONT_MATTER_EXCLUSION_HEADINGS:
        return True
    return lowered.startswith("how to use this book")


def _looks_navigation_exclusion_candidate(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_table_of_contents_entry(text):
        return True
    if _looks_front_matter_navigation_heading(text) and not _looks_front_matter_exclusion_heading(
        text
    ):
        return True
    current_is_navigation_title_entry = _looks_navigation_title_list_entry(text)
    current_is_chapter_taxonomy_heading = _looks_chapter_taxonomy_heading_candidate(text)
    if by_atomic_index is None or not (
        current_is_navigation_title_entry or current_is_chapter_taxonomy_heading
    ):
        return False
    if _has_local_knowledge_prose_support(candidate, by_atomic_index=by_atomic_index):
        return False
    navigation_like_neighbors = 0
    for offset in (-2, -1, 1, 2):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "").strip()
        if (
            _looks_table_of_contents_entry(neighbor_text)
            or _looks_front_matter_navigation_heading(neighbor_text)
            or _looks_navigation_title_list_entry(neighbor_text)
            or _looks_chapter_taxonomy_heading_candidate(neighbor_text)
        ):
            navigation_like_neighbors += 1
    required_neighbor_count = 1 if current_is_navigation_title_entry else 2
    return navigation_like_neighbors >= required_neighbor_count


def _has_local_knowledge_prose_support(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
    radius: int = 3,
) -> bool:
    if by_atomic_index is None:
        return False
    center = int(candidate.atomic_index)
    for offset in range(1, max(1, int(radius)) + 1):
        for neighbor_index in (center - offset, center + offset):
            neighbor = by_atomic_index.get(neighbor_index)
            if neighbor is None or _is_within_recipe_span(neighbor):
                continue
            neighbor_text = str(neighbor.text or "").strip()
            if (
                _looks_explicit_knowledge_cue(neighbor_text)
                or _looks_domain_knowledge_prose(neighbor_text)
                or _looks_pedagogical_knowledge_prose(neighbor_text)
            ):
                return True
    return False


def _neighbor_candidates(
    *,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
    offsets: Sequence[int] = (-2, -1, 1, 2),
) -> list[AtomicLineCandidate]:
    if by_atomic_index is None:
        return []
    neighbors: list[AtomicLineCandidate] = []
    for offset in offsets:
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbors.append(neighbor)
    return neighbors


def _looks_endorsement_blurb_candidate(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text or not _looks_prose(text):
        return False
    endorsement_blurb_cue = _ENDORSEMENT_BLURB_CUE_RE.search(text) is not None
    if _looks_explicit_knowledge_cue(text):
        return False
    lowered = text.lower()
    quote_like = text.startswith('"') or text.startswith("'") or text.endswith('"')
    if not (
        quote_like
        or _looks_book_framing_or_exhortation_prose(text)
        or endorsement_blurb_cue
    ):
        return False
    neighbor_endorsements = sum(
        1
        for neighbor in _neighbor_candidates(
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
        if _looks_endorsement_credit(str(neighbor.text or "").strip())
    )
    if neighbor_endorsements <= 0:
        return False
    if _looks_domain_knowledge_prose(text) and not endorsement_blurb_cue:
        return False
    if (
        "guide" in lowered
        and _KNOWLEDGE_EXPLANATION_CUE_RE.search(text)
        and not endorsement_blurb_cue
    ):
        return False
    return True


def _looks_publisher_promo_candidate(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_publisher_promo(text):
        return True
    if not _looks_prose(text):
        return False
    if _looks_explicit_knowledge_cue(text) or _looks_domain_knowledge_prose(text):
        return False
    neighbors = _neighbor_candidates(
        candidate=candidate,
        by_atomic_index=by_atomic_index,
    )
    promo_like_neighbors = sum(
        1
        for neighbor in neighbors
        if _looks_publisher_promo(str(neighbor.text or "").strip())
    )
    if promo_like_neighbors <= 0:
        return False
    lowered = text.lower()
    return any(
        cue in lowered
        for cue in (
            "thank you",
            "subscriber",
            "ebook",
            "offers",
            "recommended reads",
            "terms and conditions",
            "sign up",
            "register",
        )
    )


def _outside_recipe_exclude_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if _is_within_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_page_furniture(text):
        return True
    if _looks_copyright_legal(text):
        return True
    if _looks_publishing_metadata(text):
        return True
    if _looks_endorsement_credit(text):
        return True
    if _looks_endorsement_blurb_candidate(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return True
    if _looks_publisher_promo_candidate(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return True
    if _looks_front_matter_exclusion_heading(text):
        return True
    if _looks_navigation_exclusion_candidate(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return True
    return False

def _deterministic_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> tuple[str | None, list[str]]:
    tags = {str(tag) for tag in candidate.rule_tags}
    howto_prose_label, howto_prose_reason_tags = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None:
        return howto_prose_label, howto_prose_reason_tags
    variant_context_label, variant_context_reason_tags = _classify_variant_run_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if variant_context_label is not None:
        return variant_context_label, variant_context_reason_tags
    if "note_prefix" in tags or _looks_note_text(candidate.text):
        return "RECIPE_NOTES", ["note_prefix"]
    if _looks_storage_or_serving_note(candidate.text):
        return "RECIPE_NOTES", ["storage_or_serving_note"]
    if _looks_editorial_note(candidate.text):
        if _is_within_recipe_span(candidate):
            return "RECIPE_NOTES", ["editorial_note"]
        return "RECIPE_NOTES", ["outside_recipe_editorial_note"]
    if (
        _is_outside_recipe_span(candidate)
        and _looks_recipe_note_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        return "RECIPE_NOTES", ["outside_recipe_note_prose"]
    if (
        _is_outside_recipe_span(candidate)
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        if _looks_narrative_prose(candidate.text):
            return "OTHER", ["outside_recipe_narrative"]
        return "OTHER", ["outside_recipe_span", "prose_default_other"]
    if (
        candidate.within_recipe_span is None
        and _looks_prose(candidate.text)
        and "ingredient_like" not in tags
        and "yield_prefix" not in tags
        and "howto_heading" not in tags
    ):
        if _looks_narrative_prose(candidate.text):
            return "OTHER", ["unknown_recipe_span", "narrative_default_other"]
        return "OTHER", ["unknown_recipe_span", "prose_default_other"]
    if "yield_prefix" in tags:
        return "YIELD_LINE", ["yield_prefix"]
    if "howto_heading" in tags and _howto_section_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "HOWTO_SECTION", ["howto_heading"]
    if _looks_subsection_heading_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        if (
            _is_outside_recipe_span(candidate)
            and _looks_recipe_title_with_context(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "subsection_heading_title_override"]
        return "HOWTO_SECTION", ["subsection_heading_context"]
    if "note_like_prose" in tags:
        return "RECIPE_NOTES", ["note_like_prose"]
    if "ingredient_like" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", ["title_like", "ingredient_heading_override"]
        return "INGREDIENT_LINE", ["ingredient_like"]
    if "instruction_with_time" in tags:
        return "INSTRUCTION_LINE", ["instruction_with_time"]
    if "instruction_like" in tags:
        if (
            _is_outside_recipe_span(candidate)
            and _looks_recipe_title_with_context(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "instruction_heading_override"]
        return "INSTRUCTION_LINE", ["instruction_like"]
    if "time_metadata" in tags and _is_primary_time_line(candidate.text):
        return "TIME_LINE", ["time_metadata"]
    if "outside_recipe_span" in tags:
        if _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            return "RECIPE_TITLE", ["title_like", "outside_recipe_span"]
        if _looks_prose(candidate.text):
            if _looks_narrative_prose(candidate.text):
                return "OTHER", ["outside_recipe_narrative", "outside_recipe_span"]
            return "OTHER", ["outside_recipe_span", "prose_default_other"]
        return "OTHER", ["outside_recipe_span"]
    if (
        "title_like" in tags or _looks_recipe_title(candidate.text)
    ) and _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_TITLE", ["title_like"]
    return None, ["needs_disambiguation"]


def _fallback_prediction(
    candidate: AtomicLineCandidate,
    *,
    reason: str,
    by_atomic_index: dict[int, AtomicLineCandidate] | None = None,
) -> CanonicalLineRolePrediction:
    if by_atomic_index is None:
        by_atomic_index = {int(candidate.atomic_index): candidate}
    deterministic_label, deterministic_tags = _deterministic_label(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if (
        deterministic_label is not None
        and deterministic_label in CANONICAL_LINE_ROLE_ALLOWED_LABELS
    ):
        label = deterministic_label
        reason_tags = [reason, "deterministic_recovered", *deterministic_tags]
    else:
        label = "RECIPE_NOTES" if _is_within_recipe_span(candidate) else "NONRECIPE_CANDIDATE"
        reason_tags = [reason, "deterministic_unavailable"]
    return CanonicalLineRolePrediction(
        recipe_id=candidate.recipe_id,
        row_id=candidate.row_id,
        block_id=str(candidate.block_id),
        block_index=int(candidate.block_index),
        atomic_index=int(candidate.atomic_index),
        row_ordinal=int(candidate.row_ordinal),
        start_char_in_block=int(candidate.start_char_in_block),
        end_char_in_block=int(candidate.end_char_in_block),
        text=str(candidate.text),
        within_recipe_span=candidate.within_recipe_span,
        label=label,
        decided_by="fallback",
        reason_tags=reason_tags,
    )

def _apply_repo_baseline_semantic_policy(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = (
        prediction.label
        if prediction.label in FREEFORM_ALLOWED_LABELS
        else "RECIPE_NOTES"
        if _is_within_recipe_span(candidate)
        else "NONRECIPE_CANDIDATE"
    )
    reason_tags = list(prediction.reason_tags)
    decided_by = prediction.decided_by
    if (
        label == "KNOWLEDGE"
        and _is_within_recipe_span(candidate)
        and not _knowledge_allowed_inside_recipe(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        label = "RECIPE_NOTES"
        decided_by = "fallback"
        reason_tags.append("sanitized_knowledge_inside_recipe")
    if label == "TIME_LINE" and not _is_primary_time_line(candidate.text):
        label = "RECIPE_NOTES" if _is_outside_recipe_span(candidate) else "INSTRUCTION_LINE"
        decided_by = "fallback"
        reason_tags.append(
            "sanitized_time_to_instruction"
            if not _is_outside_recipe_span(candidate)
            else "sanitized_time_to_recipe_notes"
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
    if (
        _is_outside_recipe_span(candidate)
        and label in _RECIPEISH_OUTSIDE_SPAN_LABELS
        and not _outside_span_structured_label_allowed(
            label=label,
            candidate=candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        if prediction.decided_by != "codex":
            fallback_label = _outside_span_nonstructured_fallback_label(
                candidate,
                by_atomic_index=by_atomic_index,
            )
            if fallback_label != label:
                label = fallback_label
                decided_by = "fallback"
                reason_tags.append("sanitized_outside_span_structured_label")
    if label in {"OTHER", "NONRECIPE_CANDIDATE"}:
        if _variant_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            label = "RECIPE_VARIANT"
            decided_by = "fallback"
            reason_tags.append("variant_component_cluster")
        elif _should_rescue_other_to_knowledge_label(
            candidate,
            by_atomic_index=by_atomic_index,
        ) and _is_within_recipe_span(candidate):
            label = "RECIPE_NOTES"
            decided_by = "fallback"
            reason_tags.append("recipe_note_component_cluster")
        elif _should_rescue_other_to_instruction_label(
            candidate,
            by_atomic_index=by_atomic_index,
        ):
            label = "INSTRUCTION_LINE"
            decided_by = "fallback"
            reason_tags.append("instruction_component_cluster")
    if label == "KNOWLEDGE" and not _is_within_recipe_span(candidate):
        label = "NONRECIPE_CANDIDATE"
        decided_by = "fallback"
        if "coerced_outside_recipe_knowledge_to_candidate" not in reason_tags:
            reason_tags.append("coerced_outside_recipe_knowledge_to_candidate")
    if label == "OTHER":
        label = "RECIPE_NOTES" if _is_within_recipe_span(candidate) else "NONRECIPE_CANDIDATE"
        decided_by = "fallback"
        reason_tags.append("coerced_other_to_live_contract_label")
    return CanonicalLineRolePrediction(
        recipe_id=prediction.recipe_id,
        row_id=prediction.row_id,
        block_id=prediction.block_id,
        block_index=prediction.block_index,
        atomic_index=prediction.atomic_index,
        row_ordinal=prediction.row_ordinal,
        start_char_in_block=prediction.start_char_in_block,
        end_char_in_block=prediction.end_char_in_block,
        text=prediction.text,
        within_recipe_span=prediction.within_recipe_span,
        label=label,
        decided_by=decided_by,
        reason_tags=reason_tags,
    )


def _normalize_prediction_metadata(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> CanonicalLineRolePrediction:
    label = str(prediction.label or "NONRECIPE_CANDIDATE")
    if prediction.decided_by == "codex":
        return CanonicalLineRolePrediction(
            recipe_id=prediction.recipe_id,
            row_id=prediction.row_id,
            block_id=prediction.block_id,
            block_index=prediction.block_index,
            atomic_index=prediction.atomic_index,
            row_ordinal=prediction.row_ordinal,
            start_char_in_block=prediction.start_char_in_block,
            end_char_in_block=prediction.end_char_in_block,
            text=prediction.text,
            within_recipe_span=prediction.within_recipe_span,
            label=label,
            decided_by=prediction.decided_by,
            reason_tags=_unique_string_list(str(tag) for tag in prediction.reason_tags),
        )
    if _is_within_recipe_span(candidate):
        if label in {"OTHER", "KNOWLEDGE", "NONRECIPE_CANDIDATE", "NONRECIPE_EXCLUDE"}:
            label = "RECIPE_NOTES"
    elif label not in _RECIPE_LOCAL_LABELS:
        if prediction.decided_by == "codex":
            if label in {"OTHER", "KNOWLEDGE"}:
                label = "NONRECIPE_CANDIDATE"
        else:
            label = (
                "NONRECIPE_EXCLUDE"
                if _outside_recipe_exclude_allowed(
                    candidate,
                    by_atomic_index=by_atomic_index,
                )
                else "NONRECIPE_CANDIDATE"
            )
    return CanonicalLineRolePrediction(
        recipe_id=prediction.recipe_id,
        row_id=prediction.row_id,
        block_id=prediction.block_id,
        block_index=prediction.block_index,
        atomic_index=prediction.atomic_index,
        row_ordinal=prediction.row_ordinal,
        start_char_in_block=prediction.start_char_in_block,
        end_char_in_block=prediction.end_char_in_block,
        text=prediction.text,
        within_recipe_span=prediction.within_recipe_span,
        label=label,
        decided_by=prediction.decided_by,
        reason_tags=_unique_string_list(str(tag) for tag in prediction.reason_tags),
    )


def _codex_prediction_policy_rejection_reason(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str | None:
    label = str(prediction.label or "NONRECIPE_CANDIDATE")
    if label == "NONRECIPE_EXCLUDE" and _is_within_recipe_span(candidate):
        return "nonrecipe_exclude_inside_recipe_not_allowed"
    if label == "KNOWLEDGE":
        return "knowledge_not_in_live_contract"
    if label == "OTHER":
        return "other_not_in_live_contract"
    return None


def _reject_codex_prediction_to_baseline_if_policy_violated(
    *,
    prediction: CanonicalLineRolePrediction,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
    baseline_prediction: CanonicalLineRolePrediction,
) -> CanonicalLineRolePrediction:
    del candidate
    del by_atomic_index
    del baseline_prediction
    return prediction


def _should_escalate_candidate(
    *,
    candidate: AtomicLineCandidate,
    deterministic_label: str | None,
    escalation_reasons: Sequence[str],
) -> bool:
    if _is_outside_recipe_span(candidate):
        return False
    if deterministic_label in {"RECIPE_TITLE", "RECIPE_VARIANT"}:
        return False
    if not escalation_reasons:
        return False
    return True

def _outside_span_has_neighboring_recipe_evidence(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    lower = int(candidate.atomic_index) - max(1, int(radius))
    upper = int(candidate.atomic_index) + max(1, int(radius))
    for atomic_index in range(lower, upper + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None:
            continue
        tags = {str(tag) for tag in row.rule_tags}
        if {
            "ingredient_like",
            "instruction_like",
            "instruction_with_time",
            "yield_prefix",
            "howto_heading",
            "variant_heading",
        } & tags:
            return True
        if _looks_obvious_ingredient(row) or _looks_instructional_neighbor(row):
            return True
        if _looks_recipe_start_boundary(row):
            return True
    return False


def _outside_span_structured_label_allowed(
    *,
    label: str,
    candidate: AtomicLineCandidate,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    has_neighboring_recipe_evidence = _outside_span_has_neighboring_recipe_evidence(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    has_neighboring_component_structure = _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if label == "RECIPE_TITLE":
        return _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "RECIPE_VARIANT":
        return _variant_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        ) or has_neighboring_component_structure
    if label == "HOWTO_SECTION":
        return _howto_section_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "INGREDIENT_LINE":
        return _looks_obvious_ingredient(candidate) and (
            _outside_span_has_neighboring_recipe_scaffold(
                candidate,
                by_atomic_index=by_atomic_index,
            )
            or _outside_span_has_adjacent_recipe_title(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
    if label == "INSTRUCTION_LINE":
        return _instruction_line_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if label == "YIELD_LINE":
        return _looks_strict_yield_header(text)
    return True


def _outside_span_nonstructured_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    text = str(candidate.text or "").strip()
    if _looks_recipe_note_prose(text) or _looks_editorial_note(text):
        return "RECIPE_NOTES"
    return "OTHER"


def _outside_span_has_neighboring_recipe_scaffold(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    lower = center - max(1, int(radius))
    upper = center + max(1, int(radius))
    for atomic_index in range(lower, upper + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None or _is_within_recipe_span(row):
            continue
        tags = {str(tag) for tag in row.rule_tags}
        text = str(row.text or "").strip()
        if not text:
            continue
        if {"yield_prefix", "howto_heading"} & tags:
            return True
        if _QUANTITY_LINE_RE.match(text):
            return True
        if _looks_quantity_unit_fragment(text):
            return True
        if _looks_direct_instruction_start(row):
            return True
        if _looks_recipe_start_boundary(row):
            return True
    return False


def _outside_span_has_adjacent_recipe_title(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    current_text = str(candidate.text or "").strip()
    if not (
        _QUANTITY_LINE_RE.match(current_text) or _looks_quantity_unit_fragment(current_text)
    ):
        return False
    for offset in (-1, 1):
        row = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if row is None or _is_within_recipe_span(row):
            continue
        text = str(row.text or "").strip()
        if not text:
            continue
        if _looks_recipe_title(text):
            return True
    return False


def _should_rescue_other_to_knowledge_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if not _is_within_recipe_span(candidate):
        return False
    if not _knowledge_allowed_inside_recipe(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    return not _variant_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _should_rescue_other_to_instruction_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    tags = {str(tag) for tag in candidate.rule_tags}
    if not text:
        return False
    if not _instruction_line_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if (
        _looks_recipe_note_prose(text)
        or _looks_storage_or_serving_note(text)
        or _looks_recipe_title_with_context(
            candidate,
            by_atomic_index=by_atomic_index,
        )
        or _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return False
    if _looks_direct_instruction_start(candidate) or _looks_non_heading_howto_prose(text):
        return True
    if _is_outside_recipe_span(candidate):
        return bool(
            {"instruction_like", "instruction_with_time"} & tags
        ) and _outside_span_has_neighboring_component_structure(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return bool({"instruction_like", "instruction_with_time"} & tags)


def _outside_span_has_neighboring_component_structure(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    lower = center - max(1, int(radius))
    upper = center + max(1, int(radius))
    for atomic_index in range(lower, upper + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None:
            continue
        tags = {str(tag) for tag in row.rule_tags}
        if {
            "ingredient_like",
            "yield_prefix",
            "howto_heading",
            "variant_heading",
        } & tags:
            return True
        if _looks_obvious_ingredient(row):
            return True
        if _looks_recipe_start_boundary(row):
            return True
        if _looks_direct_instruction_start(row):
            return True
    return False


def _outside_span_has_title_led_recipe_cluster(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 4,
) -> bool:
    center = int(candidate.atomic_index)
    saw_supported_title = False
    saw_recipe_cluster_support = False
    for atomic_index in range(center - max(1, int(radius)), center + max(1, int(radius)) + 1):
        if atomic_index == center:
            continue
        row = by_atomic_index.get(atomic_index)
        if row is None:
            continue
        text = str(row.text or "").strip()
        if not text:
            continue
        if _looks_recipe_title_with_context(
            row,
            by_atomic_index=by_atomic_index,
        ):
            saw_supported_title = True
            continue
        if (
            _neighbor_is_ingredient_dominant(row)
            or _looks_recipe_start_boundary(row)
            or _looks_direct_instruction_start(row)
            or _looks_instructional_neighbor(row)
            or _looks_storage_or_serving_note(text)
            or _looks_recipe_note_prose(text)
        ):
            saw_recipe_cluster_support = True
    return saw_supported_title and saw_recipe_cluster_support


def _classify_non_heading_howto_prose(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> tuple[str | None, list[str]]:
    text = str(candidate.text or "").strip()
    if not _looks_non_heading_howto_prose(text):
        return None, []
    lowered = text.lower()
    if lowered.startswith("to make "):
        is_named_variant = _looks_named_variant_recipe_name_prefix(text)
        is_generic_make_step = _looks_generic_to_make_step(text)
        has_variant_cue = _looks_explicit_variant_prose(text)
        has_neighboring_variant_heading = (
            by_atomic_index is not None
            and _has_neighboring_variant_heading(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
        if _is_within_recipe_span(candidate):
            if is_named_variant or has_neighboring_variant_heading or has_variant_cue:
                return "RECIPE_VARIANT", [
                    "howto_prefix_prose",
                    "recipe_local_variant_prose",
                ]
            reason_tags = ["howto_prefix_prose", "recipe_local_make_step"]
            if is_generic_make_step:
                reason_tags.append("generic_to_make_step")
            return "INSTRUCTION_LINE", reason_tags
        has_neighboring_component_structure = (
            by_atomic_index is not None
            and _outside_span_has_neighboring_component_structure(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        )
        if (
            is_named_variant
            or has_neighboring_variant_heading
            or (has_variant_cue and has_neighboring_component_structure)
        ):
            return "RECIPE_VARIANT", [
                "howto_prefix_prose",
                "outside_recipe_variant_prose",
            ]
        if (
            by_atomic_index is not None
            and _instruction_line_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            reason_tags = ["howto_prefix_prose", "outside_recipe_make_step"]
            if is_generic_make_step:
                reason_tags.append("generic_to_make_step")
            return "INSTRUCTION_LINE", reason_tags
        if _is_outside_recipe_span(candidate):
            return "OTHER", ["howto_prefix_prose", "outside_recipe_default_other"]
        return "OTHER", ["howto_prefix_prose", "default_other"]
    if lowered.startswith("to serve"):
        if _is_within_recipe_span(candidate):
            return "INSTRUCTION_LINE", ["howto_prefix_prose", "serving_step_prose"]
        if (
            by_atomic_index is not None
            and _instruction_line_label_allowed(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "INSTRUCTION_LINE", ["howto_prefix_prose", "outside_recipe_serving_step"]
        if _is_outside_recipe_span(candidate):
            return "OTHER", ["howto_prefix_prose", "outside_recipe_serving_prose"]
        return "OTHER", ["howto_prefix_prose", "default_other"]
    if _looks_storage_or_serving_note(text) or _looks_recipe_note_prose(text):
        return "RECIPE_NOTES", ["howto_prefix_prose", "note_like_prose"]
    if _is_outside_recipe_span(candidate):
        return "OTHER", ["howto_prefix_prose", "outside_recipe_default_other"]
    return "OTHER", ["howto_prefix_prose", "default_other"]


def _classify_variant_run_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> tuple[str | None, list[str]]:
    text = str(candidate.text or "").strip()
    if _variant_heading_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        if (
            _is_outside_recipe_span(candidate)
            and _outside_span_variant_should_be_recipe_title(
                candidate,
                by_atomic_index=by_atomic_index,
            )
        ):
            return "RECIPE_TITLE", ["title_like", "variant_heading_title_override"]
        tags = ["variant_heading"]
        if _normalized_variant_heading_text(text) in _VARIANT_GENERIC_HEADINGS:
            tags.append("variant_heading_supported")
        return "RECIPE_VARIANT", tags
    if by_atomic_index is not None and _is_within_variant_run(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_VARIANT", ["variant_run_continuation"]
    return None, []


def _howto_section_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_non_heading_howto_prose(text):
        return False
    if _HOWTO_PREFIX_RE.match(text):
        if not _looks_howto_heading_shape(text):
            return False
    elif not _looks_compact_heading(text):
        return False
    if _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    return _has_recipe_local_howto_support(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _has_recipe_local_howto_support(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    explicit_prefix = bool(_HOWTO_PREFIX_RE.match(text))
    if not explicit_prefix:
        if not _looks_recipe_title(text):
            return False
        if not _looks_compact_heading(text):
            return False
    elif not _looks_howto_heading_shape(text):
        return False
    prev_candidate = by_atomic_index.get(int(candidate.atomic_index) - 1)
    next_candidate = by_atomic_index.get(int(candidate.atomic_index) + 1)
    if prev_candidate is None and next_candidate is None:
        return False

    prev_component = _is_component_level_recipe_neighbor(prev_candidate)
    next_component = _is_component_level_recipe_neighbor(next_candidate)
    prev_flow = _looks_recipe_flow_neighbor(prev_candidate)
    next_flow = _looks_recipe_flow_neighbor(next_candidate)

    if explicit_prefix:
        return prev_component or next_component or (prev_flow and next_flow)
    return (
        (prev_component and next_component)
        or (_neighbor_is_ingredient_dominant(prev_candidate) and _looks_instructional_neighbor_or_boundary(next_candidate))
        or (_neighbor_is_ingredient_dominant(next_candidate) and _looks_instructional_neighbor_or_boundary(prev_candidate))
    )


def _is_component_level_recipe_neighbor(candidate: AtomicLineCandidate | None) -> bool:
    if candidate is None:
        return False
    return (
        _neighbor_is_ingredient_dominant(candidate)
        or _looks_instructional_neighbor(candidate)
        or _looks_recipe_start_boundary(candidate)
    )


def _looks_instructional_neighbor_or_boundary(
    candidate: AtomicLineCandidate | None,
) -> bool:
    if candidate is None:
        return False
    return _looks_instructional_neighbor(candidate) or _looks_recipe_start_boundary(
        candidate
    )


def _instruction_line_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    if _is_within_recipe_span(candidate):
        return True
    if not text:
        return False
    if _looks_storage_or_serving_note(text):
        return False
    if _looks_recipe_note_prose(text) and not _looks_direct_instruction_start(candidate):
        return False
    if not (
        _looks_direct_instruction_start(candidate)
        or _looks_instructional_neighbor(candidate)
    ):
        return False
    if _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
        radius=4,
    ):
        return True
    return _outside_span_has_title_led_recipe_cluster(
        candidate,
        by_atomic_index=by_atomic_index,
        radius=4,
    )


def _howto_section_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None:
        return howto_prose_label
    text = str(candidate.text or "").strip()
    if _looks_variant_heading_text(text):
        return "RECIPE_VARIANT"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return "OTHER"


def _instruction_line_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    text = str(candidate.text or "").strip()
    if _looks_recipe_note_prose(text) or _looks_storage_or_serving_note(text):
        return "RECIPE_NOTES"
    if _looks_knowledge_prose_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "KNOWLEDGE"
    if _looks_narrative_prose(text):
        return "OTHER"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    return "OTHER"


def _variant_fallback_label(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> str:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label is not None and howto_prose_label != "RECIPE_VARIANT":
        return howto_prose_label
    if _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "RECIPE_TITLE"
    if _looks_obvious_ingredient(candidate):
        return "INGREDIENT_LINE"
    if _instruction_line_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return "INSTRUCTION_LINE"
    if _looks_storage_or_serving_note(candidate.text) or _looks_recipe_note_prose(
        candidate.text
    ):
        return "RECIPE_NOTES"
    if _is_outside_recipe_span(candidate):
        return _outside_span_nonstructured_fallback_label(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    if _looks_direct_instruction_start(candidate) or _looks_instructional_neighbor(
        candidate
    ):
        return "INSTRUCTION_LINE"
    return "OTHER"

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
    if not _is_within_recipe_span(candidate):
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
    return False


def _should_rescue_neighbor_ingredient_fragment(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    if _is_outside_recipe_span(candidate):
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
    if _HOW_TO_TITLE_PREFIX_RE.match(stripped):
        return False
    if _NUMBERED_STEP_RE.match(stripped):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _TIME_PREFIX_RE.search(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    title_case_words = sum(1 for word in words if word[:1].isupper())
    lowercase_connector_words = sum(
        1
        for word in words
        if word.islower() and word.lower() in _TITLE_CONNECTOR_WORDS
    )
    heading_like = uppercase_words >= max(2, len(words) // 2) or title_case_words >= max(
        2, len(words) - 1
    )
    if not heading_like and title_case_words >= 2:
        heading_like = (title_case_words + lowercase_connector_words) == len(words)
    if not heading_like:
        return False
    if _INSTRUCTION_VERB_RE.match(stripped):
        alpha_chars = sum(1 for ch in stripped if ch.isalpha())
        uppercase_chars = sum(1 for ch in stripped if ch.isupper())
        uppercase_ratio = (uppercase_chars / alpha_chars) if alpha_chars else 0.0
        if len(words) < 4 and uppercase_ratio < 0.72:
            return False
    return True


def _looks_recipe_title_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if not _looks_recipe_title(candidate.text):
        return False
    if by_atomic_index is None:
        return _looks_compact_heading(candidate.text)
    saw_neighbor = False
    for offset in range(1, 4):
        next_candidate = by_atomic_index.get(candidate.atomic_index + offset)
        if next_candidate is None:
            break
        saw_neighbor = True
        if _is_outside_recipe_span(candidate):
            if _supports_outside_recipe_title_context(
                next_candidate,
                by_atomic_index=by_atomic_index,
            ):
                return True
        elif _supports_recipe_title_context(next_candidate):
            return True
        if _is_within_recipe_span(candidate) and _is_recipe_note_context_line(next_candidate):
            return True
        if _is_skippable_title_context_line(
            next_candidate,
            title_text=str(candidate.text or ""),
        ):
            continue
        next_tags = {str(tag) for tag in next_candidate.rule_tags}
        next_text = str(next_candidate.text or "")
        if _looks_narrative_prose(next_text):
            return False
        if "outside_recipe_span" in next_tags and _looks_prose(next_text):
            return False
        break
    if not saw_neighbor and _is_within_recipe_span(candidate):
        return True
    return False


def _looks_subsection_heading_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    return _howto_section_label_allowed(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _supports_recipe_title_context(candidate: AtomicLineCandidate) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    if _looks_recipe_start_boundary(candidate):
        return True
    if _neighbor_is_ingredient_dominant(candidate) and not _looks_table_of_contents_entry(
        str(candidate.text or "")
    ):
        return True
    if _looks_direct_instruction_start(candidate):
        return True
    return bool(
        {
            "yield_prefix",
            "howto_heading",
        }
        & tags
    )


def _supports_outside_recipe_title_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    tags = {str(tag) for tag in candidate.rule_tags}
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_recipe_start_boundary(candidate):
        return True
    if _looks_direct_instruction_start(candidate):
        return True
    if {"yield_prefix", "howto_heading"} & tags:
        return True
    if _looks_table_of_contents_entry(text) or _looks_navigation_title_list_entry(text):
        return False
    if _QUANTITY_LINE_RE.match(text):
        return True
    if _looks_quantity_unit_fragment(text):
        return True
    return _outside_span_has_neighboring_recipe_scaffold(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _is_skippable_title_context_line(
    candidate: AtomicLineCandidate,
    *,
    title_text: str,
) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return True
    lowered = text.lower()
    if lowered == str(title_text or "").strip().lower():
        return True
    if _looks_note_text(text):
        return True
    if _looks_editorial_note(text):
        return True
    return _looks_recipe_note_prose(text)


def _is_recipe_note_context_line(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    tags = {str(tag) for tag in candidate.rule_tags}
    if "note_like_prose" in tags:
        return True
    return (
        _looks_note_text(text)
        or _looks_editorial_note(text)
        or _looks_recipe_note_prose(text)
    )


def _looks_direct_instruction_start(candidate: AtomicLineCandidate) -> bool:
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _NUMBERED_STEP_RE.match(text):
        return True
    if _INSTRUCTION_VERB_RE.match(text):
        return True
    if re.match(r"^\s*taste\b", text, re.IGNORECASE):
        return True
    if re.match(r"^\s*to serve\b", text, re.IGNORECASE) and _RECIPE_ACTION_CUE_RE.search(
        text
    ):
        return True
    if (
        _INSTRUCTION_LEADIN_RE.match(text)
        and re.search(r"\blet\s+(?:the|them|it)\b", text, re.IGNORECASE)
    ):
        return True
    if re.match(r"^\s*let\s+(?:the|them|it)\b", text, re.IGNORECASE) and _RECIPE_ACTION_CUE_RE.search(
        text
    ):
        return True
    if _INSTRUCTION_LEADIN_RE.match(text) and _RECIPE_ACTION_CUE_RE.search(text):
        return True
    return False


def _looks_table_of_contents_entry(text: str) -> bool:
    stripped = str(text or "").strip()
    if not re.match(r"^\d+\s+", stripped):
        return False
    lowered = stripped.lower()
    if "science of" in lowered:
        return True
    words = _PROSE_WORD_RE.findall(stripped)
    uppercase_words = sum(1 for word in words if word.upper() == word)
    return len(words) >= 4 and uppercase_words >= 2


def _outside_span_variant_should_be_recipe_title(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if by_atomic_index is None:
        return False
    stripped = str(candidate.text or "").strip()
    lowered = stripped.lower()
    if not stripped:
        return False
    if lowered in _VARIANT_EXPLICIT_HEADINGS or lowered.startswith("with "):
        return False
    return _looks_recipe_title_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )


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


def _looks_howto_heading_shape(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _HOWTO_PREFIX_RE.match(stripped):
        return False
    if stripped[-1:] in {".", "!", "?"}:
        return False
    heading_text = stripped[:-1].rstrip() if stripped.endswith(":") else stripped
    if not heading_text:
        return False
    if any(mark in heading_text for mark in ",;()"):
        return False
    words = _PROSE_WORD_RE.findall(heading_text)
    if not (2 <= len(words) <= 8):
        return False
    if len(heading_text) > 72:
        return False
    return True


def _looks_non_heading_howto_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    return (
        bool(stripped)
        and _HOWTO_PREFIX_RE.match(stripped) is not None
        and not _looks_howto_heading_shape(stripped)
    )


def _looks_note_text(text: str) -> bool:
    return bool(_NOTE_PREFIX_RE.match(text))


def _normalized_variant_heading_text(text: str) -> str:
    return str(text or "").strip().rstrip(":").lower()


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
    lowered = _normalized_variant_heading_text(stripped)
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


def _looks_named_variant_recipe_name_prefix(text: str) -> bool:
    stripped = str(text or "").strip()
    match = re.match(r"^\s*To make\s+(.+)$", stripped, re.IGNORECASE)
    if match is None:
        return False
    remainder = match.group(1).strip()
    if not remainder:
        return False
    words = _PROSE_WORD_RE.findall(remainder)
    if len(words) < 2:
        return False
    lead_words = list(words[:6])
    while lead_words and lead_words[0].lower() in {"a", "an", "the"}:
        lead_words.pop(0)
    if len(lead_words) < 2:
        return False
    capitalized_word_count = 0
    consumed_any = False
    for word in lead_words:
        lowered = word.lower()
        if word[:1].isupper() or word.upper() == word:
            capitalized_word_count += 1
            consumed_any = True
            continue
        if consumed_any and lowered in _TITLE_CONNECTOR_WORDS:
            continue
        break
    return capitalized_word_count >= 2


def _looks_generic_to_make_step(text: str) -> bool:
    stripped = str(text or "").strip()
    if not (
        stripped.lower().startswith("to make ")
        and _looks_non_heading_howto_prose(stripped)
    ):
        return False
    if _looks_named_variant_recipe_name_prefix(stripped):
        return False
    remainder = stripped[8:].strip()
    words = _PROSE_WORD_RE.findall(remainder)
    if not words:
        return False
    first_word = words[0]
    if first_word.lower() in {"the", "this", "these", "those", "your"}:
        return True
    return first_word[:1].islower()


def _looks_explicit_variant_prose(text: str) -> bool:
    lowered = f" {str(text or '').strip().lower()} "
    return any(
        cue in lowered
        for cue in (
            " substitute ",
            " instead",
            " variation",
            " variations",
            " version",
            " omit ",
            " skip ",
            " swap ",
        )
    )


def _looks_variant_adjustment_leadin(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    if lowered.startswith("to add ") and "," in lowered:
        return True
    if lowered.startswith("to evoke ") and "," in lowered:
        return True
    if lowered.startswith("to make it ") and "," in lowered:
        return True
    return False


def _has_neighboring_variant_heading(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    radius: int = 2,
) -> bool:
    center = int(candidate.atomic_index)
    for offset in range(1, max(1, int(radius)) + 1):
        for neighbor_index in (center - offset, center + offset):
            neighbor = by_atomic_index.get(neighbor_index)
            if neighbor is None:
                continue
            if _looks_variant_heading_text(neighbor.text):
                return True
    return False


def _looks_variant_run_body_line(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if not text:
        return False
    if _looks_obvious_ingredient(candidate):
        return True
    if lowered.startswith("to make ") and _looks_non_heading_howto_prose(text):
        if _looks_named_variant_recipe_name_prefix(text):
            return True
        return _looks_explicit_variant_prose(text)
    if _looks_variant_adjustment_leadin(text):
        return True
    if _looks_direct_instruction_start(candidate) or _looks_instructional_neighbor(
        candidate
    ):
        return _looks_explicit_variant_prose(text) or _looks_variant_adjustment_leadin(
            text
        )
    if not _looks_prose(text):
        return False
    if (
        _looks_editorial_note(text)
        or _looks_narrative_prose(text)
        or _looks_book_framing_or_exhortation_prose(text)
        or _outside_recipe_knowledge_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return False
    if _looks_named_variant_recipe_name_prefix(text):
        return True
    if lowered.startswith("if you don't have "):
        return True
    if lowered.startswith("for ") and "," in text:
        return True
    return _looks_explicit_variant_prose(text)


def _variant_heading_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if not _looks_variant_heading_text(text):
        return False
    if _normalized_variant_heading_text(text) not in _VARIANT_GENERIC_HEADINGS:
        return True
    if by_atomic_index is None:
        return False
    center = int(candidate.atomic_index)
    for offset in range(1, 3):
        for neighbor_index in (center - offset, center + offset):
            neighbor = by_atomic_index.get(neighbor_index)
            if neighbor is None:
                continue
            howto_prose_label, _ = _classify_non_heading_howto_prose(
                neighbor,
                by_atomic_index=by_atomic_index,
            )
            if howto_prose_label == "RECIPE_VARIANT":
                return True
            if _looks_variant_run_body_line(
                neighbor,
                by_atomic_index=by_atomic_index,
            ):
                return True
    return False


def _looks_variant_run_anchor(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    text = str(candidate.text or "").strip()
    lowered = text.lower()
    if (
        _normalized_variant_heading_text(text) in _VARIANT_GENERIC_HEADINGS
        and _variant_heading_label_allowed(
            candidate,
            by_atomic_index=by_atomic_index,
        )
    ):
        return True
    if not (lowered.startswith("to make ") and _looks_non_heading_howto_prose(text)):
        return False
    if _is_within_recipe_span(candidate):
        return True
    if _looks_named_variant_recipe_name_prefix(text):
        return True
    return _outside_span_has_neighboring_component_structure(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _has_neighboring_variant_heading(
        candidate,
        by_atomic_index=by_atomic_index,
    )


def _is_within_variant_run(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
    max_distance: int = 6,
) -> bool:
    if _looks_variant_run_anchor(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    if not _looks_variant_run_body_line(
        candidate,
        by_atomic_index=by_atomic_index,
    ):
        return False
    center = int(candidate.atomic_index)
    for offset in range(1, max(1, int(max_distance)) + 1):
        previous = by_atomic_index.get(center - offset)
        if previous is None:
            break
        if _looks_variant_run_anchor(
            previous,
            by_atomic_index=by_atomic_index,
        ):
            return True
        if not _looks_variant_run_body_line(
            previous,
            by_atomic_index=by_atomic_index,
        ):
            break
    return False


def _variant_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate],
) -> bool:
    howto_prose_label, _ = _classify_non_heading_howto_prose(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    if howto_prose_label == "RECIPE_VARIANT":
        return True
    variant_context_label, _ = _classify_variant_run_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )
    return variant_context_label == "RECIPE_VARIANT"


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
    if _looks_storage_or_serving_note(stripped):
        return True
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if len(words) < 12:
        return False
    if not _RECIPE_CONTEXT_RE.search(stripped):
        return False
    if _FIRST_PERSON_RE.search(stripped):
        return bool(_RECIPE_NOTE_ADVISORY_CUE_RE.search(stripped))
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


def _looks_storage_or_serving_note(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    lowered = stripped.lower()
    if _STORAGE_NOTE_PREFIX_RE.match(stripped):
        return True
    if not _SERVING_NOTE_PREFIX_RE.match(stripped):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not words or len(words) > 40:
        return False
    if "ideal for everyday cooking" in lowered:
        return False
    if "ideal for use in food" in lowered:
        return False
    return any(
        cue in lowered
        for cue in (
            "salad",
            "slaw",
            "lettuce",
            "lettuces",
            "vegetable",
            "vegetables",
            "fish",
            "chicken",
            "bread",
            "dip",
            "dipping",
            "drizzling",
            "drizzle",
            "sauce",
            "steak",
            "cucumber",
            "cucumbers",
            "tomato",
            "tomatoes",
            "leftover",
            "leftovers",
        )
    )


def _looks_narrative_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    lowered = stripped.lower()
    if any(lowered.startswith(prefix) for prefix in _NON_RECIPE_PROSE_PREFIXES):
        return True
    if _FIRST_PERSON_SINGULAR_RE.search(stripped):
        return not (
            _looks_explicit_knowledge_cue(stripped)
            or _looks_domain_knowledge_prose(stripped)
            or _looks_pedagogical_knowledge_prose(stripped)
        )
    if _FIRST_PERSON_RE.search(stripped) and not (
        _looks_explicit_knowledge_cue(stripped)
        or _looks_domain_knowledge_prose(stripped)
        or _looks_pedagogical_knowledge_prose(stripped)
    ):
        return True
    return False


def _looks_book_framing_or_exhortation_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    lowered = stripped.lower()
    second_person_count = len(_SECOND_PERSON_RE.findall(stripped))
    if "this book" in lowered and _FIRST_PERSON_RE.search(stripped):
        return True
    if _BOOK_FRAMING_EXHORTATION_CUE_RE.search(stripped):
        return True
    if (
        second_person_count >= 2
        and any(
            cue in lowered
            for cue in (
                "better",
                "learn",
                "teach",
                "for you",
                "pay attention",
            )
        )
        and not _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
    ):
        return True
    if (
        (_INSTRUCTION_VERB_RE.match(stripped) or lowered.startswith("let "))
        and second_person_count >= 1
        and not _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
    ):
        return True
    return False


def _knowledge_domain_cue_count(text: str) -> int:
    return len(
        {match.group(0).lower() for match in _KNOWLEDGE_DOMAIN_CUE_RE.finditer(text)}
    )


def _looks_domain_knowledge_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    domain_cues = _knowledge_domain_cue_count(stripped)
    if domain_cues <= 0:
        return False
    lowered = stripped.lower()
    if _looks_prose(stripped) and _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped):
        return True
    if _looks_prose(stripped) and not _INSTRUCTION_VERB_RE.match(stripped):
        if any(
            cue in lowered
            for cue in (
                " is to ",
                " can be ",
                " corrected ",
                " correct ",
                " rebalance ",
                " well suited ",
                " preferred ",
                " keeps ",
                " protects ",
                " doesn't offer ",
                " does not offer ",
                " tastes bitter",
            )
        ):
            return True
    words = _PROSE_WORD_RE.findall(stripped)
    if (
        3 <= len(words) <= 10
        and _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
        and not _INSTRUCTION_VERB_RE.match(stripped)
        and not _QUANTITY_LINE_RE.match(stripped)
    ):
        return True
    if not _looks_prose(stripped):
        return False
    if _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped):
        return True
    return False


def _looks_knowledge_heading_shape(text: str) -> bool:
    stripped = str(text or "").strip()
    words = _PROSE_WORD_RE.findall(stripped)
    if not (1 <= len(words) <= 6):
        return False
    if _QUANTITY_LINE_RE.match(stripped):
        return False
    if _NOTE_PREFIX_RE.match(stripped):
        return False
    if _YIELD_PREFIX_RE.match(stripped):
        return False
    if stripped[-1:] in {".", "!"}:
        return False
    uppercase_words = sum(1 for word in words if word.upper() == word)
    title_case_words = sum(1 for word in words if word[:1].isupper())
    lowercase_connector_words = sum(
        1
        for word in words
        if word.islower() and word.lower() in _TITLE_CONNECTOR_WORDS
    )
    return uppercase_words == len(words) or (
        title_case_words + lowercase_connector_words
    ) == len(words)


def _looks_obvious_knowledge_heading(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_knowledge_heading_shape(stripped):
        return False
    lowered = stripped.rstrip("?").lower()
    if _PEDAGOGICAL_KNOWLEDGE_HEADING_RE.match(lowered):
        return True
    if _KNOWLEDGE_HEADING_FORM_RE.match(lowered):
        return True
    return False


def _looks_knowledge_heading_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if _is_within_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if _looks_obvious_knowledge_heading(text):
        return True
    if by_atomic_index is None:
        return False
    if not _looks_knowledge_heading_shape(text):
        return False
    for offset in (-1, 1):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "")
        if _looks_domain_knowledge_prose(neighbor_text) or _looks_explicit_knowledge_cue(
            neighbor_text
        ):
            return True
    return False


def _looks_endorsement_credit(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if not stripped.startswith("-"):
        return False
    words = _PROSE_WORD_RE.findall(stripped)
    if not (5 <= len(words) <= 18):
        return False
    lowered = stripped.lower()
    return any(
        cue in lowered
        for cue in (
            "author of",
            "bestselling author",
            "chef",
            "co-founder",
            "cofounder",
            "editor",
            "founder",
            "steward of",
            "stewards of",
        )
    )


def _looks_pedagogical_knowledge_prose(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or not _looks_prose(stripped):
        return False
    if _looks_editorial_note(stripped) or _looks_recipe_note_prose(stripped):
        return False
    if _looks_book_framing_or_exhortation_prose(stripped):
        return False
    lowered = stripped.lower()
    if not any(
        cue in lowered
        for cue in ("book", "cook", "cooking", "kitchen", "meal", "recipe")
    ):
        return False
    if not _PEDAGOGICAL_KNOWLEDGE_CUE_RE.search(stripped):
        return False
    return bool(
        _KNOWLEDGE_EXPLANATION_CUE_RE.search(stripped)
        or _EXPLICIT_KNOWLEDGE_CUE_RE.search(stripped)
    )


def _looks_knowledge_prose_with_context(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    text = str(candidate.text or "").strip()
    if (
        _looks_narrative_prose(text)
        or _looks_endorsement_credit(text)
        or _looks_book_framing_or_exhortation_prose(text)
    ):
        return False
    if (
        _looks_explicit_knowledge_cue(text)
        or _looks_domain_knowledge_prose(text)
        or _looks_pedagogical_knowledge_prose(text)
    ):
        return True
    if by_atomic_index is None:
        return False
    words = _PROSE_WORD_RE.findall(text)
    if _looks_prose(text) and len(words) > 18 and not _looks_knowledge_heading_shape(text):
        return False
    for offset in (-1, 1):
        neighbor = by_atomic_index.get(int(candidate.atomic_index) + offset)
        if neighbor is None or _is_within_recipe_span(neighbor):
            continue
        neighbor_text = str(neighbor.text or "")
        if _looks_explicit_knowledge_cue(neighbor_text) or _looks_domain_knowledge_prose(
            neighbor_text
        ):
            return True
        if _looks_knowledge_heading_with_context(
            neighbor,
            by_atomic_index=by_atomic_index,
        ):
            return True
    return False


def _outside_recipe_knowledge_label_allowed(
    candidate: AtomicLineCandidate,
    *,
    by_atomic_index: dict[int, AtomicLineCandidate] | None,
) -> bool:
    if _is_within_recipe_span(candidate):
        return False
    text = str(candidate.text or "").strip()
    if not text:
        return False
    if (
        _looks_recipe_note_prose(text)
        or _looks_editorial_note(text)
        or _looks_endorsement_credit(text)
        or _looks_narrative_prose(text)
        or _looks_book_framing_or_exhortation_prose(text)
    ):
        return False
    return _looks_knowledge_heading_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    ) or _looks_knowledge_prose_with_context(
        candidate,
        by_atomic_index=by_atomic_index,
    )


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
        return "OTHER" if _is_outside_recipe_span(candidate) else "INSTRUCTION_LINE"
    if _looks_recipe_note_prose(text) or _looks_editorial_note(text):
        return "RECIPE_NOTES"
    return "OTHER"


def _looks_explicit_knowledge_cue(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    return bool(_EXPLICIT_KNOWLEDGE_CUE_RE.search(stripped))
