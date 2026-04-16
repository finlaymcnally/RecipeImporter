from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cookimport.labelstudio.prelabel as prelabel_module
from cookimport.labelstudio.prelabel import (
    CodexFarmProvider,
    codex_account_summary,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    default_codex_model,
    default_codex_cmd,
    default_codex_reasoning_effort,
    codex_reasoning_effort_from_cmd,
    list_codex_models,
    is_rate_limit_message,
    parse_span_label_output,
    preflight_codex_model_access,
    prelabel_freeform_task,
)


class _StaticProvider:
    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, _prompt: str) -> str:
        return self._response


class _CaptureProvider:
    def __init__(self, response: str) -> None:
        self._response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._response


def _freeform_task() -> dict[str, object]:
    return {
        "id": 100,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:1",
            "segment_text": "Serves 4\n\n1 cup flour",
            "source_map": {
                "separator": "\n\n",
                "focus_start_row_index": 0,
                "focus_end_row_index": 1,
                "focus_row_indices": [0, 1],
                "rows": [
                    {
                        "row_id": "row-0",
                        "row_index": 0,
                        "block_index": 0,
                        "text": "Serves 4",
                        "segment_start": 0,
                        "segment_end": 8,
                    },
                    {
                        "row_id": "row-1",
                        "row_index": 1,
                        "block_index": 1,
                        "text": "1 cup flour",
                        "segment_start": 10,
                        "segment_end": 21,
                    },
                ],
            },
        },
    }


def _single_block_task(text: str) -> dict[str, object]:
    return {
        "id": 200,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:5:5",
            "segment_text": text,
            "source_map": {
                "separator": "\n\n",
                "focus_start_row_index": 5,
                "focus_end_row_index": 5,
                "focus_row_indices": [5],
                "rows": [
                    {
                        "row_id": "row-5",
                        "row_index": 5,
                        "block_index": 5,
                        "text": text,
                        "segment_start": 0,
                        "segment_end": len(text),
                    }
                ],
            },
        },
    }


def test_parse_span_label_output_extracts_quote_and_absolute_items() -> None:
    raw = (
        "extra text\n"
        '[{"row_index": 5, "label": "time", "quote": "Prep 10 min"},'
        '{"row_index": 5, "label": "yield", "quote": "Serves 4", "occurrence": 1},'
        '{"label": "notes", "start": 2, "end": 8}]'
    )
    parsed = parse_span_label_output(raw)
    assert parsed == [
        {
            "kind": "quote",
            "row_index": 5,
            "label": "TIME_LINE",
            "quote": "Prep 10 min",
            "occurrence": None,
        },
        {
            "kind": "quote",
            "row_index": 5,
            "label": "YIELD_LINE",
            "quote": "Serves 4",
            "occurrence": 1,
        },
        {
            "kind": "absolute",
            "label": "RECIPE_NOTES",
            "start": 2,
            "end": 8,
        },
    ]


def test_is_rate_limit_message_matches_common_429_shapes() -> None:
    assert is_rate_limit_message("HTTP 429 Too Many Requests: rate limit exceeded")
    assert is_rate_limit_message("provider error: rate-limited")
    assert not is_rate_limit_message("model access denied")


def test_prelabel_freeform_task_uses_row_offsets_and_exact_text() -> None:
    task = _freeform_task()
    provider = _StaticProvider(
        '[{"row_index": 0, "label": "YIELD_LINE", "quote": "Serves 4"}, '
        '{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    results = annotation["result"]
    assert len(results) == 2

    first = results[0]["value"]
    second = results[1]["value"]
    assert first["start"] == 0
    assert first["end"] == 8
    assert first["text"] == "Serves 4"
    assert second["start"] == 10
    assert second["end"] == 21
    assert second["text"] == "1 cup flour"
    assert results[0]["from_name"] == "span_labels"
    assert results[0]["to_name"] == "segment_text"
    assert results[0]["type"] == "labels"


def test_prelabel_freeform_task_span_mode_creates_partial_block_spans() -> None:
    task = _single_block_task("Serves 4 • Prep 10 min")
    provider = _StaticProvider(
        '[{"row_index": 5, "label": "YIELD_LINE", "quote": "Serves 4"},'
        '{"row_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    results = annotation["result"]
    assert len(results) == 2

    by_label = {
        result["value"]["labels"][0]: result["value"]
        for result in results
    }
    assert by_label["YIELD_LINE"]["text"] == "Serves 4"
    assert by_label["TIME_LINE"]["text"] == "Prep 10 min"
    assert by_label["YIELD_LINE"]["start"] == 0
    assert by_label["YIELD_LINE"]["end"] == 8
    assert by_label["TIME_LINE"]["start"] > 0
    assert (
        by_label["TIME_LINE"]["start"],
        by_label["TIME_LINE"]["end"],
    ) != (0, len(task["data"]["segment_text"]))


def test_prelabel_freeform_task_allows_explicit_empty_array_output() -> None:
    task = _single_block_task("CONTENTS")
    provider = _StaticProvider("[]")

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    assert annotation["result"] == []
    assert annotation["meta"]["mode"] == "empty"


def test_codex_farm_provider_respects_xdg_cache_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))

    provider = CodexFarmProvider(cmd="codex-farm", timeout_s=60)

    assert provider.cache_dir == tmp_path / "xdg-cache" / "cookimport" / "prelabel"
    assert provider.cache_dir.is_dir()


