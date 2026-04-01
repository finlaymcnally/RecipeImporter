from __future__ import annotations

import tests.labelstudio.labelstudio_ingest_parallel_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_llm_recipe_pipeline_normalizer_rejects_legacy_codex_farm_ids() -> None:
    with pytest.raises(ValueError, match="Invalid llm_recipe_pipeline"):
        _normalize_llm_recipe_pipeline("codex-farm-3pass-v1")
    with pytest.raises(ValueError, match="Invalid llm_recipe_pipeline"):
        _normalize_llm_recipe_pipeline("codex-farm-2stage-repair-v1")


def test_generate_pred_run_artifacts_rejects_legacy_prelabel_provider_alias(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")

    with pytest.raises(ValueError, match="prelabel_provider must be 'codex-farm'"):
        generate_pred_run_artifacts(
            path=source,
            output_dir=tmp_path / "golden",
            prelabel_provider="codex-cli",
        )


def test_generate_pred_run_artifacts_plan_mode_writes_codex_plan_without_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    class FakeImporter:
        name = "fake"

        def convert(self, *_args, **_kwargs):
            return ConversionResult(
                recipes=[
                    RecipeCandidate(
                        name="Toast",
                        identifier="urn:test:toast",
                        recipeIngredient=["1 slice bread"],
                        recipeInstructions=["Toast the bread."],
                        provenance={"location": {"start_block": 0, "end_block": 1}},
                    )
                ],
                nonRecipeBlocks=[],
                rawArtifacts=[
                    RawArtifact(
                        importer="fake",
                        sourceHash="hash",
                        locationId="full_text",
                        extension="json",
                        content={
                            "blocks": [
                                {"index": 0, "text": "Toast"},
                                {"index": 1, "text": "1 slice bread"},
                                {"index": 2, "text": "Toast the bread."},
                            ]
                        },
                        metadata={"artifact_type": "extracted_blocks"},
                    )
                ],
                report=ConversionReport(),
                workbook="book",
                workbookPath=str(source),
            )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: "hash",
    )

    with pytest.raises(ValueError):
        generate_pred_run_artifacts(
            path=source,
            output_dir=output_dir,
            pipeline="fake",
            llm_recipe_pipeline="codex-recipe-shard-v1",
            codex_execution_policy="plan",
        )


def test_plan_source_job_pdf_splits(monkeypatch) -> None:
    path = Path("sample.pdf")
    monkeypatch.setattr(
        "cookimport.staging.job_planning.resolve_pdf_page_count",
        lambda _path: 120,
    )

    jobs = plan_source_job(
        path,
        pdf_split_workers=4,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
    )

    assert len(jobs) == 3
    assert jobs[0].start_page == 0
    assert jobs[1].start_page == 40
    assert jobs[2].start_page == 80
    assert jobs[0].start_spine is None


def test_plan_source_job_epub_markitdown_disables_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.staging.job_planning.resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = plan_source_job(
        path,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="markitdown",
    )

    assert len(jobs) == 1
    assert jobs[0].start_spine is None
    assert jobs[0].end_spine is None


