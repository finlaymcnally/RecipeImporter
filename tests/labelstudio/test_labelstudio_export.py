import json

import pytest

from cookimport.labelstudio.export import (
    _infer_scope_from_project_payload,
    _select_annotation,
    run_labelstudio_export,
)


def test_select_annotation_latest() -> None:
    task = {
        "annotations": [
            {"id": 1, "result": [{"value": {"labels": ["INGREDIENT_LINE"]}}]},
            {"id": 2, "result": [{"value": {"labels": ["RECIPE_TITLE"]}}]},
        ]
    }
    selected = _select_annotation(task)
    assert selected is not None
    assert selected["id"] == 2


def test_infer_scope_from_project_payload_detects_known_scopes() -> None:
    assert (
        _infer_scope_from_project_payload(
            {"label_config": "<View><Label value='RECIPE_VARIANT'/></View>"}
        )
        == "freeform-spans"
    )
    assert (
        _infer_scope_from_project_payload(
            {"label_config": "<View><Choices name='mixed'><Choice value='x'/></Choices><Choices name='value_usefulness'/></View>"}
        )
        == "pipeline"
    )


@pytest.mark.parametrize("legacy_scope", ["pipeline", "canonical-blocks"])
def test_export_rejects_legacy_scope_from_manifest(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_scope: str,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            return None

        def find_project_by_title(self, title: str) -> dict[str, object]:
            return {"id": 9, "title": title}

        def export_tasks(self, _project_id: int) -> list[dict[str, object]]:
            return []

    run_root = tmp_path / "2026-02-25_22.45.00" / "labelstudio" / "book"
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "manifest.json").write_text(
        json.dumps(
            {
                "project_name": "Legacy Project",
                "project_id": 9,
                "task_scope": legacy_scope,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("cookimport.labelstudio.export.LabelStudioClient", FakeClient)

    with pytest.raises(RuntimeError, match="supports freeform-spans projects only"):
        run_labelstudio_export(
            project_name="Legacy Project",
            output_dir=tmp_path,
            label_studio_url="http://localhost:8080",
            label_studio_api_key="token",
            run_dir=run_root,
        )