def test_prelabel_span_mode_repairs_quote_block_index_mismatch() -> None:
    task = {
        "id": 400,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:2",
            "segment_text": "A\n\nB\n\nC",
            "source_map": {
                "separator": "\n\n",
                "focus_start_row_index": 0,
                "focus_end_row_index": 2,
                "focus_row_indices": [0, 1, 2],
                "rows": [
                    {
                        "row_id": "row-0",
                        "row_index": 0,
                        "block_index": 0,
                        "text": "A",
                        "segment_start": 0,
                        "segment_end": 1,
                    },
                    {
                        "row_id": "row-1",
                        "row_index": 1,
                        "block_index": 1,
                        "text": "B",
                        "segment_start": 3,
                        "segment_end": 4,
                    },
                    {
                        "row_id": "row-2",
                        "row_index": 2,
                        "block_index": 2,
                        "text": "C",
                        "segment_start": 6,
                        "segment_end": 7,
                    },
                ],
            },
        },
    }
    provider = _StaticProvider(
        '[{"row_index": 0, "label": "OTHER", "quote": "B"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    assert len(annotation["result"]) == 1
    value = annotation["result"][0]["value"]
    assert value["labels"] == ["OTHER"]
    assert value["text"] == "B"
    assert value["start"] == 3
    assert value["end"] == 4


def test_span_resolution_requires_occurrence_for_ambiguous_quote() -> None:
    task = _single_block_task("Prep 10 min; Prep 10 min")

    ambiguous_provider = _StaticProvider(
        '[{"row_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min"}]'
    )
    ambiguous_annotation = prelabel_freeform_task(
        task,
        provider=ambiguous_provider,
        prelabel_granularity="span",
    )
    assert ambiguous_annotation is None

    disambiguated_provider = _StaticProvider(
        '[{"row_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min", "occurrence": 2}]'
    )
    disambiguated_annotation = prelabel_freeform_task(
        task,
        provider=disambiguated_provider,
        prelabel_granularity="span",
    )
    assert disambiguated_annotation is not None
    value = disambiguated_annotation["result"][0]["value"]
    assert value["text"] == "Prep 10 min"
    assert value["start"] == 13
    assert value["end"] == 24


def test_prelabel_span_prompt_uses_ai_instruction_template() -> None:
    task = _freeform_task()
    provider = _CaptureProvider(
        '[{"row_index": 0, "label": "YIELD_LINE", "quote": "Serves 4"}, '
        '{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "Segment id: urn:cookimport:segment:testhash:0:1" in prompt
    assert "0\tServes 4" in prompt
    assert "1\t1 cup flour" in prompt


def test_prelabel_prompt_includes_focus_scope() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_row_index"] = 1
    task["data"]["source_map"]["focus_end_row_index"] = 1
    task["data"]["source_map"]["focus_row_indices"] = [1]
    provider = _CaptureProvider(
        '[{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "Label only spans from rows between:" in prompt
    assert "1\t1 cup flour" in prompt


def test_prelabel_span_prompt_marks_focus_window_without_block_duplication() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_row_index"] = 1
    task["data"]["source_map"]["focus_end_row_index"] = 1
    task["data"]["source_map"]["focus_row_indices"] = [1]
    provider = _CaptureProvider(
        '[{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "Focus block indices (for quick reference):" not in prompt
    assert "<<<START_LABELING_ROWS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>" in prompt
    blocks_section = prompt.split(
        "Rows (single pass with explicit context-before / focus / context-after markers):", 1
    )[1]
    assert "<<<CONTEXT_BEFORE_LABELING_ONLY>>>" in blocks_section
    assert "<<<CONTEXT_AFTER_LABELING_ONLY>>>" not in blocks_section
    assert prompt.count("1\t1 cup flour") == 1


def test_prelabel_span_prompt_marks_context_before_and_after() -> None:
    task = {
        "id": 300,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:2",
            "segment_text": "A\n\nB\n\nC",
            "source_map": {
                "separator": "\n\n",
                "focus_start_row_index": 1,
                "focus_end_row_index": 1,
                "focus_row_indices": [1],
                "rows": [
                    {
                        "row_id": "row-0",
                        "row_index": 0,
                        "block_index": 0,
                        "text": "A",
                        "segment_start": 0,
                        "segment_end": 1,
                    },
                    {
                        "row_id": "row-1",
                        "row_index": 1,
                        "block_index": 1,
                        "text": "B",
                        "segment_start": 3,
                        "segment_end": 4,
                    },
                    {
                        "row_id": "row-2",
                        "row_index": 2,
                        "block_index": 2,
                        "text": "C",
                        "segment_start": 6,
                        "segment_end": 7,
                    },
                ],
            },
        },
    }
    provider = _CaptureProvider(
        '[{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "B"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "<<<CONTEXT_BEFORE_LABELING_ONLY>>>" in prompt
    assert "<<<START_LABELING_ROWS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>" in prompt
    assert "<<<CONTEXT_AFTER_LABELING_ONLY>>>" in prompt


def test_prelabel_span_prompt_reads_context_blocks_for_focus_only_segment() -> None:
    task = {
        "id": 301,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:2",
            "segment_text": "B",
            "source_map": {
                "separator": "\n\n",
                "focus_start_row_index": 1,
                "focus_end_row_index": 1,
                "focus_row_indices": [1],
                "context_before_rows": [{"row_index": 0, "block_index": 0, "text": "A"}],
                "context_after_rows": [{"row_index": 2, "block_index": 2, "text": "C"}],
                "rows": [
                    {
                        "row_id": "row-1",
                        "row_index": 1,
                        "block_index": 1,
                        "text": "B",
                        "segment_start": 0,
                        "segment_end": 1,
                    }
                ],
            },
        },
    }
    provider = _CaptureProvider(
        '[{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "B"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    value = annotation["result"][0]["value"]
    assert value["start"] == 0
    assert value["end"] == 1
    assert value["text"] == "B"

    prompt = provider.prompts[0]
    assert "<<<CONTEXT_BEFORE_LABELING_ONLY>>>" in prompt
    assert "<<<START_LABELING_ROWS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>" in prompt
    assert "<<<CONTEXT_AFTER_LABELING_ONLY>>>" in prompt
    assert "0\tA" in prompt
    assert "1\tB" in prompt
    assert "2\tC" in prompt


def test_prelabel_prompt_log_callback_captures_prompt_context() -> None:
    task = _freeform_task()
    provider = _StaticProvider(
        '[{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )
    prompt_logs: list[dict[str, object]] = []

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prompt_log_callback=prompt_logs.append,
        prelabel_granularity="span",
    )

    assert annotation is not None
    assert len(prompt_logs) == 1
    entry = prompt_logs[0]
    assert entry["segment_id"] == "urn:cookimport:segment:testhash:0:1"
    assert entry["prompt_template"] == "freeform-prelabel-span.prompt.md"
    assert "Segment id: urn:cookimport:segment:testhash:0:1" in entry["prompt"]
    included = entry["included_with_prompt"]
    assert included["focus_row_indices"] == [0, 1]
    assert included["segment_row_count"] == 2
    assert included["context_before_row_count"] == 0
    assert included["context_after_row_count"] == 0
    assert included["allowed_labels"][0] == "RECIPE_TITLE"
    assert "Prompt includes allowed labels" in entry["included_with_prompt_description"]


def test_prelabel_span_mode_filters_out_of_focus_rows() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_row_index"] = 1
    task["data"]["source_map"]["focus_end_row_index"] = 1
    task["data"]["source_map"]["focus_row_indices"] = [1]
    provider = _StaticProvider(
        '[{"row_index": 0, "label": "YIELD_LINE", "quote": "Serves 4"}, '
        '{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    results = annotation["result"]
    assert len(results) == 1
    value = results[0]["value"]
    assert value["labels"] == ["INGREDIENT_LINE"]
    assert value["start"] == 10
    assert value["end"] == 21


def test_prelabel_span_mode_drops_absolute_spans_outside_focus() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_row_index"] = 1
    task["data"]["source_map"]["focus_end_row_index"] = 1
    task["data"]["source_map"]["focus_row_indices"] = [1]
    provider = _StaticProvider(
        '[{"label": "YIELD_LINE", "start": 0, "end": 21}, '
        '{"row_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    results = annotation["result"]
    assert len(results) == 1
    value = results[0]["value"]
    assert value["labels"] == ["INGREDIENT_LINE"]
    assert value["text"] == "1 cup flour"


def test_prelabel_prompt_uses_file_templates(monkeypatch, tmp_path: Path) -> None:
    assert str(prelabel_module._PROMPT_TEMPLATE_DIR).endswith("llm_pipelines/prompts")
    span_path = tmp_path / "freeform-prelabel-span.prompt.md"
    span_path.write_text(
        "SPAN {{SEGMENT_ID}} | {{ALLOWED_LABELS}}\n{{ROWS_JSON_LINES}}",
        encoding="utf-8",
    )
    prelabel_module._PROMPT_TEMPLATE_CACHE.clear()
    monkeypatch.setattr(prelabel_module, "_SPAN_PROMPT_TEMPLATE_PATH", span_path)

    task = _freeform_task()
    span_provider = _CaptureProvider(
        '[{"row_index": 0, "label": "YIELD_LINE", "quote": "Serves 4"}]'
    )
    span_annotation = prelabel_freeform_task(
        task,
        provider=span_provider,
        prelabel_granularity="span",
    )
    assert span_annotation is not None
    assert "SPAN urn:cookimport:segment:testhash:0:1" in span_provider.prompts[0]
    assert '{"row_index": 0, "text": "Serves 4"}' in span_provider.prompts[0]
