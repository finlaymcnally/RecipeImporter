from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.core.progress_messages import parse_stage_progress
from cookimport.llm.canonical_line_role_prompt import (
    build_canonical_line_role_file_prompt,
    build_canonical_line_role_prompt,
    serialize_line_role_targets,
)
from cookimport.llm.codex_exec_runner import CodexExecLiveSnapshot, FakeCodexExecRunner
from cookimport.llm.codex_exec_runner import CodexExecRunResult
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1
from cookimport.parsing import canonical_line_roles as canonical_line_roles_module
from cookimport.parsing.canonical_line_roles import _preflight_line_role_shard, label_atomic_lines
from cookimport.parsing.recipe_block_atomizer import (
    AtomicLineCandidate,
    atomize_blocks,
    build_atomic_index_lookup,
)
from tests.paths import FIXTURES_DIR


def _load_fixture(name: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "canonical_labeling" / name
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def _settings(mode: str = "off", **kwargs):
    return RunSettings(line_role_pipeline=mode, **kwargs)


@pytest.fixture(autouse=True)
def _isolate_default_line_role_runtime_root(tmp_path, monkeypatch) -> None:
    original = canonical_line_roles_module._resolve_line_role_codex_farm_workspace_root

    def _patched(*, settings):
        resolved = original(settings=settings)
        if resolved is not None:
            return resolved
        return tmp_path / "line-role-runtime-workspace"

    monkeypatch.setattr(
        canonical_line_roles_module,
        "_resolve_line_role_codex_farm_workspace_root",
        _patched,
    )


def _progress_messages_as_text(messages: list[str]) -> list[str]:
    rows: list[str] = []
    for message in messages:
        payload = parse_stage_progress(message)
        if payload is not None:
            rows.append(str(payload.get("message") or "").strip())
        else:
            rows.append(str(message).strip())
    return rows


def _line_role_runner(
    label_by_atomic_index: dict[int, str] | None = None,
    *,
    output_builder=None,
):
    def _default_builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        atomic_indices: list[int] = []
        for row in rows:
            value = None
            if isinstance(row, dict):
                value = row.get("atomic_index")
            elif isinstance(row, list | tuple) and row:
                value = row[0]
            if value is not None:
                atomic_indices.append(int(value))
        if not atomic_indices:
            prompt_text = payload if isinstance(payload, str) else json.dumps(payload, sort_keys=True)
            atomic_indices = [
                int(value)
                for value in re.findall(r'"atomic_index"\s*:\s*(\d+)', prompt_text)
            ]
        if not atomic_indices:
            atomic_indices = [
                int(value) for value in re.findall(r"(?m)^(\d+)\|", prompt_text)
            ]
        return {
            "rows": [
                {
                    "atomic_index": atomic_index,
                    "label": (label_by_atomic_index or {}).get(atomic_index, "OTHER"),
                }
                for atomic_index in atomic_indices
            ]
        }

    return FakeCodexExecRunner(
        output_builder=output_builder or _default_builder
    )


class _NoFinalWorkspaceMessageRunner(FakeCodexExecRunner):
    def run_workspace_worker(self, **kwargs) -> CodexExecRunResult:  # noqa: ANN003
        result = super().run_workspace_worker(**kwargs)
        return CodexExecRunResult(
            command=list(result.command),
            subprocess_exit_code=result.subprocess_exit_code,
            output_schema_path=result.output_schema_path,
            prompt_text=result.prompt_text,
            response_text=None,
            turn_failed_message=result.turn_failed_message,
            events=tuple(
                event
                for event in result.events
                if event.get("item", {}).get("type") != "agent_message"
            ),
            usage=dict(result.usage or {}),
            stderr_text=result.stderr_text,
            stdout_text=result.stdout_text,
            source_working_dir=result.source_working_dir,
            execution_working_dir=result.execution_working_dir,
            execution_agents_path=result.execution_agents_path,
            duration_ms=result.duration_ms,
            started_at_utc=result.started_at_utc,
            finished_at_utc=result.finished_at_utc,
            workspace_mode=result.workspace_mode,
            supervision_state=result.supervision_state,
            supervision_reason_code=result.supervision_reason_code,
            supervision_reason_detail=result.supervision_reason_detail,
            supervision_retryable=result.supervision_retryable,
        )


def test_label_atomic_lines_hollandaise_note_and_howto_rules() -> None:
    payload = _load_fixture("hollandaise_merged_block.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
        atomic_block_splitter="atomic-v1",
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["NOTE: Keep blender cup warm."].label == "RECIPE_NOTES"
    assert (
        by_text["TO MAKE HOLLANDAISE WITH AN IMMERSION BLENDER"].label
        == "HOWTO_SECTION"
    )
    assert by_text["NOTE: Keep blender cup warm."].decided_by == "rule"
    assert all(prediction.within_recipe_span is True for prediction in predictions)


def test_label_atomic_lines_ingredient_range_never_yield() -> None:
    payload = _load_fixture("ingredient_vs_yield_ranges.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
        atomic_block_splitter="atomic-v1",
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SERVES 4"].label == "YIELD_LINE"
    assert by_text["4 to 6 chicken leg quarters"].label == "INGREDIENT_LINE"
    assert by_text["2 tablespoons olive oil"].label == "INGREDIENT_LINE"


def test_label_atomic_lines_omelet_variant_and_ingredient_rules() -> None:
    payload = _load_fixture("omelet_variant_lines.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
        atomic_block_splitter="atomic-v1",
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert (
        by_text["DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET"].label
        == "RECIPE_VARIANT"
    )
    assert by_text["3 tablespoons whole milk"].label == "INGREDIENT_LINE"


def test_label_atomic_lines_instruction_with_time_stays_instruction() -> None:
    payload = _load_fixture("braised_chicken_tail_steps.json")
    blocks = payload.get("blocks")
    assert isinstance(blocks, list)
    candidates = atomize_blocks(
        blocks,
        recipe_id=str(payload.get("recipe_id") or ""),
        within_recipe_span=True,
        atomic_block_splitter="atomic-v1",
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["3. Cover and braise for 45 minutes."].label == "INSTRUCTION_LINE"


def test_codex_time_line_prediction_demotes_to_instruction_when_not_primary_time(
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:time:1",
            block_index=1,
            atomic_index=0,
            text="Add onions and cook for 5 minutes.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "TIME_LINE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "INSTRUCTION_LINE"
    assert predictions[0].decided_by == "fallback"
    assert "sanitized_time_to_instruction" in predictions[0].reason_tags


def test_label_atomic_lines_requires_explicit_live_llm_approval_for_shard_runtime() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ambiguous:1",
            block_index=1,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    blocked_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "OTHER"}),
    )
    assert blocked_predictions[0].decided_by == "fallback"

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "OTHER"}),
        live_llm_allowed=True,
    )
    assert predictions[0].decided_by == "codex"


