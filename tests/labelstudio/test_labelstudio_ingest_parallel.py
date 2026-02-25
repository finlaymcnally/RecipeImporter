from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from cookimport.core.progress_messages import parse_worker_activity
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    RawArtifact,
    RecipeCandidate,
)
from cookimport.labelstudio.ingest import (
    _acquire_split_phase_slot,
    _normalize_llm_recipe_pipeline,
    generate_pred_run_artifacts,
    _merge_parallel_results,
    _plan_parallel_convert_jobs,
    run_labelstudio_import,
)
from cookimport.labelstudio.models import ArchiveBlock


def test_llm_recipe_pipeline_normalizer_rejects_codex_farm_enablement() -> None:
    with pytest.raises(ValueError, match="TURNED OFF"):
        _normalize_llm_recipe_pipeline("codex-farm-3pass-v1")


def test_plan_parallel_convert_jobs_pdf_splits(monkeypatch) -> None:
    path = Path("sample.pdf")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_pdf_page_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=4,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
    )

    assert len(jobs) == 3
    assert jobs[0]["start_page"] == 0
    assert jobs[1]["start_page"] == 40
    assert jobs[2]["start_page"] == 80
    assert jobs[0]["start_spine"] is None


def test_plan_parallel_convert_jobs_epub_markitdown_disables_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="markitdown",
    )

    assert len(jobs) == 1
    assert jobs[0]["start_spine"] is None
    assert jobs[0]["end_spine"] is None


def test_plan_parallel_convert_jobs_epub_unstructured_uses_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = _plan_parallel_convert_jobs(
        path,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="unstructured",
    )

    assert len(jobs) > 1
    assert jobs[0]["start_spine"] == 0
    assert jobs[-1]["end_spine"] == 120


def test_split_phase_slot_gate_emits_wait_acquire_release(
    monkeypatch, tmp_path: Path
) -> None:
    gate_dir = tmp_path / "split-slot-gate"
    messages: list[str] = []
    attempts = {"count": 0}

    def fake_try_lock(_handle) -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 3

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._try_acquire_file_lock_nonblocking",
        fake_try_lock,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.time.sleep", lambda *_: None)

    with _acquire_split_phase_slot(
        slots=2,
        gate_dir=gate_dir,
        notify=messages.append,
        status_label="Config 1/4",
    ):
        pass

    assert any("waiting for split slot" in message for message in messages)
    assert any("acquired split slot" in message for message in messages)
    assert any("released split slot" in message for message in messages)


