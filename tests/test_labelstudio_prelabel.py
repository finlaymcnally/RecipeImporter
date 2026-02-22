from __future__ import annotations

import json
from pathlib import Path

from cookimport.labelstudio.ingest import run_labelstudio_decorate
from cookimport.labelstudio.prelabel import (
    annotation_is_cookimport_augment,
    merge_annotation_results,
    parse_block_label_output,
    prelabel_freeform_task,
)


class _StaticProvider:
    def __init__(self, response: str) -> None:
        self._response = response

    def complete(self, _prompt: str) -> str:
        return self._response


def _freeform_task() -> dict[str, object]:
    return {
        "id": 100,
        "data": {
            "segment_id": "urn:cookimport:segment:testhash:0:1",
            "segment_text": "Serves 4\n\n1 cup flour",
            "source_map": {
                "separator": "\n\n",
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


def test_parse_block_label_output_extracts_embedded_json() -> None:
    raw = (
        "Here is the answer:\n"
        '[{"block_index": 0, "label": "YIELD"}, {"block_index": 1, "label": "time"}]\n'
        "done."
    )
    parsed = parse_block_label_output(raw)
    assert parsed == [
        {"block_index": 0, "label": "YIELD_LINE"},
        {"block_index": 1, "label": "TIME_LINE"},
    ]


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


def test_merge_annotation_results_dedupes_exact_matches() -> None:
    base = [
        {
            "value": {
                "start": 0,
                "end": 8,
                "labels": ["YIELD_LINE"],
            }
        }
    ]
    additions = [
        {
            "value": {
                "start": 0,
                "end": 8,
                "labels": ["YIELD_LINE"],
            }
        },
        {
            "value": {
                "start": 10,
                "end": 21,
                "labels": ["INGREDIENT_LINE"],
            }
        },
    ]

    merged = merge_annotation_results(base, additions)
    assert len(merged) == 2


def test_annotation_is_cookimport_augment_checks_added_labels() -> None:
    annotation = {
        "meta": {
            "cookimport_prelabel": True,
            "mode": "augment",
            "added_labels": ["YIELD_LINE", "TIME_LINE"],
        }
    }
    assert annotation_is_cookimport_augment(
        annotation, requested_labels={"YIELD_LINE"}
    )
    assert not annotation_is_cookimport_augment(
        annotation, requested_labels={"INGREDIENT_LINE"}
    )


def test_run_labelstudio_decorate_dry_run(monkeypatch, tmp_path: Path) -> None:
    task = _freeform_task()
    task["annotations"] = [
        {
            "id": 1,
            "result": [
                {
                    "id": "base-1",
                    "from_name": "span_labels",
                    "to_name": "segment_text",
                    "type": "labels",
                    "value": {
                        "start": 10,
                        "end": 21,
                        "text": "1 cup flour",
                        "labels": ["INGREDIENT_LINE"],
                    },
                }
            ],
        }
    ]
    already_done = _freeform_task()
    already_done["id"] = 200
    already_done["data"]["segment_id"] = "urn:cookimport:segment:testhash:2:3"
    already_done["annotations"] = [
        {
            "id": 4,
            "meta": {
                "cookimport_prelabel": True,
                "mode": "augment",
                "added_labels": ["YIELD_LINE", "TIME_LINE"],
            },
            "result": [],
        }
    ]

    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, _title: str) -> dict[str, object]:
            return {"id": 10, "title": "test"}

        def list_project_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return [task, already_done]

        def create_annotation(self, *_args, **_kwargs):
            raise AssertionError("create_annotation should not be called in dry-run mode")

    provider = _StaticProvider('[{"block_index": 0, "label": "YIELD_LINE"}]')
    monkeypatch.setattr("cookimport.labelstudio.ingest.LabelStudioClient", FakeClient)
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_prelabel_provider",
        lambda **_kwargs: provider,
    )

    result = run_labelstudio_decorate(
        project_name="test",
        output_dir=tmp_path,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        add_labels={"YIELD_LINE", "TIME_LINE"},
        no_write=True,
    )

    report = json.loads(result["report_path"].read_text(encoding="utf-8"))
    assert report["counts"]["tasks_total"] == 2
    assert report["counts"]["dry_run_would_create"] == 1
    assert report["counts"]["skipped_already_decorated"] == 1
