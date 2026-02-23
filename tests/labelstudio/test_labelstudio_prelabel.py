from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import cookimport.labelstudio.prelabel as prelabel_module
from cookimport.labelstudio.prelabel import (
    CodexCliProvider,
    codex_account_summary,
    codex_cmd_with_model,
    codex_cmd_with_reasoning_effort,
    default_codex_model,
    default_codex_cmd,
    default_codex_reasoning_effort,
    codex_reasoning_effort_from_cmd,
    list_codex_models,
    is_rate_limit_message,
    parse_block_label_output,
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
                "focus_start_block_index": 0,
                "focus_end_block_index": 1,
                "focus_block_indices": [0, 1],
                "blocks": [
                    {
                        "block_id": "urn:cookimport:block:testhash:0",
                        "block_index": 0,
                        "segment_start": 0,
                        "segment_end": 8,
                    },
                    {
                        "block_id": "urn:cookimport:block:testhash:1",
                        "block_index": 1,
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
                "focus_start_block_index": 5,
                "focus_end_block_index": 5,
                "focus_block_indices": [5],
                "blocks": [
                    {
                        "block_id": "urn:cookimport:block:testhash:5",
                        "block_index": 5,
                        "segment_start": 0,
                        "segment_end": len(text),
                    }
                ],
            },
        },
    }


def test_parse_block_label_output_extracts_embedded_json() -> None:
    raw = (
        "Here is the answer:\n"
        '[{"block_index": 0, "label": "YIELD"}, '
        '{"block_index": 1, "label": "time"}, '
        '{"block_index": 2, "label": "TIP"}, '
        '{"block_index": 3, "label": "notes"}, '
        '{"block_index": 4, "label": "variant"}]\n'
        "done."
    )
    parsed = parse_block_label_output(raw)
    assert parsed == [
        {"block_index": 0, "label": "YIELD_LINE"},
        {"block_index": 1, "label": "TIME_LINE"},
        {"block_index": 2, "label": "KNOWLEDGE"},
        {"block_index": 3, "label": "RECIPE_NOTES"},
        {"block_index": 4, "label": "RECIPE_VARIANT"},
    ]


