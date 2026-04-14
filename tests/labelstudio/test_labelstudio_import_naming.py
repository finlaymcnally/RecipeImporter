from pathlib import Path
from typing import cast

from cookimport.labelstudio.client import LabelStudioClient
from cookimport.labelstudio.ingest_support import (
    _dedupe_project_name,
    _resolve_project_name,
)


def test_dedupe_project_name_adds_incrementing_suffix() -> None:
    existing = {"the_food_lab", "the_food_lab-1", "other"}
    assert _dedupe_project_name("the_food_lab", existing) == "the_food_lab-2"


def test_resolve_project_name_uses_explicit_name_without_lookup() -> None:
    class FakeClient:
        def list_projects(self) -> list[dict[str, object]]:
            raise AssertionError("list_projects should not be called for explicit names")

    resolved = _resolve_project_name(
        Path("data/input/the_food_lab.epub"),
        "Manual Project",
        cast(LabelStudioClient, FakeClient()),
    )
    assert resolved == "Manual Project"


def test_resolve_project_name_defaults_to_file_stem_and_dedupes() -> None:
    class FakeClient:
        def list_projects(self) -> list[dict[str, object]]:
            return [
                {"title": "the_food_lab"},
                {"title": "the_food_lab-1"},
                {"title": "Unrelated"},
            ]

    resolved = _resolve_project_name(
        Path("data/input/the_food_lab.epub"),
        None,
        cast(LabelStudioClient, FakeClient()),
    )
    assert resolved == "the_food_lab-2"


def test_list_project_tasks_uses_project_scoped_endpoint(monkeypatch) -> None:
    client = LabelStudioClient("http://localhost:8080", "token")
    calls: list[str] = []

    def fake_request_json(method: str, path: str, payload=None):
        calls.append(f"{method} {path}")
        return {"results": [{"id": 1, "data": {"segment_id": "seg-1"}}], "next": None}

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    tasks = client.list_project_tasks(123)

    assert tasks == [{"id": 1, "data": {"segment_id": "seg-1"}}]
    assert calls == ["GET /api/projects/123/tasks?page=1&page_size=100"]


def test_list_project_tasks_falls_back_to_legacy_query_on_runtime_error(monkeypatch) -> None:
    client = LabelStudioClient("http://localhost:8080", "token")
    calls: list[str] = []

    def fake_request_json(method: str, path: str, payload=None):
        calls.append(f"{method} {path}")
        if path.startswith("/api/projects/123/tasks?"):
            raise RuntimeError("project-scoped endpoint unavailable")
        return {"results": [{"id": 2, "data": {"segment_id": "seg-2"}}], "next": None}

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    tasks = client.list_project_tasks(123)

    assert tasks == [{"id": 2, "data": {"segment_id": "seg-2"}}]
    assert calls == [
        "GET /api/projects/123/tasks?page=1&page_size=100",
        "GET /api/tasks?project=123&page=1&page_size=100",
    ]


def test_update_project_uses_patch(monkeypatch) -> None:
    client = LabelStudioClient("http://localhost:8080", "token")
    calls: list[tuple[str, str, object]] = []

    def fake_request_json(method: str, path: str, payload=None):
        calls.append((method, path, payload))
        return {"id": 123, "show_annotation_history": True}

    monkeypatch.setattr(client, "_request_json", fake_request_json)

    updated = client.update_project(123, {"show_annotation_history": True})

    assert updated == {"id": 123, "show_annotation_history": True}
    assert calls == [
        ("PATCH", "/api/projects/123", {"show_annotation_history": True})
    ]