def test_plan_source_job_epub_unstructured_uses_split(monkeypatch) -> None:
    path = Path("sample.epub")
    monkeypatch.setattr(
        "cookimport.staging.job_planning.resolve_epub_spine_count",
        lambda _path: 120,
    )

    jobs = plan_source_job(
        path,
        pdf_split_workers=1,
        epub_split_workers=4,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        epub_extractor="unstructured",
    )

    assert len(jobs) > 1
    assert jobs[0].start_spine == 0
    assert jobs[-1].end_spine == 120


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
        "cookimport.labelstudio.ingest_flows.split_cache._try_acquire_file_lock_nonblocking",
        fake_try_lock,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.split_cache.time.sleep", lambda *_: None)

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
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "a"},
            {"blockId": "b1", "orderIndex": 1, "text": "b"},
            {"blockId": "b2", "orderIndex": 2, "text": "c"},
        ],
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
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "x"},
            {"blockId": "b1", "orderIndex": 1, "text": "y"},
        ],
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

    assert merged.recipes == []
    assert [block.text for block in merged.source_blocks] == ["x", "y", "a", "b", "c"]
    assert [block.order_index for block in merged.source_blocks] == [0, 1, 2, 3, 4]
    assert [block.block_id for block in merged.source_blocks] == ["b0", "b1", "b2", "b3", "b4"]
    assert len(merged.raw_artifacts) == 2
    shifted = next(artifact for artifact in merged.raw_artifacts if artifact.source_hash == "hash-a")
    shifted_indices = [block["index"] for block in shifted.content["blocks"]]
    assert shifted_indices == [2, 3, 4]
    assert merged.report.total_recipes == 0
    assert merged.report.total_standalone_blocks == 0


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Simple Soup"},
            {"blockId": "b1", "orderIndex": 1, "text": "1 cup stock"},
            {"blockId": "b2", "orderIndex": 2, "text": "Heat stock."},
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(
            total_recipes=9,
            total_standalone_blocks=5,
        ),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()
    authority_mismatch_path = (
        run_root / "recipe_boundary" / "book" / "authority_mismatch.json"
    )
    assert not authority_mismatch_path.exists()

    report_path = run_root / "book.excel_import_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["totalRecipes"] == 1
    assert not any(
        "report_total_mismatch_detected" in warning
        for warning in payload.get("warnings", [])
    )


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics_for_explicit_zero_totals(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Simple Soup"},
            {"blockId": "b1", "orderIndex": 1, "text": "1 cup stock"},
            {"blockId": "b2", "orderIndex": 2, "text": "Heat stock."},
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(
            total_recipes=0,
            total_standalone_blocks=0,
        ),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()


def test_write_processed_outputs_writes_report_total_mismatch_diagnostics_for_implicit_defaults(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_root = tmp_path / "processed"

    result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Simple Soup",
                ingredients=["1 cup stock"],
                instructions=["Heat stock."],
                identifier="urn:recipeimport:test:soup",
            )
        ],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Simple Soup"},
            {"blockId": "b1", "orderIndex": 1, "text": "1 cup stock"},
            {"blockId": "b2", "orderIndex": 2, "text": "Heat stock."},
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    run_dt = dt.datetime(2026, 3, 4, 12, 34, 56)
    run_root = _write_processed_outputs(
        result=result,
        path=source,
        run_dt=run_dt,
        output_root=output_root,
        importer_name="epub",
        run_config={"table_extraction": "off"},
    )

    mismatch_path = run_root / "book.report_totals_mismatch_diagnostics.json"
    assert not mismatch_path.exists()

    report_path = run_root / "book.excel_import_report.json"
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert not any(
        "report_total_mismatch_detected" in warning
        for warning in payload.get("warnings", [])
    )