def test_label_atomic_lines_outside_recipe_can_be_knowledge() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:1",
            "block_index": 1,
            "text": (
                "Copper pans conduct heat quickly and evenly, so even small burner "
                "changes show up immediately across the pan."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "KNOWLEDGE"
    assert predictions[0].within_recipe_span is False


def test_label_atomic_lines_outside_recipe_science_prose_is_knowledge() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:science",
            "block_index": 1,
            "text": (
                "The primary role that salt plays in cooking is to amplify flavor. "
                "Though salt also affects texture, nearly every decision you make "
                "about salt will involve enhancing and deepening flavor."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "KNOWLEDGE"


def test_label_atomic_lines_outside_recipe_knowledge_heading_uses_neighbor_context() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:prev",
            "block_index": 1,
            "text": (
                "Salt affects texture and flavor because it changes how food "
                "absorbs moisture during cooking."
            ),
        },
        {
            "block_id": "block:knowledge:heading",
            "block_index": 2,
            "text": "SALT AND FLAVOR",
        },
        {
            "block_id": "block:knowledge:next",
            "block_index": 3,
            "text": (
                "The relationship between salt and flavor is multidimensional, "
                "and even small changes can improve aroma and balance bitterness."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SALT AND FLAVOR"].label == "KNOWLEDGE"


def test_label_atomic_lines_outside_recipe_first_person_learning_prose_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:first-person",
            "block_index": 1,
            "text": (
                "As I improved, I began to detect the nuances that distinguish good "
                "food from great, understanding when pasta water needed more salt "
                "and when vinegar was needed to balance a rich stew."
            ),
        },
        {
            "block_id": "block:knowledge:neighbor",
            "block_index": 2,
            "text": (
                "Salt, fat, acid, and heat guided those decisions because each one "
                "changed flavor, texture, and temperature in predictable ways."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert (
        by_text[
            "As I improved, I began to detect the nuances that distinguish good "
            "food from great, understanding when pasta water needed more salt "
            "and when vinegar was needed to balance a rich stew."
        ].label
        == "KNOWLEDGE"
    )


def test_label_atomic_lines_outside_recipe_note_prefix_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:1",
            "block_index": 1,
            "text": "NOTE: Keep the soup warm while you prep garnish.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_outside_recipe_variant_heading_can_stay_structured() -> None:
    blocks = [
        {
            "block_id": "block:variant:1",
            "block_index": 1,
            "text": "FOR A CROWD",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_VARIANT"


def test_label_atomic_lines_outside_recipe_structured_cluster_can_stay_structured() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:1",
            "block_index": 1,
            "text": "1 tablespoon kosher salt",
        },
        {
            "block_id": "block:instruction:2",
            "block_index": 2,
            "text": "Stir to combine.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label == "INGREDIENT_LINE"
    assert predictions[1].label == "INSTRUCTION_LINE"


def test_label_atomic_lines_unknown_pre_grouping_cluster_stays_structured() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:unknown:1",
            "block_index": 41,
            "text": "2 tablespoons olive oil",
        },
        {
            "block_id": "block:instruction:unknown:1",
            "block_index": 42,
            "text": "Whisk until smooth.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].within_recipe_span is None
    assert predictions[1].within_recipe_span is None
    assert predictions[0].label == "INGREDIENT_LINE"
    assert predictions[1].label == "INSTRUCTION_LINE"


def test_label_atomic_lines_unknown_pre_grouping_science_prose_is_knowledge() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:science:unknown",
            "block_index": 1,
            "text": (
                "The primary role that salt plays in cooking is to amplify flavor. "
                "Though salt also affects texture, nearly every decision you make "
                "about salt will involve enhancing and deepening flavor."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].within_recipe_span is None
    assert predictions[0].label == "KNOWLEDGE"


def test_label_atomic_lines_unknown_pre_grouping_knowledge_heading_uses_neighbor_context() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:prev:unknown",
            "block_index": 1,
            "text": (
                "Salt affects texture and flavor because it changes how food "
                "absorbs moisture during cooking."
            ),
        },
        {
            "block_id": "block:knowledge:heading:unknown",
            "block_index": 2,
            "text": "SALT AND FLAVOR",
        },
        {
            "block_id": "block:knowledge:next:unknown",
            "block_index": 3,
            "text": (
                "The relationship between salt and flavor is multidimensional, "
                "and even small changes can improve aroma and balance bitterness."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["SALT AND FLAVOR"].label == "KNOWLEDGE"
    assert by_text["Salt affects texture and flavor because it changes how food absorbs moisture during cooking."].label == "KNOWLEDGE"
    assert by_text["The relationship between salt and flavor is multidimensional, and even small changes can improve aroma and balance bitterness."].label == "KNOWLEDGE"


def test_label_atomic_lines_outside_recipe_howto_heading_can_stay_structured() -> None:
    blocks = [
        {
            "block_id": "block:howto:outside:1",
            "block_index": 1,
            "text": "FOR THE SAUCE",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "HOWTO_SECTION"


def test_label_atomic_lines_outside_recipe_first_person_prose_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:preface:1",
            "block_index": 1,
            "text": (
                "I spent years testing this in my home kitchen, but this paragraph "
                "is narrative preface prose and not an inline recipe note."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_prose_defaults_to_other_without_knowledge_cue() -> None:
    blocks = [
        {
            "block_id": "block:narrative:1",
            "block_index": 1,
            "text": (
                "The chapter opens with a short story about market mornings, and "
                "the prose lingers on scene-setting details before any recipe starts."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_food_note_prose_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:tip:1",
            "block_index": 1,
            "text": (
                "I like mine extra peppery, and you can spoon it over biscuits "
                "while the gravy is still hot."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_storage_note_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:storage:1",
            "block_index": 1,
            "text": "Store leftover slaw covered, in the fridge, for up to two days.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_refrigerate_leftovers_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:storage:2",
            "block_index": 1,
            "text": "Refrigerate leftovers, covered, for up to 3 days.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_ideal_for_serving_suggestion_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:serving:1",
            "block_index": 1,
            "text": (
                "Ideal for garden lettuces, arugula, chicories, Belgian endive, "
                "Little Gem and romaine lettuce, beets, tomatoes, blanched, "
                "grilled, or roasted vegetables of any kind."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_unknown_pre_grouping_serve_with_suggestion_is_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note:serving:2",
            "block_index": 1,
            "text": "Serve with grilled fish, roast chicken, or ripe tomatoes.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"


def test_label_atomic_lines_science_prose_with_internal_ideal_for_is_not_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:knowledge:ideal-for:1",
            "block_index": 1,
            "text": (
                "Fine or medium-size crystals of this type are ideal for everyday "
                "cooking. Use this type of sea salt to season foods from within."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=None,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label != "RECIPE_NOTES"


def test_label_atomic_lines_outside_recipe_contents_heading_is_not_recipe_variant() -> None:
    blocks = [
        {
            "block_id": "block:heading:1",
            "block_index": 1,
            "text": "CONTENTS",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label != "RECIPE_VARIANT"


def test_label_atomic_lines_heading_like_line_without_neighboring_evidence_is_not_title() -> None:
    blocks = [
        {
            "block_id": "block:title:1",
            "block_index": 1,
            "text": "POACHED EGGS",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label in {"OTHER", "KNOWLEDGE"}


def test_label_atomic_lines_heading_like_line_with_neighboring_structure_can_be_title() -> None:
    blocks = [
        {
            "block_id": "block:title:with-context:1",
            "block_index": 1,
            "text": "POACHED EGGS",
        },
        {
            "block_id": "block:title:with-context:2",
            "block_index": 2,
            "text": "2 large eggs",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_long_mixed_case_title_with_yield_is_title() -> None:
    blocks = [
        {
            "block_id": "block:title:long:1",
            "block_index": 1,
            "text": "Pan-Roasted Filets Mignons with Asparagus and Garlic-Herb Butter",
        },
        {
            "block_id": "block:title:long:2",
            "block_index": 2,
            "text": "serves 2",
        },
        {
            "block_id": "block:title:long:3",
            "block_index": 3,
            "text": "total time: 45 minutes",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_all_caps_verb_heading_can_be_title() -> None:
    blocks = [
        {
            "block_id": "block:title:verb:1",
            "block_index": 1,
            "text": "ROAST GROUSE WITH BREAD SAUCE AND GAME CRUMBS",
        },
        {
            "block_id": "block:title:verb:2",
            "block_index": 2,
            "text": "NOTE: Keep the birds cool before cooking.",
        },
        {
            "block_id": "block:title:verb:3",
            "block_index": 3,
            "text": "serves 4",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_title_can_look_past_note_line() -> None:
    blocks = [
        {
            "block_id": "block:title:note:1",
            "block_index": 1,
            "text": "FOOLPROOF SOFT-BOILED EGGS",
        },
        {
            "block_id": "block:title:note:2",
            "block_index": 2,
            "text": "NOTE: Practice once if needed.",
        },
        {
            "block_id": "block:title:note:3",
            "block_index": 3,
            "text": "1 quart water",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_outside_recipe_toc_heading_is_not_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:toc:1",
            "block_index": 1,
            "text": "THE BASIC PANTRY",
        },
        {
            "block_id": "block:title:toc:2",
            "block_index": 2,
            "text": "1 EGGS, DAIRY, and the Science of Breakfast",
        },
        {
            "block_id": "block:title:toc:3",
            "block_index": 3,
            "text": "2 SOUPS, STEWS, and the Science of Stock",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "OTHER"


def test_label_atomic_lines_outside_recipe_how_to_heading_is_not_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:howto:1",
            "block_index": 1,
            "text": "How to Cut a Bell Pepper",
        },
        {
            "block_id": "block:title:howto:2",
            "block_index": 2,
            "text": "There are two camps when it comes to cutting peppers.",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label != "RECIPE_TITLE"


def test_codex_neighbor_ingredient_fragment_rescued_to_ingredient() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:0",
            block_index=0,
            atomic_index=0,
            text="1 cup",
            within_recipe_span=True,
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:1",
            block_index=1,
            atomic_index=1,
            text="flour",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:ingredient:2",
            block_index=2,
            atomic_index=2,
            text="2 tablespoons sugar",
            within_recipe_span=True,
            rule_tags=["ingredient_like"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({1: "OTHER"}),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "INGREDIENT_LINE"
    assert by_index[1].decided_by == "fallback"
    assert "sanitized_neighbor_ingredient_fragment" in by_index[1].reason_tags


def test_label_atomic_lines_component_heading_prefers_howto_section() -> None:
    blocks = [
        {
            "block_id": "block:ingredient:1",
            "block_index": 1,
            "text": "4 Hakurei turnip leaves, about 8 to 10 inches long",
        },
        {
            "block_id": "block:heading:1",
            "block_index": 2,
            "text": "AGING THE DUCK",
        },
        {
            "block_id": "block:instruction:1",
            "block_index": 3,
            "text": (
                "Trim any excess fat from around the neck and abdominal cavity of "
                "the duck."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    by_text = {prediction.text: prediction for prediction in predictions}
    assert by_text["AGING THE DUCK"].label == "HOWTO_SECTION"
    assert by_text["AGING THE DUCK"].decided_by == "rule"


def test_label_atomic_lines_recipe_title_with_immediate_yield_stays_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:yield:1",
            "block_index": 1,
            "text": "CHICKEN DRIPPINGS",
        },
        {
            "block_id": "block:title:yield:2",
            "block_index": 2,
            "text": "YIELDS ABOUT 2 CUPS/400 G",
        },
        {
            "block_id": "block:title:yield:3",
            "block_index": 3,
            "text": "4 whole chickens",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].text == "CHICKEN DRIPPINGS"
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_recipe_title_with_immediate_note_prose_stays_recipe_title() -> None:
    blocks = [
        {
            "block_id": "block:title:note-prose:1",
            "block_index": 1,
            "text": "LEEKS VINAIGRETTE",
        },
        {
            "block_id": "block:title:note-prose:2",
            "block_index": 2,
            "text": (
                "I like this best when the leeks are barely warm and the dressing "
                "has had a minute to soak in."
            ),
        },
        {
            "block_id": "block:title:note-prose:3",
            "block_index": 3,
            "text": "2 large leeks",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert predictions[0].label == "RECIPE_TITLE"


def test_label_atomic_lines_non_header_yield_phrase_demotes_to_instruction() -> None:
    blocks = [
        {
            "block_id": "block:yield:1",
            "block_index": 1,
            "text": "SERVES with crusty bread and lemon wedges.",
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "INSTRUCTION_LINE"
    assert "sanitized_yield_to_instruction" in predictions[0].reason_tags


def test_label_atomic_lines_title_like_line_without_supportive_next_line_is_not_title() -> None:
    blocks = [
        {
            "block_id": "block:title:outside:1",
            "block_index": 1,
            "text": "PAN-SEARED SALMON",
        },
        {
            "block_id": "block:title:outside:2",
            "block_index": 2,
            "text": (
                "I learned this on a rainy night, and this paragraph is narrative "
                "context rather than an ingredient list or recipe boundary line."
            ),
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id=None,
        within_recipe_span=False,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 2
    assert predictions[0].label == "OTHER"


def test_title_like_line_can_be_overridden_when_full_book_codex_reviews_it(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:1",
            block_index=1,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "OTHER"}),
        live_llm_allowed=True,
    )
    assert (
        tmp_path
        / "line-role-pipeline"
        / "prompts"
        / "line_role"
        / "line_role_prompt_0001.txt"
    ).exists()
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"


def test_codex_mode_accepts_global_label_not_present_in_old_shortlist() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:title:global",
            block_index=1,
            atomic_index=0,
            text="Shaved Carrot Salad with Ginger and Lime",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_TITLE"
    assert predictions[0].decided_by == "codex"


def test_codex_mode_allows_override_of_strong_recipe_note() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:note:0",
            block_index=0,
            atomic_index=0,
            text="NOTE: Keep blender cup warm.",
            within_recipe_span=True,
            rule_tags=["note_prefix"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "OTHER"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == ["codex_disagreed_with_rule"]


def test_codex_mode_allows_override_without_old_syntax_ownership_veto() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:instruction:0",
            block_index=0,
            atomic_index=0,
            text="Stir well and taste for seasoning.",
            within_recipe_span=True,
            rule_tags=["instruction_like"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "RECIPE_NOTES"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == ["codex_disagreed_with_rule"]


def test_codex_mode_allows_outside_span_title_override() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:2",
            block_index=2,
            atomic_index=0,
            text="A PORRIDGE OF LOVAGE STEMS",
            within_recipe_span=False,
            rule_tags=["outside_recipe_span"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:title:3",
            block_index=3,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=False,
            rule_tags=["ingredient_like", "outside_recipe_span"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner(
            {0: "OTHER", 1: "INGREDIENT_LINE"},
        ),
        live_llm_allowed=True,
    )
    assert len(predictions) == 2
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == ["codex_disagreed_with_rule"]


def test_label_atomic_lines_note_like_prose_prefers_recipe_notes() -> None:
    blocks = [
        {
            "block_id": "block:note-prose:1",
            "block_index": 1,
            "text": (
                "If you like a thinner finish, you can whisk in a splash of stock "
                "right before serving to loosen the texture."
            ),
        }
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:0",
        within_recipe_span=True,
    )
    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "RECIPE_NOTES"
    assert predictions[0].decided_by == "rule"


def test_label_atomic_lines_recovers_outside_recipe_knowledge_headings_and_fragments() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:1",
            block_index=1,
            atomic_index=0,
            text="How Salt Works",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:2",
            block_index=2,
            atomic_index=1,
            text="FAT",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:3",
            block_index=3,
            atomic_index=2,
            text="acid, which brightens and balances",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:4",
            block_index=4,
            atomic_index=3,
            text="and heat, which ultimately determines the texture of food",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert [prediction.label for prediction in predictions] == [
        "KNOWLEDGE",
        "KNOWLEDGE",
        "KNOWLEDGE",
        "KNOWLEDGE",
    ]


def test_label_atomic_lines_recovers_outside_recipe_pedagogical_and_endorsement_prose() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:5",
            block_index=5,
            atomic_index=0,
            text=(
                "Whether you've never picked up a knife and fork or you cook every "
                "day, mastering these four elements will make every meal better."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:knowledge:6",
            block_index=6,
            atomic_index=1,
            text="-Alice Waters , New York Times bestselling author of The Art of Simple Food",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert [prediction.label for prediction in predictions] == [
        "KNOWLEDGE",
        "KNOWLEDGE",
    ]


def test_label_atomic_lines_outside_recipe_generic_heading_stays_other() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:outside-title:1",
            block_index=1,
            atomic_index=0,
            text="A Panzanella for Every Season",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(candidates, _settings())
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"


def test_codex_outside_recipe_generic_lesson_heading_demotes_howto_to_knowledge(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:lesson:1",
            block_index=1,
            atomic_index=0,
            text="Gentle Cooking Methods",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:lesson:2",
            block_index=2,
            atomic_index=1,
            text=(
                "Gentle cooking methods control heat transfer so food cooks through "
                "without toughening or drying out."
            ),
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION", 1: "KNOWLEDGE"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"
    assert "outside_span_structured_label" in predictions[0].escalation_reasons
    assert "codex_disagreed_with_rule" in predictions[0].escalation_reasons


def test_codex_outside_recipe_narrative_prose_demotes_howto_to_other(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:memoir:1",
            block_index=1,
            atomic_index=0,
            text=(
                "Then I fell in love with Johnny, who introduced me to the culinary "
                "delights of his native San Francisco."
            ),
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"
    assert "outside_span_structured_label" in predictions[0].escalation_reasons
    assert "codex_disagreed_with_rule" in predictions[0].escalation_reasons


def test_codex_outside_recipe_explicit_howto_heading_can_stay_structured(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:howto:outside:1",
            block_index=1,
            atomic_index=0,
            text="FOR THE SAUCE",
            within_recipe_span=False,
            rule_tags=[],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "HOWTO_SECTION"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "HOWTO_SECTION"
    assert predictions[0].decided_by == "codex"


def test_label_atomic_lines_codex_parse_error_falls_back_and_writes_flag(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text=(
                "This paragraph explains why pan temperature matters for crust "
                "development and how airflow changes moisture retention."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            output_builder=lambda _payload: {"rows": [{"atomic_index": 999, "label": "OTHER"}]}
        ),
        live_llm_allowed=True,
    )
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "fallback"
    assert "deterministic_unavailable" in predictions[0].reason_tags
    assert "task_packet_fallback" in predictions[0].reason_tags
    parse_errors_path = (
        tmp_path
        / "line-role-pipeline"
        / "prompts"
        / "line_role"
        / "parse_errors.json"
    )
    payload = json.loads(parse_errors_path.read_text(encoding="utf-8"))
    assert payload["parse_error_count"] == 0
    assert payload["parse_error_present"] is False
    assert not (tmp_path / "line-role-pipeline" / "guardrail_report.json").exists()
    assert not (tmp_path / "line-role-pipeline" / "do_no_harm_diagnostics.json").exists()
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == []
    assert (
        proposal_payload["validation_metadata"]["task_aggregation"]["fallback_task_count"]
        == 1
    )
    task_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "task_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert task_status_rows[0]["state"] == "repair_failed"


def test_canonical_line_role_prompt_includes_required_contract_text() -> None:
    candidate = AtomicLineCandidate(
        recipe_id="r1",
        block_id="block:1",
        block_index=1,
        atomic_index=0,
        text="SERVES 4",
        within_recipe_span=True,
        rule_tags=["yield_prefix"],
    )
    by_atomic_index = build_atomic_index_lookup(
        [
            candidate,
            AtomicLineCandidate(
                recipe_id="r1",
                block_id="block:2",
                block_index=2,
                atomic_index=1,
                text="2 tablespoons olive oil",
                within_recipe_span=True,
                rule_tags=["ingredient_like"],
            ),
        ]
    )
    prompt = build_canonical_line_role_prompt(
        [candidate],
        allowed_labels=["OTHER", "YIELD_LINE", "INGREDIENT_LINE"],
        escalation_reasons_by_atomic_index={0: ["deterministic_unresolved"]},
        by_atomic_index=by_atomic_index,
    )
    assert "RECIPE_TITLE > RECIPE_VARIANT > YIELD_LINE > HOWTO_SECTION >" in prompt
    assert "Never label a quantity/unit ingredient line as `KNOWLEDGE`." in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "`INSTRUCTION_LINE` means a recipe-local procedural step" in prompt
    assert "`HOWTO_SECTION` is recipe-internal only." in prompt
    assert "Cooking Acids" in prompt
    assert "Use limes in guacamole" in prompt
    assert "Label codes: L0=OTHER, L1=YIELD_LINE, L2=INGREDIENT_LINE" in prompt
    assert "Span codes: R=in_recipe, N=outside_recipe, U=unknown_recipe_status" in prompt
    assert "Grounding windows:" in prompt
    assert "ctx:0|prev=_|line=SERVES 4|next=2 tablespoons olive oil" in prompt
    assert "0|L0|R|yield,needs_review|SERVES 4" in prompt


def test_canonical_line_role_prompt_compact_format_defines_row_schema_once() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="SERVES 4",
            within_recipe_span=True,
            rule_tags=["yield_prefix"],
        ),
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:2",
            block_index=2,
            atomic_index=1,
            text="2 tablespoons olive oil",
            within_recipe_span=True,
            rule_tags=["ingredient_like"],
        ),
    ]

    prompt = build_canonical_line_role_prompt(
        candidates,
        prompt_format="compact_v1",
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
    )
    assert "atomic_index|label_code|span_code|hint_codes|current_line" in prompt
    assert prompt.count("atomic_index|label_code|span_code|hint_codes|current_line") == 1
    assert "ordered contiguous slice of the book" in prompt
    assert "0|L1|R|yield|SERVES 4" in prompt
    assert "1|L1|R|ingredient|2 tablespoons olive oil" in prompt

    compact_rows = serialize_line_role_targets(
        candidates,
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
    )
    assert compact_rows.splitlines() == [
        "0|L1|R|yield|SERVES 4",
        "1|L1|R|ingredient|2 tablespoons olive oil",
    ]


def test_canonical_line_role_prompt_does_not_repeat_neighbor_text_for_escalated_rows() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="Praise for SALT FAT ACID HEAT",
            within_recipe_span=False,
            rule_tags=["outside_recipe"],
        ),
        AtomicLineCandidate(
            recipe_id="r1",
            block_id="block:2",
            block_index=2,
            atomic_index=1,
            text="SERVES 4",
            within_recipe_span=True,
            rule_tags=["yield_prefix"],
        ),
    ]

    compact_rows = serialize_line_role_targets(
        candidates,
        allowed_labels=["YIELD_LINE", "OTHER", "INGREDIENT_LINE"],
        escalation_reasons_by_atomic_index={
            0: ["outside_span_structured_label"],
            1: ["deterministic_unresolved"],
        },
    ).splitlines()

    assert compact_rows[0] == (
        "0|L1|N|outside,outside_structure|Praise for SALT FAT ACID HEAT"
    )
    assert compact_rows[1] == "1|L1|R|yield,needs_review|SERVES 4"


def test_canonical_candidate_fingerprint_changes_when_neighbor_text_changes() -> None:
    baseline = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text="Before",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text="Ambiguous line",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text="After",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]
    updated = [
        baseline[0],
        baseline[1],
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text="Changed after",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]

    assert canonical_line_roles_module._canonical_candidate_fingerprint(
        baseline
    ) != canonical_line_roles_module._canonical_candidate_fingerprint(updated)


def test_canonical_line_role_file_prompt_describes_compact_tuple_payload() -> None:
    prompt = build_canonical_line_role_file_prompt(
        input_path=Path("/tmp/line_role_input_0001.json"),
        input_payload={
            "v": 1,
            "shard_id": "line-role-canonical-0001-a000123-a000456",
            "rows": [[123, "L4", "1 cup flour"]],
        },
    )

    assert '{"rows":[{"atomic_index":<int>,"label":"<ALLOWED_LABEL>"}]}' in prompt
    assert (
        '{"v":1,"shard_id":"line-role-canonical-0001-a000123-a000456","rows":[[123,"L4","1 cup flour"]]}'
        in prompt
    )
    assert (
        "Treat each row's `label_code` as the deterministic first-pass label you are reviewing, not final truth."
        in prompt
    )
    assert "The authoritative shard rows are embedded below." in prompt
    assert "do not open it or inspect the workspace to answer" in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "Do not describe your plan, reasoning, or heuristics." in prompt
    assert "Your first response must be the final JSON object." in prompt
    assert "Each row is `[atomic_index, label_code, current_line]`." in prompt
    assert "Label codes:" in prompt
    assert "Return one result for every input row." in prompt
    assert "Use each row's tuple slot 2 (`current_line`) as the line to label." in prompt
    assert "Recompute labels from the task file rows themselves" in prompt
    assert "Never label a quantity/unit ingredient line as `KNOWLEDGE`." in prompt
    assert "Do not use `INSTRUCTION_LINE` for explanatory/advisory prose" in prompt
    assert "default to `KNOWLEDGE` or `OTHER`" in prompt
    assert "Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure" in prompt
    assert "A single outside-recipe heading by itself is not enough" in prompt
    assert "Salt and Pepper" in prompt
    assert '<BEGIN_AUTHORITATIVE_ROWS>\n[123, "L4", "1 cup flour"]\n<END_AUTHORITATIVE_ROWS>' in prompt


def test_codex_knowledge_inside_recipe_requires_explicit_prose_tags(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text=(
                "This paragraph gives narrative context about pan construction, and "
                "it includes multiple clauses to remain prose-like."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Another prose paragraph discusses heat retention, moisture movement, "
                "and texture outcomes in complete sentences."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text=(
                "A final prose paragraph closes the section, with punctuation and "
                "long-form explanation rather than imperative action."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "OTHER", 1: "KNOWLEDGE", 2: "OTHER"}),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "KNOWLEDGE"
    assert by_index[1].decided_by == "codex"


def test_codex_knowledge_inside_recipe_rejected_without_explicit_prose_tag(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:0",
            block_index=0,
            atomic_index=0,
            text=(
                "This paragraph gives narrative context about pan construction, and "
                "it includes multiple clauses to remain prose-like."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:1",
            block_index=1,
            atomic_index=1,
            text=(
                "Another prose paragraph discusses heat retention, moisture movement, "
                "and texture outcomes in complete sentences."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:2",
            block_index=2,
            atomic_index=2,
            text=(
                "A final prose paragraph closes the section, with punctuation and "
                "long-form explanation rather than imperative action."
            ),
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback", "explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner({0: "OTHER", 1: "KNOWLEDGE", 2: "OTHER"}),
        live_llm_allowed=True,
    )
    by_index = {row.atomic_index: row for row in predictions}
    assert by_index[1].label == "OTHER"
    assert by_index[1].decided_by == "fallback"


def test_codex_mode_does_not_escalate_outside_recipe_span_candidates_without_reasons() -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:1",
            block_index=1,
            atomic_index=0,
            text="CONTENTS",
            within_recipe_span=False,
            rule_tags=["outside_recipe_span"],
        )
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        codex_runner=_line_role_runner({0: "OTHER"}),
        live_llm_allowed=True,
    )
    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"
    assert predictions[0].escalation_reasons == []


def test_label_atomic_lines_codex_cache_hit_skips_runner(tmp_path) -> None:
    settings = _settings("codex-line-role-shard-v1")
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    runner = _line_role_runner({0: "OTHER"})
    first = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=runner,
        live_llm_allowed=True,
    )
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert runner.calls[0]["output_schema_path"] is None
    assert first[0].decided_by == "codex"
    second = label_atomic_lines(
        candidates,
        settings,
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-1",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert second[0].label == first[0].label
    assert second[0].decided_by == first[0].decided_by
    cache_files = list((tmp_path / "line-role-cache").rglob("*.json"))
    assert cache_files


def test_label_atomic_lines_writes_line_role_telemetry_summary_from_runtime_rows(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:telemetry:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _TelemetryRunner(FakeCodexExecRunner):
        @staticmethod
        def _with_usage(result):  # noqa: ANN001
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=result.response_text,
                turn_failed_message=result.turn_failed_message,
                events=result.events,
                usage={
                    "input_tokens": 20,
                    "cached_input_tokens": 4,
                    "output_tokens": 5,
                    "reasoning_tokens": 2,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
            )

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
            return self._with_usage(result)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            return self._with_usage(result)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_TelemetryRunner(output_builder=_line_role_runner({0: "OTHER"}).output_builder),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["batch_count"] == 1
    assert telemetry_payload["summary"]["attempt_count"] == 1
    assert telemetry_payload["summary"]["attempts_with_usage"] == 1
    assert telemetry_payload["summary"]["tokens_input"] == 20
    assert telemetry_payload["summary"]["tokens_cached_input"] == 4
    assert telemetry_payload["summary"]["tokens_output"] == 5
    assert telemetry_payload["summary"]["tokens_reasoning"] == 2
    assert telemetry_payload["summary"]["tokens_total"] == 31
    assert [phase["phase_key"] for phase in telemetry_payload["phases"]] == [
        "line_role",
    ]
    assert telemetry_payload["phases"][0]["batches"][0]["attempts"][0]["process_run"]["runtime_mode"] == "direct_codex_exec_v1"


def test_preflight_line_role_shard_rejects_missing_model_facing_rows() -> None:
    shard = ShardManifestEntryV1(
        shard_id="line-role-0001",
        owned_ids=("0",),
        input_payload={"rows": []},
    )

    assert _preflight_line_role_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "line-role shard has no model-facing rows",
    }


def test_label_atomic_lines_marks_watchdog_killed_shards_in_summary(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:watchdog:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _WatchdogRunner(FakeCodexExecRunner):
        def _watchdog_result(
            self,
            result,
            *,
            supervision_callback=None,
            timeout_seconds=None,
        ):  # noqa: ANN001
            decision = None
            if supervision_callback is not None:
                decision = supervision_callback(
                    CodexExecLiveSnapshot(
                        elapsed_seconds=4.0,
                        last_event_seconds_ago=0.0,
                        event_count=80,
                        command_execution_count=40,
                        reasoning_item_count=0,
                        last_command="/bin/bash -lc cat in/line-role-canonical-0001-a000000-a000000.json",
                        last_command_repeat_count=2,
                        has_final_agent_message=False,
                        timeout_seconds=timeout_seconds,
                    )
                )
            return result.__class__(
                command=result.command,
                subprocess_exit_code=result.subprocess_exit_code,
                output_schema_path=result.output_schema_path,
                prompt_text=result.prompt_text,
                response_text=None,
                turn_failed_message=str(
                    (decision.reason_detail if decision is not None else None)
                    or "strict JSON stage attempted tool use"
                ),
                events=(
                    {"type": "thread.started"},
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "id": "cmd-1",
                            "command": "/bin/bash -lc cat in/line-role-canonical-0001-a000000-a000000.json",
                        },
                    },
                ),
                usage={
                    "input_tokens": 7,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                stderr_text=result.stderr_text,
                stdout_text=result.stdout_text,
                source_working_dir=result.source_working_dir,
                execution_working_dir=result.execution_working_dir,
                execution_agents_path=result.execution_agents_path,
                duration_ms=result.duration_ms,
                started_at_utc=result.started_at_utc,
                finished_at_utc=result.finished_at_utc,
                supervision_state="watchdog_killed",
                supervision_reason_code=str(
                    (decision.reason_code if decision is not None else None)
                    or "watchdog_command_loop_without_output"
                ),
                supervision_reason_detail=str(
                    (decision.reason_detail if decision is not None else None)
                    or "workspace worker stage spent too many shell commands without reaching final output"
                ),
                supervision_retryable=bool(
                    decision.retryable if decision is not None else True
                ),
            )

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_structured_prompt(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            result = super().run_workspace_worker(*args, **kwargs)
            return self._watchdog_result(
                result,
                supervision_callback=kwargs.get("supervision_callback"),
                timeout_seconds=kwargs.get("timeout_seconds"),
            )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_WatchdogRunner(output_builder=_line_role_runner({0: "OTHER"}).output_builder),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].decided_by == "codex"
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 1
    assert "watchdog_kills_detected" in telemetry_payload["summary"]["pathological_flags"]
    assert "command_execution_detected" in telemetry_payload["summary"]["pathological_flags"]

    live_status_path = next(
        path
        for path in (tmp_path / "line-role-pipeline" / "runtime").rglob("live_status.json")
        if "shards" in path.parts
    )
    status_path = live_status_path.with_name("status.json")
    status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert status_payload["status"] == "validated"
    assert status_payload["state"] == "watchdog_killed"
    assert status_payload["reason_code"] == "watchdog_command_loop_without_output"
    assert "command_count=40" in status_payload["reason_detail"]

    live_status_payload = json.loads(live_status_path.read_text(encoding="utf-8"))
    assert live_status_payload["state"] == "watchdog_killed"
    assert live_status_payload["reason_code"] == "watchdog_command_loop_without_output"
    assert "command_count=40" in live_status_payload["reason_detail"]


def test_line_role_strict_watchdog_still_kills_benign_commands_in_structured_mode(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc ls",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is not None
    assert decision.reason_code == "watchdog_command_execution_forbidden"
    assert "ls" in str(decision.reason_detail or "")


def test_label_atomic_lines_allows_workspace_commands_without_immediate_kill(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:workspace-benign:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    class _WorkspaceCommandRunner(FakeCodexExecRunner):
        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            supervision_callback = kwargs.get("supervision_callback")
            if supervision_callback is not None:
                for command_count, last_command in (
                    (1, "/bin/bash -lc pwd"),
                    (2, "/bin/bash -lc 'find . -maxdepth 2 -type f | head -n 5 >/dev/null'"),
                    (3, "/bin/bash -lc cat in/line-role-canonical-0001-a000000-a000000.json"),
                    (5, "/bin/bash -lc sed -n '1,20p' in/line-role-canonical-0001-a000000-a000000.json"),
                    (
                        7,
                        "/bin/bash -lc \"cat <<'EOF' > scratch/helper.sh\n"
                        "jq -M -c '.rows[0]' in/line-role-canonical-0001-a000000-a000000.json >/dev/null\n"
                        "EOF\"",
                    ),
                    (9, "/bin/bash -lc jq .rows[0] in/line-role-canonical-0001-a000000-a000000.json"),
                ):
                    decision = supervision_callback(
                        CodexExecLiveSnapshot(
                            elapsed_seconds=0.1 * command_count,
                            last_event_seconds_ago=0.0,
                            event_count=2 * command_count,
                            command_execution_count=command_count,
                            reasoning_item_count=0,
                            last_command=last_command,
                            last_command_repeat_count=1,
                            has_final_agent_message=False,
                            timeout_seconds=kwargs.get("timeout_seconds"),
                        )
                    )
                    assert decision is None
            return super().run_workspace_worker(*args, **kwargs)

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_runner=_WorkspaceCommandRunner(output_builder=_line_role_runner({0: "OTHER"}).output_builder),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by == "codex"


def test_label_atomic_lines_allows_line_role_workspace_orientation_commands(
    tmp_path: Path,
) -> None:
    callback = canonical_line_roles_module._build_strict_json_watchdog_callback(  # noqa: SLF001
        live_status_path=tmp_path / "live_status.json",
        watchdog_policy="workspace_worker_v1",
        allow_workspace_commands=True,
    )
    decision = callback(
        CodexExecLiveSnapshot(
            elapsed_seconds=0.1,
            last_event_seconds_ago=0.0,
            event_count=2,
            command_execution_count=1,
            reasoning_item_count=0,
            last_command="/bin/bash -lc ls",
            last_command_repeat_count=1,
            has_final_agent_message=False,
            timeout_seconds=30,
        )
    )

    assert decision is None
    live_status = json.loads((tmp_path / "live_status.json").read_text(encoding="utf-8"))
    assert live_status["last_command_policy"] == "tolerated_orientation_command"
    assert live_status["last_command_policy_allowed"] is True
    assert live_status["last_command_boundary_violation_detected"] is False


def test_label_atomic_lines_retries_cohort_outlier_watchdog_once(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MIN_ELAPSED_MS",
        10,
    )
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_COHORT_WATCHDOG_MEDIAN_FACTOR",
        2.0,
    )

    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:outlier:{atomic_index}",
            block_index=atomic_index,
            atomic_index=atomic_index,
            text=f"Ambiguous line {atomic_index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for atomic_index in range(4)
    ]

    class _OutlierRetryRunner(FakeCodexExecRunner):
        @staticmethod
        def _first_atomic_index_for_workspace(working_dir) -> int:  # noqa: ANN001
            worker_root = Path(str(working_dir))
            assigned_shards_path = worker_root / "assigned_shards.json"
            if not assigned_shards_path.exists():
                return -1
            assigned_shards = json.loads(assigned_shards_path.read_text(encoding="utf-8"))
            if not isinstance(assigned_shards, list) or not assigned_shards:
                return -1
            shard_row = assigned_shards[0]
            if not isinstance(shard_row, dict):
                return -1
            shard_id = str(shard_row.get("shard_id") or "").strip()
            if not shard_id:
                return -1
            input_path = worker_root / "in" / f"{shard_id}.json"
            if not input_path.exists():
                return -1
            payload = json.loads(input_path.read_text(encoding="utf-8"))
            rows = payload.get("rows") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                return -1
            first_row = rows[0]
            return int(first_row[0]) if isinstance(first_row, list) and first_row else -1

        def run_structured_prompt(self, *args, **kwargs):  # noqa: ANN002, ANN003
            payload = dict(kwargs.get("input_payload") or {})
            rows = payload.get("rows") or []
            first_atomic_index = int(rows[0][0]) if rows else -1
            if payload.get("retry_mode") == "line_role_watchdog":
                return super().run_structured_prompt(*args, **kwargs)
            if first_atomic_index == 3:
                supervision_callback = kwargs.get("supervision_callback")
                decision = None
                if supervision_callback is not None:
                    for _ in range(40):
                        time.sleep(0.05)
                        decision = supervision_callback(
                            CodexExecLiveSnapshot(
                                elapsed_seconds=0.2,
                                last_event_seconds_ago=0.05,
                                event_count=0,
                                command_execution_count=0,
                                reasoning_item_count=0,
                                last_command=None,
                                last_command_repeat_count=0,
                                has_final_agent_message=False,
                                timeout_seconds=kwargs.get("timeout_seconds"),
                            )
                        )
                        if decision is not None:
                            break
                assert decision is not None
                from cookimport.llm.codex_exec_runner import CodexExecRunResult

                return CodexExecRunResult(
                    command=["codex", "exec"],
                    subprocess_exit_code=0,
                    output_schema_path=str(kwargs.get("output_schema_path")),
                    prompt_text=str(kwargs.get("prompt_text") or ""),
                    response_text=None,
                    turn_failed_message=str(decision.reason_detail or ""),
                    events=(),
                    usage={
                        "input_tokens": 7,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                    },
                    source_working_dir=str(kwargs.get("working_dir")),
                    execution_working_dir=str(kwargs.get("working_dir")),
                    execution_agents_path=None,
                    duration_ms=50,
                    started_at_utc="2026-01-01T00:00:00Z",
                    finished_at_utc="2026-01-01T00:00:00Z",
                    supervision_state="watchdog_killed",
                    supervision_reason_code=str(decision.reason_code),
                    supervision_reason_detail=str(decision.reason_detail),
                    supervision_retryable=bool(decision.retryable),
                )
            return super().run_structured_prompt(*args, **kwargs)

        def run_workspace_worker(self, *args, **kwargs):  # noqa: ANN002, ANN003
            first_atomic_index = self._first_atomic_index_for_workspace(kwargs.get("working_dir"))
            if first_atomic_index == 3:
                supervision_callback = kwargs.get("supervision_callback")
                decision = None
                if supervision_callback is not None:
                    for _ in range(40):
                        time.sleep(0.05)
                        decision = supervision_callback(
                            CodexExecLiveSnapshot(
                                elapsed_seconds=0.2,
                                last_event_seconds_ago=0.05,
                                event_count=0,
                                command_execution_count=0,
                                reasoning_item_count=0,
                                last_command=None,
                                last_command_repeat_count=0,
                                has_final_agent_message=False,
                                timeout_seconds=kwargs.get("timeout_seconds"),
                            )
                        )
                        if decision is not None:
                            break
                assert decision is not None
                from cookimport.llm.codex_exec_runner import CodexExecRunResult

                return CodexExecRunResult(
                    command=["codex", "exec"],
                    subprocess_exit_code=0,
                    output_schema_path=None,
                    prompt_text=str(kwargs.get("prompt_text") or ""),
                    response_text=None,
                    turn_failed_message=str(decision.reason_detail or ""),
                    events=(),
                    usage={
                        "input_tokens": 7,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                    },
                    source_working_dir=str(kwargs.get("working_dir")),
                    execution_working_dir=str(kwargs.get("working_dir")),
                    execution_agents_path=None,
                    duration_ms=50,
                    started_at_utc="2026-01-01T00:00:00Z",
                    finished_at_utc="2026-01-01T00:00:00Z",
                    supervision_state="watchdog_killed",
                    supervision_reason_code=str(decision.reason_code),
                    supervision_reason_detail=str(decision.reason_detail),
                    supervision_retryable=bool(decision.retryable),
                )
            return super().run_workspace_worker(*args, **kwargs)

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_worker_count=4,
            line_role_prompt_target_count=4,
        ),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_OutlierRetryRunner(
            output_builder=lambda payload: {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "OTHER"}
                    for row in (payload.get("rows") or [])
                ]
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "OTHER",
        "OTHER",
        "OTHER",
        "OTHER",
    ]
    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["watchdog_killed_shard_count"] == 1
    assert telemetry_payload["summary"]["attempt_count"] == 5

    proposal_paths = list(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "proposals").glob("*.json")
    )
    recovered_proposal = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in proposal_paths
        if json.loads(path.read_text(encoding="utf-8")).get("watchdog_retry_attempted")
    )
    assert recovered_proposal["watchdog_retry_status"] == "recovered"
    assert recovered_proposal["validation_errors"] == []

    retry_status_path = next(
        (tmp_path / "line-role-pipeline" / "runtime").rglob("watchdog_retry_status.json")
    )
    retry_status = json.loads(retry_status_path.read_text(encoding="utf-8"))
    assert retry_status["status"] == "validated"
    assert retry_status["watchdog_retry_reason_code"] == "watchdog_cohort_runtime_outlier"

    retry_prompt = (
        retry_status_path.parent / "watchdog_retry_prompt.txt"
    ).read_text(encoding="utf-8")
    assert "Successful sibling examples:" in retry_prompt
    assert "Authoritative shard rows to relabel" in retry_prompt
    assert "Your first response must be the final JSON object." in retry_prompt
    assert "Do not describe your plan, reasoning, or heuristics." in retry_prompt


def test_label_atomic_lines_accepts_valid_workspace_outputs_without_final_message(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:authoritative:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    runner = _NoFinalWorkspaceMessageRunner(
        output_builder=lambda payload: {"rows": [{"atomic_index": 0, "label": "OTHER"}]}
    )

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=runner,
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"

    proposal_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "proposals").glob(
            "*.json"
        )
    )
    proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal_payload["validation_errors"] == []
    assert proposal_payload["repair_attempted"] is False

    worker_status_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "workers").rglob(
            "status.json"
        )
    )
    worker_status = json.loads(worker_status_path.read_text(encoding="utf-8"))
    rows = worker_status["telemetry"]["rows"]
    assert rows
    assert rows[0]["final_agent_message_state"] == "absent"
    assert rows[0]["final_agent_message_reason"] is None


def test_label_atomic_lines_repairs_near_miss_invalid_shard_once(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:repair:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    def _output_builder(payload):
        if payload and payload.get("repair_mode") == "line_role":
            return {"rows": [{"atomic_index": 0, "label": "OTHER"}]}
        return {"rows": []}

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=FakeCodexExecRunner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert len(predictions) == 1
    assert predictions[0].label == "OTHER"

    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["attempt_count"] == 2
    assert telemetry_payload["summary"]["repaired_shard_count"] == 1
    assert telemetry_payload["summary"]["invalid_output_shard_count"] == 1

    repair_status_path = next(
        (tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json")
    )
    repair_status = json.loads(repair_status_path.read_text(encoding="utf-8"))
    assert repair_status["status"] == "repaired"
    repair_prompt = (repair_status_path.parent / "repair_prompt.txt").read_text(
        encoding="utf-8"
    )
    assert "Authoritative shard rows to relabel" in repair_prompt
    assert "Your first response must be the final JSON object." in repair_prompt
    assert "Do not describe your plan, reasoning, or heuristics." in repair_prompt


def test_label_atomic_lines_accepts_valid_uniform_packet_output_without_reverting_to_baseline(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:0",
            block_index=0,
            atomic_index=0,
            text="SERVES 4",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:1",
            block_index=1,
            atomic_index=1,
            text="1 cup flour",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:2",
            block_index=2,
            atomic_index=2,
            text="Stir until smooth.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:uniform:3",
            block_index=3,
            atomic_index=3,
            text="NOTE: Keep warm.",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        ),
    ]
    def _output_builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        return {
            "rows": [
                {"atomic_index": int(row[0]), "label": "INGREDIENT_LINE"}
                for row in rows
            ]
        }

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_runner=FakeCodexExecRunner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert all(prediction.label == "INGREDIENT_LINE" for prediction in predictions)

    telemetry_payload = json.loads(
        (tmp_path / "line-role-pipeline" / "telemetry_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert telemetry_payload["summary"]["attempt_count"] == 1

    proposal_path = next(
        (tmp_path / "line-role-pipeline" / "runtime" / "line_role" / "proposals").glob(
            "*.json"
        )
    )
    proposal_payload = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert proposal_payload["validation_errors"] == []
    assert proposal_payload["validation_metadata"]["task_aggregation"]["fallback_task_count"] == 0


def test_validate_line_role_payload_semantics_reports_uniform_diagnostic_against_diverse_baseline() -> None:
    baseline = {
        0: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b0",
            block_index=0,
            atomic_index=0,
            text="A",
            within_recipe_span=True,
            label="INGREDIENT_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
        1: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b1",
            block_index=1,
            atomic_index=1,
            text="B",
            within_recipe_span=True,
            label="INSTRUCTION_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
        2: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b2",
            block_index=2,
            atomic_index=2,
            text="C",
            within_recipe_span=True,
            label="RECIPE_NOTES",
            decided_by="rule",
            reason_tags=[],
        ),
        3: canonical_line_roles_module.CanonicalLineRolePrediction(
            recipe_id="recipe:0",
            block_id="b3",
            block_index=3,
            atomic_index=3,
            text="D",
            within_recipe_span=True,
            label="YIELD_LINE",
            decided_by="rule",
            reason_tags=[],
        ),
    }

    semantic_errors, semantic_metadata = canonical_line_roles_module._validate_line_role_payload_semantics(  # noqa: SLF001
        payload={
            "rows": [
                {"atomic_index": 0, "label": "INGREDIENT_LINE"},
                {"atomic_index": 1, "label": "INGREDIENT_LINE"},
                {"atomic_index": 2, "label": "INGREDIENT_LINE"},
                {"atomic_index": 3, "label": "INGREDIENT_LINE"},
            ]
        },
        deterministic_baseline_by_atomic_index=baseline,
    )

    assert semantic_metadata["guard_applied"] is True
    assert "pathological_uniform_label_output:INGREDIENT_LINE" in semantic_errors


def test_label_atomic_lines_repairs_split_task_packets(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_TASK_TARGET_ROWS",
        2,
    )
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:repair-task:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous repair line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(4)
    ]

    def _output_builder(payload):
        rows = payload.get("rows") if isinstance(payload, dict) else []
        if payload and payload.get("repair_mode") == "line_role":
            return {
                "rows": [
                    {"atomic_index": int(row[0]), "label": "OTHER"}
                    for row in rows
                ]
            }
        return {"rows": []}

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_prompt_target_count=1,
            line_role_worker_count=1,
        ),
        artifact_root=tmp_path,
        codex_batch_size=4,
        codex_runner=FakeCodexExecRunner(output_builder=_output_builder),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == ["OTHER"] * 4

    repair_status_paths = sorted(
        (tmp_path / "line-role-pipeline" / "runtime").rglob("repair_status.json")
    )
    assert [path.parent.name for path in repair_status_paths] == [
        "line-role-canonical-0001-a000000-a000003.task-001",
        "line-role-canonical-0001-a000000-a000003.task-002",
    ]
    for repair_status_path in repair_status_paths:
        repair_status = json.loads(repair_status_path.read_text(encoding="utf-8"))
        assert repair_status["status"] == "repaired"
        repair_prompt_path = repair_status_path.parent / "repair_prompt.txt"
        assert repair_prompt_path.exists()
        repair_prompt = repair_prompt_path.read_text(encoding="utf-8")
        assert "Authoritative shard rows to relabel" in repair_prompt


def test_label_atomic_lines_codex_cache_reuses_across_runtime_only_setting_changes(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:runtime",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]
    runner = _line_role_runner({0: "OTHER"})
    first = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", workers=1, codex_farm_cmd="codex-a"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=runner,
        live_llm_allowed=True,
    )
    assert len(runner.calls) == 1
    assert runner.calls[0]["mode"] == "workspace_worker"
    assert runner.calls[0]["output_schema_path"] is None
    assert first[0].decided_by == "codex"
    second = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", workers=9, codex_farm_cmd="codex-b"),
        artifact_root=tmp_path / "artifacts",
        source_hash="source-hash-runtime",
        cache_root=tmp_path / "line-role-cache",
        codex_runner=_line_role_runner({0: "RECIPE_TITLE"}),
        live_llm_allowed=True,
    )
    assert second[0].label == first[0].label


def test_line_role_cache_path_changes_when_line_role_pipeline_changes(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:cache:path",
            block_index=0,
            atomic_index=0,
            text="Ambiguous context sentence",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
    ]

    off_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("off"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )
    codex_path = canonical_line_roles_module._resolve_line_role_cache_path(
        source_hash="source-hash-path",
        settings=_settings("codex-line-role-shard-v1"),
        ordered_candidates=candidates,
        artifact_root=tmp_path / "artifacts",
        cache_root=tmp_path / "line-role-cache",
        codex_timeout_seconds=30,
        codex_batch_size=8,
    )

    assert off_path is not None
    assert codex_path is not None
    assert off_path != codex_path


def test_label_atomic_lines_codex_shards_keep_deterministic_output_order(
    tmp_path,
) -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(4):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:parallel:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "OTHER", 1: "OTHER", 2: "OTHER", 3: "OTHER"}),
        live_llm_allowed=True,
    )
    assert [row.atomic_index for row in predictions] == [0, 1, 2, 3]
    assert all(row.label == "OTHER" for row in predictions)

    prompt_dir = tmp_path / "line-role-pipeline" / "prompts"
    dedup_lines = (
        prompt_dir / "line_role" / "codex_prompt_log.dedup.txt"
    ).read_text(encoding="utf-8").splitlines()
    assert len(dedup_lines) == 4
    assert all("\tline_role_prompt_" in line for line in dedup_lines)


def test_label_atomic_lines_uses_compact_prompt_format_when_env_enabled(
    monkeypatch,
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id="block:compact:0",
            block_index=0,
            atomic_index=0,
            text="Ambiguous line 0",
            within_recipe_span=None,
            rule_tags=[],
        )
    ]

    monkeypatch.setenv("COOKIMPORT_LINE_ROLE_PROMPT_FORMAT", "compact_v1")

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1"),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "OTHER"}),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "OTHER"
    prompt_text = (
        tmp_path
        / "line-role-pipeline"
        / "prompts"
        / "line_role"
        / "line_role_prompt_0001.txt"
    ).read_text(encoding="utf-8")
    assert "You are processing many canonical line-role task packets inside one local worker workspace." in prompt_text
    assert "Start by opening `worker_manifest.json`, then `assigned_tasks.json`, then `assigned_shards.json`." in prompt_text
    assert "Do not orient yourself with `pwd`, `ls`, `find`, `tree`" in prompt_text
    assert "keep them narrow and grounded on the named local files only" in prompt_text
    assert "Stay inside this workspace" in prompt_text
    assert "Read `assigned_tasks.json` and process the assigned task packets in order." in prompt_text
    assert "open `hints/<task_id>.md` first" in prompt_text
    assert "write exactly one JSON object to `out/<task_id>.json`." in prompt_text
    worker_prompt_text = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "shards"
        / "line-role-canonical-0001-a000000-a000000"
        / "prompt.txt"
    ).read_text(encoding="utf-8")
    assert "You are processing many canonical line-role task packets inside one local worker workspace." in worker_prompt_text
    assert "worker_manifest.json" in worker_prompt_text
    assert "Assigned task files:" in worker_prompt_text
    worker_manifest_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "worker_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert worker_manifest_payload["entry_files"] == [
        "worker_manifest.json",
        "assigned_shards.json",
        "assigned_tasks.json",
    ]
    assert worker_manifest_payload["hints_dir"] == "hints"
    worker_hint_text = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "hints"
        / "line-role-canonical-0001-a000000-a000000.md"
    ).read_text(encoding="utf-8")
    assert "Label code legend" in worker_hint_text
    assert "Attention rows" in worker_hint_text
    worker_input_text = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
        / "in"
        / "line-role-canonical-0001-a000000-a000000.json"
    ).read_text(encoding="utf-8")
    worker_input_payload = json.loads(worker_input_text)
    assert worker_input_payload["rows"] == [[0, "L9", "Ambiguous line 0"]]
    input_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "in"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    debug_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "workers"
            / "worker-001"
            / "debug"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert input_payload["rows"][0][2] == "Ambiguous line 0"
    assert debug_payload["rows"][0]["current_line"] == "Ambiguous line 0"
    assert "prev_text" not in debug_payload["rows"][0]
    assert "next_text" not in debug_payload["rows"][0]


def test_label_atomic_lines_splits_one_shard_into_multiple_task_packets(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(
        canonical_line_roles_module,
        "_LINE_ROLE_TASK_TARGET_ROWS",
        2,
    )
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:task:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Ambiguous line {index}",
            within_recipe_span=None,
            rule_tags=[],
        )
        for index in range(4)
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_prompt_target_count=1,
        ),
        artifact_root=tmp_path,
        codex_batch_size=4,
        codex_runner=_line_role_runner({index: "OTHER" for index in range(4)}),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == ["OTHER"] * 4
    worker_root = (
        tmp_path
        / "line-role-pipeline"
        / "runtime"
        / "line_role"
        / "workers"
        / "worker-001"
    )
    assigned_tasks = json.loads(
        (worker_root / "assigned_tasks.json").read_text(encoding="utf-8")
    )
    assert [row["task_id"] for row in assigned_tasks] == [
        "line-role-canonical-0001-a000000-a000003.task-001",
        "line-role-canonical-0001-a000000-a000003.task-002",
    ]
    assert sorted(path.name for path in (worker_root / "out").glob("*.json")) == [
        "line-role-canonical-0001-a000000-a000003.task-001.json",
        "line-role-canonical-0001-a000000-a000003.task-002.json",
    ]
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000003.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == []
    assert len(proposal_payload["payload"]["rows"]) == 4
    assert (
        proposal_payload["validation_metadata"]["task_aggregation"]["task_count"] == 2
    )


def test_label_atomic_lines_writes_canonical_line_table_and_task_status(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:line-table:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Line {index}",
            within_recipe_span=bool(index == 0),
            rule_tags=["recipe_span_fallback"] if index == 0 else [],
        )
        for index in range(2)
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=_line_role_runner({0: "OTHER", 1: "KNOWLEDGE"}),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == ["OTHER", "KNOWLEDGE"]
    runtime_root = tmp_path / "line-role-pipeline" / "runtime" / "line_role"
    line_table_rows = [
        json.loads(line)
        for line in (runtime_root / "canonical_line_table.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [row["line_id"] for row in line_table_rows] == ["0", "1"]
    assert [row["current_line"] for row in line_table_rows] == ["Line 0", "Line 1"]
    task_status_rows = [
        json.loads(line)
        for line in (runtime_root / "task_status.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert all(row["state"] == "validated" for row in task_status_rows)
    assert sum(row["metadata"]["llm_authoritative_row_count"] for row in task_status_rows) == 2
    assert sum(row["metadata"]["fallback_row_count"] for row in task_status_rows) == 0


def test_label_atomic_lines_resume_existing_valid_packet_outputs_without_rerunning_worker(
    tmp_path: Path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id="recipe:0",
            block_id=f"block:resume:{index}",
            block_index=index,
            atomic_index=index,
            text=f"Resume line {index}",
            within_recipe_span=True,
            rule_tags=["recipe_span_fallback"],
        )
        for index in range(2)
    ]

    first_runner = _line_role_runner({0: "OTHER", 1: "OTHER"})
    first_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=first_runner,
        live_llm_allowed=True,
    )
    assert [prediction.label for prediction in first_predictions] == ["OTHER", "OTHER"]
    assert any(call["mode"] == "workspace_worker" for call in first_runner.calls)

    second_runner = _line_role_runner({0: "KNOWLEDGE", 1: "KNOWLEDGE"})
    second_predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=2,
        codex_runner=second_runner,
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in second_predictions] == ["OTHER", "OTHER"]
    assert second_runner.calls == []
    task_status_rows = [
        json.loads(line)
        for line in (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "task_status.jsonl"
        ).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert task_status_rows[0]["last_attempt_type"] == "resume_existing_output"
    assert task_status_rows[0]["metadata"]["resumed_from_existing_output"] is True


def test_line_role_workspace_worker_invalid_task_output_falls_back_without_invalidating_parent_shard(
    tmp_path,
) -> None:
    predictions = label_atomic_lines(
        [
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id="block:task-invalid:0",
                block_index=0,
                atomic_index=0,
                text="Ambiguous line 0",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        ],
        _settings("codex-line-role-shard-v1", line_role_worker_count=1),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_runner=FakeCodexExecRunner(
            output_builder=lambda _payload: {
                "rows": [{"atomic_index": 999, "label": "OTHER"}]
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[0].label == "OTHER"
    assert predictions[0].decided_by != "codex"
    proposal_payload = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "proposals"
            / "line-role-canonical-0001-a000000-a000000.json"
        ).read_text(encoding="utf-8")
    )
    assert proposal_payload["validation_errors"] == []
    assert proposal_payload["payload"]["rows"] == [{"atomic_index": 0, "label": "OTHER"}]
    assert (
        proposal_payload["validation_metadata"]["task_aggregation"]["fallback_task_count"]
        == 1
    )


def test_line_role_prompt_format_defaults_to_compact_when_env_unset(
    monkeypatch,
) -> None:
    monkeypatch.delenv("COOKIMPORT_LINE_ROLE_PROMPT_FORMAT", raising=False)

    assert canonical_line_roles_module._resolve_line_role_prompt_format() == "compact_v1"


def test_label_atomic_lines_codex_progress_callback_reports_shard_runtime_start_and_finish() -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(3):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:progress:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings(
            "codex-line-role-shard-v1",
            line_role_worker_count=2,
            line_role_prompt_target_count=None,
        ),
        codex_batch_size=1,
        codex_runner=_line_role_runner({0: "OTHER", 1: "OTHER", 2: "OTHER"}),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert progress_texts[0] == (
        "Running canonical line-role pipeline... task 0/3"
    )
    assert (
        "Running canonical line-role pipeline... task 0/3 | running 2"
        in progress_texts
    )
    assert progress_texts[-1] == (
        "Running canonical line-role pipeline... task 3/3 | running 0"
    )


def test_label_atomic_lines_codex_max_inflight_override_takes_precedence(
    tmp_path,
) -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(3):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:override:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_prompt_target_count=None),
        artifact_root=tmp_path,
        codex_batch_size=1,
        codex_max_inflight=3,
        codex_runner=_line_role_runner({0: "OTHER", 1: "OTHER", 2: "OTHER"}),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    assert [row.atomic_index for row in predictions] == [0, 1, 2]
    assert (
        "Running canonical line-role pipeline... task 0/3 | running 3"
        in progress_texts
    )
    phase_manifest = json.loads(
        (
            tmp_path
            / "line-role-pipeline"
            / "runtime"
            / "line_role"
            / "phase_manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert phase_manifest["worker_count"] == 3


def test_label_atomic_lines_defaults_workers_to_shard_count_when_unspecified() -> None:
    candidates: list[AtomicLineCandidate] = []
    for atomic_index in range(5):
        candidates.append(
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id=f"block:default-workers:{atomic_index}",
                block_index=atomic_index,
                atomic_index=atomic_index,
                text=f"Ambiguous line {atomic_index}",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            )
        )

    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-shard-v1", line_role_prompt_target_count=None),
        codex_batch_size=1,
        codex_runner=_line_role_runner(
            {
                0: "OTHER",
                1: "OTHER",
                2: "OTHER",
                3: "OTHER",
                4: "OTHER",
            }
        ),
        live_llm_allowed=True,
        progress_callback=progress_messages.append,
    )

    progress_texts = _progress_messages_as_text(progress_messages)
    assert [row.atomic_index for row in predictions] == [0, 1, 2, 3, 4]
    assert (
        "Running canonical line-role pipeline... task 0/5 | running 5"
        in progress_texts
    )


def test_label_atomic_lines_deterministic_progress_callback_reports_task_counts() -> None:
    blocks = [
        {
            "block_id": "block:det:0",
            "block_index": 0,
            "text": "SERVES 4",
        },
        {
            "block_id": "block:det:1",
            "block_index": 1,
            "text": "2 tablespoons olive oil",
        },
    ]
    candidates = atomize_blocks(
        blocks,
        recipe_id="recipe:det",
        within_recipe_span=True,
    )
    progress_messages: list[str] = []
    predictions = label_atomic_lines(
        candidates,
        _settings("off"),
        progress_callback=progress_messages.append,
    )
    progress_texts = _progress_messages_as_text(progress_messages)
    assert len(predictions) == 2
    assert progress_texts[0] == "Running canonical line-role pipeline... task 0/2"
    assert progress_texts[-1] == "Running canonical line-role pipeline... task 2/2"
    assert all("| running " not in message for message in progress_texts)