def test_parse_span_label_output_extracts_quote_and_absolute_items() -> None:
    raw = (
        "extra text\n"
        '[{"block_index": 5, "label": "time", "quote": "Prep 10 min"},'
        '{"block_index": 5, "label": "yield", "quote": "Serves 4", "occurrence": 1},'
        '{"label": "notes", "start": 2, "end": 8}]'
    )
    parsed = parse_span_label_output(raw)
    assert parsed == [
        {
            "kind": "quote",
            "block_index": 5,
            "label": "TIME_LINE",
            "quote": "Prep 10 min",
            "occurrence": None,
        },
        {
            "kind": "quote",
            "block_index": 5,
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


def test_prelabel_freeform_task_uses_block_offsets_and_exact_text() -> None:
    task = _freeform_task()
    provider = _StaticProvider(
        '[{"block_index": 0, "label": "YIELD_LINE"}, {"block_index": 1, "label": "INGREDIENT_LINE"}]'
    )

    annotation = prelabel_freeform_task(task, provider=provider)
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
        '[{"block_index": 5, "label": "YIELD_LINE", "quote": "Serves 4"},'
        '{"block_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min"}]'
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


def test_span_resolution_requires_occurrence_for_ambiguous_quote() -> None:
    task = _single_block_task("Prep 10 min; Prep 10 min")

    ambiguous_provider = _StaticProvider(
        '[{"block_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min"}]'
    )
    ambiguous_annotation = prelabel_freeform_task(
        task,
        provider=ambiguous_provider,
        prelabel_granularity="span",
    )
    assert ambiguous_annotation is None

    disambiguated_provider = _StaticProvider(
        '[{"block_index": 5, "label": "TIME_LINE", "quote": "Prep 10 min", "occurrence": 2}]'
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


def test_prelabel_full_prompt_uses_ai_instruction_template() -> None:
    task = _freeform_task()
    provider = _CaptureProvider(
        '[{"block_index": 0, "label": "YIELD_LINE"}, {"block_index": 1, "label": "INGREDIENT_LINE"}]'
    )

    annotation = prelabel_freeform_task(task, provider=provider)
    assert annotation is not None
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "Segment id: urn:cookimport:segment:testhash:0:1" in prompt
    assert '{"block_index": 0, "text": "Serves 4"}' in prompt
    assert '{"block_index": 1, "text": "1 cup flour"}' in prompt


def test_prelabel_prompt_includes_focus_scope() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_block_index"] = 1
    task["data"]["source_map"]["focus_end_block_index"] = 1
    task["data"]["source_map"]["focus_block_indices"] = [1]
    provider = _CaptureProvider('[{"block_index": 1, "label": "INGREDIENT_LINE"}]')

    annotation = prelabel_freeform_task(task, provider=provider)
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "Focus blocks to label (context blocks may be broader):" in prompt
    assert '{"block_index": 1, "text": "1 cup flour"}' in prompt


def test_prelabel_span_prompt_marks_focus_window_without_block_duplication() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_block_index"] = 1
    task["data"]["source_map"]["focus_end_block_index"] = 1
    task["data"]["source_map"]["focus_block_indices"] = [1]
    provider = _CaptureProvider(
        '[{"block_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "Focus block indices (for quick reference):" not in prompt
    assert "<<<START_LABELING_BLOCKS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>" in prompt
    blocks_section = prompt.split(
        "Blocks (single pass with explicit context-before / focus / context-after markers):", 1
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
                "focus_start_block_index": 1,
                "focus_end_block_index": 1,
                "focus_block_indices": [1],
                "blocks": [
                    {
                        "block_id": "urn:cookimport:block:testhash:0",
                        "block_index": 0,
                        "segment_start": 0,
                        "segment_end": 1,
                    },
                    {
                        "block_id": "urn:cookimport:block:testhash:1",
                        "block_index": 1,
                        "segment_start": 3,
                        "segment_end": 4,
                    },
                    {
                        "block_id": "urn:cookimport:block:testhash:2",
                        "block_index": 2,
                        "segment_start": 6,
                        "segment_end": 7,
                    },
                ],
            },
        },
    }
    provider = _CaptureProvider(
        '[{"block_index": 1, "label": "INGREDIENT_LINE", "quote": "B"}]'
    )

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prelabel_granularity="span",
    )
    assert annotation is not None
    prompt = provider.prompts[0]
    assert "<<<CONTEXT_BEFORE_LABELING_ONLY>>>" in prompt
    assert "<<<START_LABELING_BLOCKS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>" in prompt
    assert "<<<CONTEXT_AFTER_LABELING_ONLY>>>" in prompt


def test_prelabel_span_prompt_reads_context_blocks_for_focus_only_segment() -> None:
    task = {
        "id": 301,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:2",
            "segment_text": "B",
            "source_map": {
                "separator": "\n\n",
                "focus_start_block_index": 1,
                "focus_end_block_index": 1,
                "focus_block_indices": [1],
                "context_before_blocks": [{"block_index": 0, "text": "A"}],
                "context_after_blocks": [{"block_index": 2, "text": "C"}],
                "blocks": [
                    {
                        "block_id": "urn:cookimport:block:testhash:1",
                        "block_index": 1,
                        "segment_start": 0,
                        "segment_end": 1,
                    }
                ],
            },
        },
    }
    provider = _CaptureProvider(
        '[{"block_index": 1, "label": "INGREDIENT_LINE", "quote": "B"}]'
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
    assert "<<<START_LABELING_BLOCKS_HERE>>>" in prompt
    assert "<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>" in prompt
    assert "<<<CONTEXT_AFTER_LABELING_ONLY>>>" in prompt
    assert "0\tA" in prompt
    assert "1\tB" in prompt
    assert "2\tC" in prompt


def test_prelabel_prompt_log_callback_captures_prompt_context() -> None:
    task = _freeform_task()
    provider = _StaticProvider('[{"block_index": 1, "label": "INGREDIENT_LINE"}]')
    prompt_logs: list[dict[str, object]] = []

    annotation = prelabel_freeform_task(
        task,
        provider=provider,
        prompt_log_callback=prompt_logs.append,
    )

    assert annotation is not None
    assert len(prompt_logs) == 1
    entry = prompt_logs[0]
    assert entry["segment_id"] == "urn:cookimport:segment:testhash:0:1"
    assert entry["prompt_template"] == "freeform-prelabel-full.prompt.md"
    assert "Segment id: urn:cookimport:segment:testhash:0:1" in entry["prompt"]
    included = entry["included_with_prompt"]
    assert included["focus_block_indices"] == [0, 1]
    assert included["segment_block_count"] == 2
    assert included["context_before_block_count"] == 0
    assert included["context_after_block_count"] == 0
    assert included["allowed_labels"][0] == "RECIPE_TITLE"
    assert "Prompt includes allowed labels" in entry["included_with_prompt_description"]


def test_prelabel_block_mode_filters_out_of_focus_blocks() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_block_index"] = 1
    task["data"]["source_map"]["focus_end_block_index"] = 1
    task["data"]["source_map"]["focus_block_indices"] = [1]
    provider = _StaticProvider(
        '[{"block_index": 0, "label": "YIELD_LINE"}, {"block_index": 1, "label": "INGREDIENT_LINE"}]'
    )

    annotation = prelabel_freeform_task(task, provider=provider)
    assert annotation is not None
    results = annotation["result"]
    assert len(results) == 1
    value = results[0]["value"]
    assert value["labels"] == ["INGREDIENT_LINE"]
    assert value["start"] == 10
    assert value["end"] == 21


def test_prelabel_span_mode_drops_absolute_spans_outside_focus() -> None:
    task = _freeform_task()
    task["data"]["source_map"]["focus_start_block_index"] = 1
    task["data"]["source_map"]["focus_end_block_index"] = 1
    task["data"]["source_map"]["focus_block_indices"] = [1]
    provider = _StaticProvider(
        '[{"label": "YIELD_LINE", "start": 0, "end": 21}, '
        '{"block_index": 1, "label": "INGREDIENT_LINE", "quote": "1 cup flour"}]'
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
    full_path = tmp_path / "freeform-prelabel-full.prompt.md"
    span_path = tmp_path / "freeform-prelabel-span.prompt.md"
    full_path.write_text(
        "FULL {{SEGMENT_ID}} | {{ALLOWED_LABELS}} | {{UNCERTAINTY_HINT}}\n{{BLOCKS_JSON_LINES}}",
        encoding="utf-8",
    )
    span_path.write_text(
        "SPAN {{SEGMENT_ID}} | {{ALLOWED_LABELS}}\n{{BLOCKS_JSON_LINES}}",
        encoding="utf-8",
    )
    prelabel_module._PROMPT_TEMPLATE_CACHE.clear()
    monkeypatch.setattr(prelabel_module, "_FULL_PROMPT_TEMPLATE_PATH", full_path)
    monkeypatch.setattr(prelabel_module, "_SPAN_PROMPT_TEMPLATE_PATH", span_path)

    task = _freeform_task()
    full_provider = _CaptureProvider('[{"block_index": 0, "label": "YIELD_LINE"}]')
    full_annotation = prelabel_freeform_task(task, provider=full_provider)
    assert full_annotation is not None
    assert "FULL urn:cookimport:segment:testhash:0:1" in full_provider.prompts[0]
    assert '{"block_index": 0, "text": "Serves 4"}' in full_provider.prompts[0]

    span_provider = _CaptureProvider(
        '[{"block_index": 0, "label": "YIELD_LINE", "quote": "Serves 4"}]'
    )
    span_annotation = prelabel_freeform_task(
        task,
        provider=span_provider,
        prelabel_granularity="span",
    )
    assert span_annotation is not None
    assert "SPAN urn:cookimport:segment:testhash:0:1" in span_provider.prompts[0]


def test_default_codex_cmd_uses_noninteractive_exec(monkeypatch) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_CMD", raising=False)
    assert default_codex_cmd() == "codex exec -"


def test_default_codex_cmd_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("COOKIMPORT_CODEX_CMD", "codex2 exec -")
    assert default_codex_cmd() == "codex2 exec -"


def test_codex_provider_retries_plain_codex_with_exec(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Error: stdin is not a terminal",
            )
        return SimpleNamespace(
            returncode=0,
            stdout='[{"block_index": 0, "label": "OTHER"}]',
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(cmd="codex", timeout_s=10, cache_dir=tmp_path)
    response = provider.complete("label this")

    assert response == '[{"block_index": 0, "label": "OTHER"}]'
    assert calls == [["codex"], ["codex", "exec", "-"]]


def test_codex_provider_tracks_usage_from_json_events(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"[{\\"block_index\\": 0, \\"label\\": \\"OTHER\\"}]"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":7,"output_tokens":3}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(
        cmd="codex exec -",
        timeout_s=10,
        cache_dir=tmp_path,
        track_usage=True,
    )

    response = provider.complete("label this")
    usage = provider.usage_summary()

    assert response == '[{"block_index": 0, "label": "OTHER"}]'
    assert calls == [["codex", "exec", "--json", "-"]]
    assert usage["input_tokens"] == 11
    assert usage["cached_input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["reasoning_tokens"] == 0
    assert usage["calls_with_usage"] == 1
    assert usage["calls_total"] == 1


def test_codex_provider_tracks_reasoning_tokens_from_nested_usage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def _fake_run(argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"[{\\"block_index\\": 0, \\"label\\": \\"OTHER\\"}]"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":7,"output_tokens":3,"output_tokens_details":{"reasoning_tokens":9}}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(
        cmd="codex exec -",
        timeout_s=10,
        cache_dir=tmp_path,
        track_usage=True,
    )

    provider.complete("label this")
    usage = provider.usage_summary()

    assert usage["input_tokens"] == 11
    assert usage["cached_input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["reasoning_tokens"] == 9
    assert usage["calls_with_usage"] == 1
    assert usage["calls_total"] == 1


def test_codex_cmd_with_model_injects_model_for_exec() -> None:
    assert (
        codex_cmd_with_model("codex exec -", "gpt-5.3-codex")
        == "codex exec --model gpt-5.3-codex -"
    )
    assert (
        codex_cmd_with_model("codex2 exec -", "gpt-5.3-codex")
        == "codex2 exec --model gpt-5.3-codex -"
    )
    assert (
        codex_cmd_with_model("codex exec --model gpt-5.3-codex -", "gpt-5-codex")
        == "codex exec --model gpt-5.3-codex -"
    )


def test_codex_cmd_with_reasoning_effort_injects_config_for_exec() -> None:
    assert (
        codex_cmd_with_reasoning_effort("codex exec -", "high")
        == "codex exec -c 'model_reasoning_effort=\"high\"' -"
    )
    assert (
        codex_cmd_with_reasoning_effort("codex2 exec -", "xhigh")
        == "codex2 exec -c 'model_reasoning_effort=\"xhigh\"' -"
    )
    assert (
        codex_cmd_with_reasoning_effort(
            'codex exec -c model_reasoning_effort="low" -',
            "high",
        )
        == 'codex exec -c model_reasoning_effort="low" -'
    )


def test_codex_reasoning_effort_from_cmd_reads_config_override() -> None:
    assert (
        codex_reasoning_effort_from_cmd(
            'codex exec -c model_reasoning_effort="medium" -'
        )
        == "medium"
    )
    assert (
        codex_reasoning_effort_from_cmd(
            "codex exec --config 'model_reasoning_effort=\"xhigh\"' -"
        )
        == "xhigh"
    )


def test_default_codex_model_reads_codex_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config_dir = tmp_path / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-test-codex"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model() == "gpt-test-codex"


def test_default_codex_model_prefers_codex_over_codex_alt(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    codex_dir = tmp_path / ".codex"
    codex_alt_dir = tmp_path / ".codex-alt"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_alt_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex-primary"\n',
        encoding="utf-8",
    )
    (codex_alt_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex-alt"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model() == "gpt-codex-primary"


def test_default_codex_model_reads_command_specific_codex_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".codex2").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codex2" / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex2-default"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model(cmd="codex2 exec -") == "gpt-codex2-default"


def test_default_codex_reasoning_effort_reads_codex_config(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config_dir = tmp_path / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel_reasoning_effort = "high"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_reasoning_effort() == "high"


def test_list_codex_models_reads_models_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom_codex"))
    custom_root = tmp_path / "custom_codex"
    custom_root.mkdir(parents=True, exist_ok=True)
    (custom_root / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex",
                        "display_name": "gpt-5.3-codex",
                        "description": "Latest coding model",
                        "visibility": "list",
                    },
                    {
                        "slug": "private-model",
                        "display_name": "private-model",
                        "description": "hidden",
                        "visibility": "hidden",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)

    models = list_codex_models()

    assert models == [
        {
            "slug": "gpt-5.3-codex",
            "display_name": "gpt-5.3-codex",
            "description": "Latest coding model",
        }
    ]


def test_list_codex_models_reads_command_specific_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".codex2").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codex2" / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-pro",
                        "display_name": "gpt-5.3-codex-pro",
                        "description": "Pro model",
                        "visibility": "list",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    models = list_codex_models(cmd="codex2 exec -")
    assert models == [
        {
            "slug": "gpt-5.3-codex-pro",
            "display_name": "gpt-5.3-codex-pro",
            "description": "Pro model",
        }
    ]


def test_codex_account_summary_reads_email_from_command_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claims = {
        "email": "pro-account@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    token = f"header.{encoded.rstrip('=')}.signature"
    auth_path = tmp_path / ".codex2" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": token, "access_token": token},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert codex_account_summary("codex2 exec -") == "pro-account@example.com (pro)"


def test_codex_account_summary_prefers_codex_over_codex_alt(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    primary_claims = {
        "email": "primary@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
    }
    alt_claims = {
        "email": "alt@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    primary_token = (
        "header."
        + base64.urlsafe_b64encode(json.dumps(primary_claims).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        + ".signature"
    )
    alt_token = (
        "header."
        + base64.urlsafe_b64encode(json.dumps(alt_claims).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        + ".signature"
    )
    primary_auth = tmp_path / ".codex" / "auth.json"
    alt_auth = tmp_path / ".codex-alt" / "auth.json"
    primary_auth.parent.mkdir(parents=True, exist_ok=True)
    alt_auth.parent.mkdir(parents=True, exist_ok=True)
    primary_auth.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": primary_token, "access_token": primary_token},
            }
        ),
        encoding="utf-8",
    )
    alt_auth.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": alt_token, "access_token": alt_token},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert codex_account_summary("codex exec -") == "primary@example.com (pro)"


def test_preflight_codex_model_access_raises_on_turn_failed(monkeypatch) -> None:
    def _fake_run(_argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"turn.started"}\n'
                '{"type":"turn.failed","error":{"message":"{\\"detail\\":\\"Model not supported\\"}"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)

    try:
        preflight_codex_model_access(cmd="codex exec -", timeout_s=5)
        raise AssertionError("expected preflight failure")
    except RuntimeError as exc:
        assert "Model not supported" in str(exc)


def test_codex_provider_raises_turn_failed_message(monkeypatch, tmp_path: Path) -> None:
    def _fake_run(_argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"turn.started"}\n'
                '{"type":"turn.failed","error":{"message":"{\\"detail\\":\\"Model denied\\"}"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(cmd="codex exec -", timeout_s=5, cache_dir=tmp_path)

    try:
        provider.complete("label this")
        raise AssertionError("expected provider failure")
    except RuntimeError as exc:
        assert "Model denied" in str(exc)