def test_run_labelstudio_import_emits_post_merge_progress(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "hello"},
        ],
        non_recipe_blocks=[],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )

    class FakeImporter:
        name = "fake"

        def convert(self, _path, _mapping, progress_callback=None, **_kwargs):
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

    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer", lambda _name: FakeImporter())
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.plan_source_job",
        lambda *_args, **_kwargs: [JobSpec(file_path=source, job_index=0, job_count=1)],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
        lambda *_args, **_kwargs: [
            SimpleNamespace(index=0, text="hello", location={"block_index": 0}, source_kind="raw")
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(401)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.upload.LabelStudioClient", FakeLabelStudioClient)

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


def test_run_labelstudio_import_respects_custom_upload_batch_size(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_empty_conversion_result(source)
    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=fake_result,
        archive_blocks=[
            SimpleNamespace(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
        source_hash="hash",
    )
    fake_stage_result = StageImportSessionResult(
        run_root=processed_root / "2026-02-11_00:00:00",
        workbook_slug="book",
        source_file=source,
        source_hash="hash",
        importer_name="fake",
        conversion_result=fake_result,
        report_path=processed_root / "2026-02-11_00:00:00" / "book.excel_import_report.json",
        stage_block_predictions_path=(
            processed_root
            / "2026-02-11_00:00:00"
            / ".bench"
            / "book"
            / "stage_block_predictions.json"
        ),
        run_config={},
        run_config_hash=None,
        run_config_summary=None,
        llm_report={"enabled": False, "pipeline": "off"},
        timing={},
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.execute_stage_import_session_from_result",
        lambda **_kwargs: fake_stage_result,
    )

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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._write_processed_outputs",
        lambda **_kwargs: processed_root / "2026-02-11_00:00:00",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [
            {"data": {"segment_id": f"seg-{i}"}} for i in range(8)
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 1000,
            "segment_chars": 950,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.upload.LabelStudioClient", FakeLabelStudioClient)

    result = run_labelstudio_import(
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
        upload_batch_size=3,
        workers=2,
        pdf_split_workers=1,
        epub_split_workers=1,
        pdf_pages_per_job=50,
        epub_spine_items_per_job=10,
        processed_output_root=processed_root,
        allow_labelstudio_write=True,
    )

    assert FakeLabelStudioClient.uploaded_batches == [3, 3, 2]
    assert result["upload_batch_size"] == 3


def test_run_labelstudio_import_split_workers_emit_worker_activity(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="cookimport.config.run_settings")
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_empty_conversion_result(source)
    _install_split_import_mocks(
        monkeypatch,
        fake_result=fake_result,
        processed_root=processed_root,
        task_count=5,
        planned_jobs=[
            JobSpec(file_path=source, job_index=0, job_count=3, start_spine=0, end_spine=10),
            JobSpec(file_path=source, job_index=1, job_count=3, start_spine=10, end_spine=20),
            JobSpec(file_path=source, job_index=2, job_count=3, start_spine=20, end_spine=30),
        ],
        process_pool_executor=ThreadPoolExecutor,
    )

    progress_messages: list[str] = []
    _run_split_labelstudio_import_case(
        source=source,
        output_dir=output_dir,
        processed_root=processed_root,
        progress_messages=progress_messages,
    )

    assert any(
        "Running split conversion... task 0/3 (workers=2)" in message
        for message in progress_messages
    )
    assert any(
        "Running split conversion... task 3/3 (workers=2)" in message
        for message in progress_messages
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
    assert not any(
        "Ignoring unknown labelstudio split run config keys" in record.getMessage()
        for record in caplog.records
    )


def test_run_labelstudio_import_split_workers_fallback_to_thread_on_process_denied(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_empty_conversion_result(source)

    class BrokenProcessPoolExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("sandbox denied")

    thread_pool_started = {"count": 0}

    class TrackingThreadPoolExecutor(ThreadPoolExecutor):
        def __init__(self, *args, **kwargs):
            thread_pool_started["count"] += 1
            super().__init__(*args, **kwargs)

    _install_split_import_mocks(
        monkeypatch,
        fake_result=fake_result,
        processed_root=processed_root,
        task_count=5,
        planned_jobs=[
            JobSpec(file_path=source, job_index=0, job_count=3, start_spine=0, end_spine=10),
            JobSpec(file_path=source, job_index=1, job_count=3, start_spine=10, end_spine=20),
            JobSpec(file_path=source, job_index=2, job_count=3, start_spine=20, end_spine=30),
        ],
        process_pool_executor=BrokenProcessPoolExecutor,
        thread_pool_executor=TrackingThreadPoolExecutor,
    )

    progress_messages: list[str] = []
    _run_split_labelstudio_import_case(
        source=source,
        output_dir=output_dir,
        processed_root=processed_root,
        progress_messages=progress_messages,
    )

    assert thread_pool_started["count"] >= 1
    assert any(
        "using thread-based worker concurrency" in message.lower()
        for message in progress_messages
    )
    assert not any(
        "running split jobs serially" in message.lower()
        for message in progress_messages
    )
    worker_events = [parse_worker_activity(message) for message in progress_messages]
    assert any(
        isinstance(event, dict)
        and event.get("type") == "activity"
        and event.get("worker_total") == 2
        for event in worker_events
    )


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
        "cookimport.labelstudio.ingest_flows.upload.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.upload.LabelStudioClient",
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
        allow_codex=True,
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
        "cookimport.labelstudio.ingest_flows.upload.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.upload.LabelStudioClient",
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
        allow_codex=True,
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
        "cookimport.labelstudio.ingest_flows.upload.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.upload.LabelStudioClient",
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
        "cookimport.labelstudio.ingest_flows.upload.generate_pred_run_artifacts",
        lambda **_kwargs: _fake_pred_result(tmp_path, tasks),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.upload.LabelStudioClient",
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