def test_merge_parallel_results_combines_and_reorders(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_text("source", encoding="utf-8")

    job_a = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Later",
                identifier="old-later",
                provenance={"location": {"start_page": 9, "start_block": 20}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-a",
                location_id="loc-a",
                extension="json",
                content={
                    "block_count": 3,
                    "blocks": [
                        {"index": 0, "text": "a"},
                        {"index": 1, "text": "b"},
                        {"index": 2, "text": "c"},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    job_b = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Earlier",
                identifier="old-earlier",
                provenance={"location": {"start_page": 1, "start_block": 1}},
            )
        ],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[
            RawArtifact(
                importer="pdf",
                source_hash="hash-b",
                location_id="loc-b",
                extension="json",
                content={
                    "block_count": 2,
                    "blocks": [
                        {"index": 0, "text": "x"},
                        {"index": 1, "text": "y"},
                    ],
                },
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    merged = _merge_parallel_results(
        source,
        "pdf",
        [
            {"job_index": 1, "start_page": 8, "result": job_a},
            {"job_index": 0, "start_page": 0, "result": job_b},
        ],
    )

    assert len(merged.recipes) == 2
    assert merged.recipes[0].name == "Earlier"
    assert merged.recipes[1].name == "Later"
    assert merged.recipes[0].identifier != "old-earlier"
    assert merged.recipes[1].identifier != "old-later"
    assert merged.recipes[1].provenance["location"]["start_block"] == 22
    assert len(merged.raw_artifacts) == 2
    shifted = next(artifact for artifact in merged.raw_artifacts if artifact.source_hash == "hash-a")
    shifted_indices = [block["index"] for block in shifted.content["blocks"]]
    assert shifted_indices == [2, 3, 4]


def test_run_labelstudio_import_emits_post_merge_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    class FakeLabelStudioClient:
        uploaded_batches: list[int] = []

        def __init__(self, _url: str, _key: str) -> None:
            pass

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks):
            self.uploaded_batches.append(len(tasks))

    monkeypatch.setattr("cookimport.labelstudio.ingest.registry.get_importer", lambda _name: FakeImporter())
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [{"job_index": 0, "start_page": None, "end_page": None, "start_spine": None, "end_spine": None}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(401)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.LabelStudioClient", FakeLabelStudioClient)

    progress_messages: list[str] = []
    run_labelstudio_import(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        project_name="benchmark project",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="test",
        limit=None,
        sample=None,
        progress_callback=progress_messages.append,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        processed_output_root=processed_root,
        allow_labelstudio_write=True,
    )

    assert "Building extracted archive..." in progress_messages
    assert "Writing processed cookbook outputs..." in progress_messages
    assert "Building freeform span tasks..." in progress_messages
    assert "Uploading 401 task(s) in 3 batch(es)..." in progress_messages
    assert "Uploaded 401/401 task(s)." in progress_messages
    assert progress_messages[-1] == "Label Studio import artifacts complete."


def test_run_labelstudio_import_split_workers_emit_worker_activity(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    class FakeLabelStudioClient:
        uploaded_batches: list[int] = []

        def __init__(self, _url: str, _key: str) -> None:
            pass

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(
            self, title: str, _label_config: str, description: str | None = None
        ):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks):
            self.uploaded_batches.append(len(tasks))

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [
            {
                "job_index": 0,
                "start_page": None,
                "end_page": None,
                "start_spine": 0,
                "end_spine": 10,
            },
            {
                "job_index": 1,
                "start_page": None,
                "end_page": None,
                "start_spine": 10,
                "end_spine": 20,
            },
            {
                "job_index": 2,
                "start_page": None,
                "end_page": None,
                "start_spine": 20,
                "end_spine": 30,
            },
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.ProcessPoolExecutor",
        ThreadPoolExecutor,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._parallel_convert_worker",
        lambda *_args, **_kwargs: ("fake", fake_result),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._merge_parallel_results",
        lambda *_args, **_kwargs: fake_result,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(5)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    progress_messages: list[str] = []
    run_labelstudio_import(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        project_name="benchmark project",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="test",
        limit=None,
        sample=None,
        progress_callback=progress_messages.append,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=2,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        processed_output_root=processed_root,
        allow_labelstudio_write=True,
    )

    worker_events = [
        parse_worker_activity(message) for message in progress_messages
    ]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        and str(event.get("status") or "").startswith("job ")
        for event in worker_events
    )
    assert any(
        isinstance(event, dict) and event.get("type") == "reset"
        for event in worker_events
    )


def test_generate_pred_run_artifacts_reports_prelabel_task_progress(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    tasks = [
        {"data": {"segment_id": "seg-1"}},
        {"data": {"segment_id": "seg-2"}},
    ]

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.preflight_codex_model_access",
        lambda **_kwargs: None,
    )
    seen_granularity: list[str] = []

    def _fake_prelabel(_task, **kwargs):
        seen_granularity.append(str(kwargs.get("prelabel_granularity")))
        prompt_log_callback = kwargs.get("prompt_log_callback")
        if callable(prompt_log_callback):
            prompt_log_callback(
                {
                    "prompt": "test prompt",
                    "prompt_hash": "abc123",
                    "included_with_prompt_description": "test metadata",
                    "included_with_prompt": {"segment_block_count": 1},
                }
            )
        return {
            "result": [
                {
                    "value": {
                        "start": 0,
                        "end": 5,
                        "labels": ["TIP"],
                    }
                }
            ]
        }

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.prelabel_freeform_task",
        _fake_prelabel,
    )

    progress_messages: list[str] = []
    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        prelabel_granularity="span",
        prelabel_workers=2,
        progress_callback=progress_messages.append,
    )

    assert any(
        "Running freeform prelabeling... task 0/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 0/2" in msg for msg in progress_messages)
    assert any(
        "Running freeform prelabeling... task 1/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 1/2" in msg for msg in progress_messages)
    assert any(
        "Running freeform prelabeling... task 2/2" in msg
        for msg in progress_messages
    )
    assert any("workers=2" in msg and "task 2/2" in msg for msg in progress_messages)
    worker_events = [
        parse_worker_activity(message)
        for message in progress_messages
    ]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        and str(event.get("status") or "").startswith("task ")
        for event in worker_events
    )
    assert seen_granularity == ["span", "span"]
    assert result["prelabel"]["granularity"] == "span"
    assert result["prelabel"]["workers"] == 2
    assert result["prelabel"]["prompt_log_count"] == 2
    prompt_log_path = result["prelabel_prompt_log_path"]
    assert prompt_log_path is not None
    assert prompt_log_path.name == "prelabel_prompt_log.md"
    content = prompt_log_path.read_text(encoding="utf-8")
    assert "# Prelabel Prompt Log" in content
    assert "## Task 1/2 - `seg-1`" in content
    assert "## Task 2/2 - `seg-2`" in content
    assert "test metadata" in content
    assert "test prompt" in content


def test_generate_pred_run_artifacts_stops_prelabel_after_rate_limit_429(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    tasks = [
        {"data": {"segment_id": "seg-1"}},
        {"data": {"segment_id": "seg-2"}},
        {"data": {"segment_id": "seg-3"}},
    ]

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.preflight_codex_model_access",
        lambda **_kwargs: None,
    )

    prelabel_calls: list[str] = []

    def _fake_prelabel(task_payload, **_kwargs):
        segment_id = str(task_payload.get("data", {}).get("segment_id") or "")
        prelabel_calls.append(segment_id)
        raise RuntimeError("HTTP 429 Too Many Requests: rate limit exceeded")

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.prelabel_freeform_task",
        _fake_prelabel,
    )

    progress_messages: list[str] = []
    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        prelabel_workers=1,
        prelabel_allow_partial=True,
        progress_callback=progress_messages.append,
    )

    assert prelabel_calls == ["seg-1"]
    assert any("HTTP 429" in message for message in progress_messages)
    prelabel_summary = result["prelabel"]
    assert prelabel_summary["rate_limit_stop_triggered"] is True
    assert prelabel_summary["rate_limit_failure_count"] == 1
    assert prelabel_summary["rate_limit_skipped_count"] == 2
    assert prelabel_summary["failure_count"] == 3
    assert prelabel_summary["success_count"] == 0

    errors_path = result["prelabel_errors_path"]
    assert errors_path is not None
    rows = [
        json.loads(line)
        for line in errors_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(rows) == 3
    assert rows[0]["segment_id"] == "seg-1"
    assert rows[0]["rate_limit"] is True


def test_generate_pred_run_artifacts_ignores_progress_callback_errors(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._plan_parallel_convert_jobs",
        lambda *_args, **_kwargs: [
            {
                "job_index": 0,
                "start_page": None,
                "end_page": None,
                "start_spine": None,
                "end_spine": None,
            }
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest._write_processed_outputs",
        lambda **_kwargs: output_dir / "processed",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    progress_messages: list[str] = []

    def _broken_callback(message: str) -> None:
        progress_messages.append(message)
        raise RuntimeError("ui callback failed")

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        progress_callback=_broken_callback,
    )

    assert result["tasks_total"] == 1
    assert "fake convert complete" in progress_messages


def test_generate_pred_run_artifacts_freeform_focus_and_target_manifest_fields(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=i,
                text=f"block {i}",
                location={"block_index": i},
                source_kind="raw",
            )
            for i in range(9)
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        segment_blocks=4,
        segment_overlap=1,
        segment_focus_blocks=2,
        target_task_count=4,
        prelabel=False,
    )

    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["segment_blocks"] == 4
    assert manifest["segment_focus_blocks"] == 2
    assert manifest["segment_overlap_requested"] == 1
    assert manifest["segment_overlap_effective"] == 2
    assert manifest["segment_overlap"] == 2
    assert manifest["target_task_count"] == 4
    assert manifest["task_count"] == 4
    assert isinstance(manifest.get("timing"), dict)
    assert manifest["timing"]["total_seconds"] >= 0.0
    assert manifest["timing"]["prediction_seconds"] >= 0.0
    assert manifest["timing"]["checkpoints"]["conversion_seconds"] >= 0.0

    assert result["tasks"][0]["data"]["segment_text"] == "block 1\n\nblock 2"
    assert isinstance(result.get("timing"), dict)
    assert result["timing"]["total_seconds"] >= 0.0
    first_source_map = result["tasks"][0]["data"]["source_map"]
    assert first_source_map["focus_start_block_index"] == 1
    assert first_source_map["focus_end_block_index"] == 2
    assert first_source_map["focus_block_indices"] == [1, 2]
    assert first_source_map["context_before_block_range"] == "0"
    assert first_source_map["context_after_block_range"] == "3"


def test_generate_pred_run_artifacts_freeform_focus_floor_adjusts_overlap_without_target(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        tips=[],
        tip_candidates=[],
        topic_candidates=[],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None):
            if progress_callback is not None:
                progress_callback("fake convert complete")
            return fake_result

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=i,
                text=f"block {i}",
                location={"block_index": i},
                source_kind="raw",
            )
            for i in range(9)
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        segment_blocks=4,
        segment_overlap=1,
        segment_focus_blocks=2,
        target_task_count=None,
        prelabel=False,
    )

    manifest = json.loads(result["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["segment_blocks"] == 4
    assert manifest["segment_focus_blocks"] == 2
    assert manifest["segment_overlap_requested"] == 1
    assert manifest["segment_overlap_effective"] == 2
    assert manifest["segment_overlap"] == 2
    assert manifest["target_task_count"] is None
    assert manifest["task_count"] == 4


def _fake_pred_result(tmp_path: Path, tasks: list[dict[str, object]]) -> dict[str, object]:
    run_root = tmp_path / "2026-02-20_12.00.00" / "labelstudio" / "book"
    run_root.mkdir(parents=True, exist_ok=True)
    manifest_path = run_root / "manifest.json"
    manifest_path.write_text(
        "{}",
        encoding="utf-8",
    )
    return {
        "run_root": run_root,
        "processed_run_root": None,
        "processed_report_path": None,
        "tasks_total": len(tasks),
        "tasks": tasks,
        "manifest_path": manifest_path,
        "label_config": "<View/>",
        "run_config": {},
        "run_config_hash": None,
        "run_config_summary": None,
        "file_hash": "hash",
        "importer_name": "fake",
        "prelabel": {"enabled": True},
        "prelabel_report_path": run_root / "prelabel_report.json",
        "prelabel_errors_path": run_root / "prelabel_errors.jsonl",
    }


def test_run_labelstudio_import_falls_back_to_post_import_annotations(
    monkeypatch, tmp_path: Path
) -> None:
    tasks = [
        {
            "data": {"segment_id": "seg-1"},
            "annotations": [{"result": [{"value": {"start": 0, "end": 5, "labels": ["TIP"]}}]}],
        },
        {
            "data": {"segment_id": "seg-2"},
            "annotations": [{"result": [{"value": {"start": 6, "end": 11, "labels": ["NOTES"]}}]}],
        },
    ]

    class FakeLabelStudioClient:
        inline_rejections = 0
        created_annotations: list[tuple[int, dict[str, object]]] = []
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            if any("annotations" in item for item in payload):
                FakeLabelStudioClient.inline_rejections += 1
                raise RuntimeError("inline annotation import rejected")
            return {"task_count": len(payload)}

        def list_project_tasks(self, _project_id: int):
            return [
                {"id": 501, "data": {"segment_id": "seg-1"}},
                {"id": 502, "data": {"segment_id": "seg-2"}},
            ]

        def create_annotation(self, task_id: int, annotation: dict[str, object]):
            self.created_annotations.append((task_id, annotation))
            return {"id": len(self.created_annotations)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=tmp_path / "golden",
        pipeline="auto",
        project_name="prelabel test",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        prelabel=True,
        prelabel_upload_as="annotations",
        allow_labelstudio_write=True,
    )

    assert result["tasks_uploaded"] == 2
    assert result["prelabel_inline_annotations_fallback"] is True
    assert result["prelabel_post_import_annotations_created"] == 2
    assert FakeLabelStudioClient.inline_rejections == 1
    assert len(FakeLabelStudioClient.created_annotations) == 2


def test_run_labelstudio_import_can_upload_prelabels_as_predictions(
    monkeypatch, tmp_path: Path
) -> None:
    tasks = [
        {
            "data": {"segment_id": "seg-1"},
            "annotations": [{"result": [{"value": {"start": 0, "end": 5, "labels": ["TIP"]}}]}],
        }
    ]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=tmp_path / "golden",
        pipeline="auto",
        project_name="prelabel prediction test",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=False,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        prelabel=True,
        prelabel_upload_as="predictions",
        allow_labelstudio_write=True,
    )

    assert len(FakeLabelStudioClient.imported_batches) == 1
    uploaded = FakeLabelStudioClient.imported_batches[0][0]
    assert "predictions" in uploaded
    assert "annotations" not in uploaded


def test_run_labelstudio_import_skips_resume_manifest_when_project_is_new(
    monkeypatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "golden"
    stale_manifest = output_dir / "2026-02-10_00.00.00" / "labelstudio" / "book" / "manifest.json"
    stale_manifest.parent.mkdir(parents=True, exist_ok=True)
    stale_manifest.write_text(
        '{"project_name":"benchmark-project","task_scope":"freeform-spans"}',
        encoding="utf-8",
    )

    tasks = [{"data": {"chunk_id": "chunk-1"}}]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return []

        def find_project_by_title(self, _title: str):
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "book.epub",
        output_dir=output_dir,
        pipeline="auto",
        project_name="benchmark-project",
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=True,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        allow_labelstudio_write=True,
    )

    assert result["tasks_uploaded"] == 1
    assert len(FakeLabelStudioClient.imported_batches) == 1


def test_run_labelstudio_import_scope_mismatch_auto_dedupes_project_for_benchmark(
    monkeypatch, tmp_path: Path
) -> None:
    output_dir = tmp_path / "golden"
    stale_manifest = (
        output_dir / "2026-02-10_00.00.00" / "labelstudio" / "benchmark_project" / "manifest.json"
    )
    stale_manifest.parent.mkdir(parents=True, exist_ok=True)
    stale_manifest.write_text(
        '{"project_name":"benchmark_project","task_scope":"freeform-spans"}',
        encoding="utf-8",
    )

    tasks = [{"data": {"chunk_id": "chunk-1"}}]

    class FakeLabelStudioClient:
        imported_batches: list[list[dict[str, object]]] = []
        created_titles: list[str] = []

        def __init__(self, _url: str, _key: str) -> None:
            return None

        def list_projects(self):
            return [{"id": 42, "title": "benchmark_project"}]

        def find_project_by_title(self, title: str):
            if title == "benchmark_project":
                return {"id": 42, "title": title}
            return None

        def create_project(self, title: str, _label_config: str, description: str | None = None):
            self.created_titles.append(title)
            return {"id": 123, "title": title, "description": description}

        def import_tasks(self, _project_id: int, tasks_payload):
            payload = [dict(item) for item in tasks_payload]
            self.imported_batches.append(payload)
            return {"task_count": len(payload)}

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest.LabelStudioClient",
        FakeLabelStudioClient,
    )

    result = run_labelstudio_import(
        path=tmp_path / "benchmark_project.epub",
        output_dir=output_dir,
        pipeline="auto",
        project_name=None,
        segment_blocks=40,
        segment_overlap=5,
        overwrite=False,
        resume=True,
        label_studio_url="http://localhost:8080",
        label_studio_api_key="token",
        limit=None,
        sample=None,
        auto_project_name_on_scope_mismatch=True,
        allow_labelstudio_write=True,
    )

    assert result["project_name"] == "benchmark_project-1"
    assert FakeLabelStudioClient.created_titles == ["benchmark_project-1"]
    assert result["tasks_uploaded"] == 1
    assert len(FakeLabelStudioClient.imported_batches) == 1
