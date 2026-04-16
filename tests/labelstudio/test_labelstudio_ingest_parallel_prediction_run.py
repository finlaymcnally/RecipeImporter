from __future__ import annotations

import tests.labelstudio.labelstudio_ingest_parallel_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_generate_pred_run_artifacts_reports_prelabel_task_progress(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    fixture = _run_prelabel_task_progress_fixture(
        monkeypatch=monkeypatch,
        source=source,
        output_dir=output_dir,
    )
    progress_messages = fixture["progress_messages"]
    seen_granularity = fixture["seen_granularity"]
    result = fixture["result"]
    assert isinstance(progress_messages, list)
    assert isinstance(seen_granularity, list)
    assert isinstance(result, dict)

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


def test_generate_pred_run_artifacts_writes_prelabel_prompt_log(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    fixture = _run_prelabel_task_progress_fixture(
        monkeypatch=monkeypatch,
        source=source,
        output_dir=output_dir,
    )
    result = fixture["result"]
    prompt_log_path = fixture["prompt_log_path"]
    content = fixture["prompt_log_content"]
    assert isinstance(result, dict)
    assert isinstance(prompt_log_path, Path)
    assert isinstance(content, str)

    assert result["prelabel"]["prompt_log_count"] == 2
    assert prompt_log_path.name == "prelabel_prompt_log.md"
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
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "hello"},
        ],
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

    tasks = [
        {"data": {"segment_id": "seg-1"}},
        {"data": {"segment_id": "seg-2"}},
        {"data": {"segment_id": "seg-3"}},
    ]

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
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
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks_in, **_kwargs: tasks_in,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._build_prelabel_provider",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.preflight_codex_model_access",
        lambda **_kwargs: None,
    )

    prelabel_calls: list[str] = []

    def _fake_prelabel(task_payload, **_kwargs):
        segment_id = str(task_payload.get("data", {}).get("segment_id") or "")
        prelabel_calls.append(segment_id)
        raise RuntimeError("HTTP 429 Too Many Requests: rate limit exceeded")

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.prelabel_freeform_task",
        _fake_prelabel,
    )

    progress_messages: list[str] = []
    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        prelabel=True,
        allow_codex=True,
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
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "hello"},
        ],
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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.plan_source_job",
        lambda *_args, **_kwargs: [JobSpec(file_path=source, job_index=0, job_count=1)],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
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
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: "hash",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._write_processed_outputs",
        lambda **_kwargs: output_dir / "processed",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
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


def test_generate_pred_run_artifacts_can_skip_tasks_jsonl(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "hello"},
        ],
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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        write_label_studio_tasks=False,
    )

    run_root = Path(result["run_root"])
    assert not (run_root / "label_studio_tasks.jsonl").exists()
    assert result["tasks_jsonl_status"] == "skipped_by_config"

    manifest = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["tasks_jsonl_status"] == "skipped_by_config"
    assert manifest["write_label_studio_tasks"] is False

    run_manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["artifacts"]["tasks_jsonl_status"] == "skipped_by_config"
    assert "tasks_jsonl" not in run_manifest["artifacts"]


def test_generate_pred_run_artifacts_line_role_projection_prefers_projection_for_scoring(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=[
            "Pancakes",
            "SERVES 2",
            "1 cup flour",
            "Whisk batter",
            "NOTE: Keep warm",
        ],
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )
    _install_projection_generate_pred_run_artifacts_mocks(
        monkeypatch,
        source=source,
        fake_result=fake_result,
        label_first_result=label_first_result,
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="Pancakes SERVES 2 1 cup flour; Whisk batter NOTE: Keep warm",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
        patch_parsing_archive=True,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=processed_root,
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    projected_spans_path = result["line_role_pipeline_projected_spans_path"]
    assert projected_spans_path is not None and projected_spans_path.exists()
    projected_stage_path = projected_spans_path.parent / "semantic_row_predictions.json"
    projected_archive_path = projected_spans_path.parent / "extracted_archive.json"
    assert projected_stage_path.exists()
    assert projected_archive_path.exists()
    processed_run_root = Path(result["processed_run_root"])
    processed_stage_path = (
        processed_run_root / ".bench" / "book" / "semantic_row_predictions.json"
    )
    mirrored_stage_path = Path(result["semantic_row_predictions_path"])
    assert mirrored_stage_path == projected_stage_path
    assert result["extracted_archive_path"] == projected_archive_path
    assert processed_stage_path.exists()
    assert processed_stage_path != projected_stage_path

    stage_payload = json.loads(mirrored_stage_path.read_text(encoding="utf-8"))
    assert stage_payload["block_labels"]["0"] == "RECIPE_TITLE"
    assert stage_payload["block_labels"]["1"] == "YIELD_LINE"
    assert stage_payload["block_labels"]["2"] == "INGREDIENT_LINE"
    assert stage_payload["block_labels"]["3"] == "INSTRUCTION_LINE"
    assert stage_payload["block_labels"]["4"] == "RECIPE_NOTES"

    projected_rows = [
        json.loads(line)
        for line in projected_spans_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    predicted_ingredients = [
        row["text"] for row in projected_rows if row.get("label") == "INGREDIENT_LINE"
    ]
    predicted_instructions = [
        row["text"] for row in projected_rows if row.get("label") == "INSTRUCTION_LINE"
    ]
    predicted_notes = [
        row["text"] for row in projected_rows if row.get("label") == "RECIPE_NOTES"
    ]

    processed_draft = json.loads(
        (
            processed_run_root
            / "final drafts"
            / "book"
            / "r0.json"
        ).read_text(encoding="utf-8")
    )
    assert processed_draft["recipe"]["title"] == "Pancakes"
    assert [
        line["raw_text"]
        for step in processed_draft["steps"]
        for line in step.get("ingredient_lines", [])
    ] == predicted_ingredients
    assert processed_draft["steps"][0]["instruction"] == "Gather and prepare ingredients."
    assert [step["instruction"] for step in processed_draft["steps"][1:]] == predicted_instructions
    assert predicted_notes == ["NOTE: Keep warm"]
    assert result["line_role_pipeline_recipe_projection"]["recipes_applied"] == 1
    assert (
        result["line_role_pipeline_recipe_projection"][
            "authoritative_stage_outputs_mutated"
        ]
        is False
    )


def _build_authoritative_atomic_projection_fixture(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    label_first_result = _make_label_first_result(source=source, raw_artifacts=[])
    label_first_result = label_first_result.model_copy(deep=True)
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Tahini Dressing",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=1,
            text="Makes 1 cup",
            deterministic_label="YIELD_LINE",
            final_label="YIELD_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=2,
            text="1/2 cup tahini",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
    ]
    label_first_result.block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0, 1],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[2],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
    ]
    label_first_result.archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Tahini Dressing Makes 1 cup",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "1/2 cup tahini",
            "location": {"block_index": 1},
        },
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=2,
            atomic_indices=[0, 1, 2],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    artifacts, summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path,
        source_file=str(source),
        source_hash="hash-123",
        workbook_slug="book",
        label_first_result=label_first_result,
    )

    return {
        "archive_payload": json.loads(
            artifacts["extracted_archive_path"].read_text(encoding="utf-8")
        ),
        "stage_payload": json.loads(
            artifacts["semantic_row_predictions_path"].read_text(encoding="utf-8")
        ),
        "summary": summary,
    }


def test_authoritative_line_role_artifacts_aggregate_stage_payload_by_source_block(
    tmp_path: Path,
) -> None:
    fixture = _build_authoritative_atomic_projection_fixture(tmp_path)
    stage_payload = fixture["stage_payload"]
    summary = fixture["summary"]
    assert isinstance(stage_payload, dict)
    assert isinstance(summary, dict)

    assert stage_payload["block_count"] == 3
    assert stage_payload["block_labels"] == {
        "0": "RECIPE_TITLE",
        "1": "YIELD_LINE",
        "2": "INGREDIENT_LINE",
    }
    assert summary["span_count"] == 3


def test_authoritative_line_role_artifacts_preserve_atomic_projection_archive_semantics(
    tmp_path: Path,
) -> None:
    fixture = _build_authoritative_atomic_projection_fixture(tmp_path)
    archive_payload = fixture["archive_payload"]
    assert isinstance(archive_payload, list)

    assert len(archive_payload) == 3
    assert archive_payload[1]["location"]["features"]["line_role_projection"] is True
    assert archive_payload[1]["location"]["block_index"] == 0


def _build_final_nonrecipe_authority_fixture(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path: Path,
) -> dict[str, object]:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"
    processed_root = tmp_path / "processed"

    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=[
            "Pancakes",
            "1 cup flour",
            "Salt strengthens flavor.",
        ],
    )

    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    ).model_copy(deep=True)
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Salt strengthens flavor.",
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="rule",
        ),
    ]
    label_first_result.block_labels = [
        AuthoritativeBlockLabel(
            source_block_id="block:0",
            source_block_index=0,
            supporting_atomic_indices=[0],
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:1",
            source_block_index=1,
            supporting_atomic_indices=[1],
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeBlockLabel(
            source_block_id="block:2",
            source_block_index=2,
            supporting_atomic_indices=[2],
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="rule",
        ),
    ]
    label_first_result.archive_blocks = [
        {
            "index": 0,
            "block_id": "block:0",
            "text": "Pancakes",
            "location": {"block_index": 0},
        },
        {
            "index": 1,
            "block_id": "block:1",
            "text": "1 cup flour",
            "location": {"block_index": 1},
        },
        {
            "index": 2,
            "block_id": "block:2",
            "text": "Salt strengthens flavor.",
            "location": {"block_index": 2},
        },
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=1,
            atomic_indices=[0, 1],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    final_nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({2: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[2]),
        authority=make_authority_result({2: "knowledge"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[2],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "enabled": True,
            "authority_mode": "knowledge_refined_final",
            "input_mode": "nonrecipe_candidate_spans",
            "seed_nonrecipe_span_count": 1,
            "final_nonrecipe_span_count": 1,
            "changed_block_count": 1,
            "changed_blocks": [
                {
                    "block_index": 2,
                    "previous_final_category": None,
                    "final_category": "knowledge",
                    "applied_packet_ids": [],
                }
            ],
            "conflicts": [],
            "ignored_block_indices": [],
            "scored_effect": "final_authority",
        },
    )

    def _fake_execute_stage_import_session_from_result(**kwargs):
        run_root = kwargs["run_root"]
        run_root.mkdir(parents=True, exist_ok=True)
        stage_predictions_path = run_root / ".bench" / "book" / "semantic_row_predictions.json"
        stage_predictions_path.parent.mkdir(parents=True, exist_ok=True)
        stage_predictions_path.write_text(
            json.dumps(
                {
                    "schema_version": "stage_block_predictions.v1",
                    "block_labels": {"0": "RECIPE_TITLE", "1": "INGREDIENT_LINE", "2": "KNOWLEDGE"},
                    "label_blocks": {
                        "RECIPE_TITLE": [0],
                        "INGREDIENT_LINE": [1],
                        "KNOWLEDGE": [2],
                    },
                    "workbook_slug": "book",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        full_text_path = run_root / "raw" / "fake" / "hash-123" / "full_text.json"
        full_text_path.parent.mkdir(parents=True, exist_ok=True)
        full_text_path.write_text("[]", encoding="utf-8")
        report_path = run_root / "book.excel_import_report.json"
        report_path.write_text("{}", encoding="utf-8")
        result = kwargs["result"]
        return StageImportSessionResult(
            run_root=run_root,
            workbook_slug="book",
            source_file=source,
            source_hash="hash-123",
            importer_name="fake",
            conversion_result=result,
            report_path=report_path,
            semantic_row_predictions_path=stage_predictions_path,
            run_config={"write_markdown": kwargs.get("write_markdown")},
            run_config_hash=None,
            run_config_summary=None,
            llm_report={"enabled": False, "pipeline": "off"},
            timing={},
            label_first_result=label_first_result,
            nonrecipe_stage_result=final_nonrecipe_stage_result,
        )

    _install_projection_generate_pred_run_artifacts_mocks(
        monkeypatch,
        source=source,
        fake_result=fake_result,
        label_first_result=label_first_result,
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="Pancakes",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            ),
            ArchiveBlock(
                index=1,
                text="1 cup flour",
                location={"block_index": 1, "line_index": 0},
                source_kind="raw",
            ),
            ArchiveBlock(
                index=2,
                text="Salt strengthens flavor.",
                location={"block_index": 2, "line_index": 0},
                source_kind="raw",
            ),
        ],
        execute_stage_import_session_from_result=_fake_execute_stage_import_session_from_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=processed_root,
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )
    return {
        "result": result,
    }


def test_generate_pred_run_artifacts_processed_output_reuses_final_nonrecipe_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _build_final_nonrecipe_authority_fixture(
        monkeypatch,
        tmp_path=tmp_path,
    )
    result = fixture["result"]
    assert isinstance(result, dict)

    stage_payload = json.loads(
        Path(result["semantic_row_predictions_path"]).read_text(encoding="utf-8")
    )
    assert stage_payload["block_labels"]["2"] == "KNOWLEDGE"


def test_generate_pred_run_artifacts_processed_output_reports_final_nonrecipe_authority_projection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fixture = _build_final_nonrecipe_authority_fixture(
        monkeypatch,
        tmp_path=tmp_path,
    )
    result = fixture["result"]
    assert isinstance(result, dict)

    telemetry_payload = json.loads(
        (
            Path(result["line_role_pipeline_projected_spans_path"]).parent
            / "telemetry_summary.json"
        ).read_text(encoding="utf-8")
    )

    assert result["line_role_pipeline_recipe_projection"][
        "authoritative_stage_outputs_mutated"
    ] is True
    assert result["line_role_pipeline_recipe_projection"]["mode"] == (
        "final_authority_projection"
    )
    assert telemetry_payload["mode"] == "final_authority_projection"
    assert telemetry_payload["changed_block_indices"] == [2]


def test_nonrecipe_authority_projection_preserves_recipe_notes_outside_recipe() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Refrigerate leftovers, covered, for up to 3 days.",
            within_recipe_span=False,
            label="RECIPE_NOTES",
            decided_by="rule",
            reason_tags=["storage_or_serving_note"],
        )
    ]
    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({10: "other"}),
        routing=make_routing_result(candidate_block_indices=[10]),
        authority=make_authority_result({10: "other"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[10],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "knowledge_refined_final",
            "scored_effect": "final_authority",
            "changed_blocks": [{"block_index": 10}],
        },
    )

    adjusted, summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert summary["changed_block_count"] == 1
    assert len(adjusted) == 1
    assert adjusted[0].label == "RECIPE_NOTES"
    assert "nonrecipe_authority:other" not in adjusted[0].reason_tags


def test_nonrecipe_authority_projection_ignores_unresolved_candidate_without_final_authority() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Balancing Fat",
            within_recipe_span=False,
            label="NONRECIPE_CANDIDATE",
            decided_by="codex",
            reason_tags=["knowledge_heading"],
        )
    ]
    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({10: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[10]),
        authority=make_authority_result({}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[],
            unreviewed_block_category_by_index={10: "candidate"},
        ),
        refinement_report={
            "authority_mode": "deterministic_route_only",
            "scored_effect": "route_only",
            "changed_blocks": [],
        },
    )

    adjusted, summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert summary["authority_mode"] == "deterministic_route_only"
    assert adjusted[0].label == "NONRECIPE_CANDIDATE"
    assert "nonrecipe_authority:other" not in adjusted[0].reason_tags


def test_nonrecipe_authority_projection_marks_reviewed_candidate_as_codex_without_changed_blocks() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Salt and heat work together.",
            within_recipe_span=False,
            label="NONRECIPE_CANDIDATE",
            decided_by="fallback",
            reason_tags=["outside_recipe_route"],
        )
    ]
    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({10: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[10]),
        authority=make_authority_result({10: "other"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[10],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "nonrecipe_finalized_candidates",
            "scored_effect": "final_authority",
            "changed_blocks": [],
        },
    )

    adjusted, summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert summary["reviewed_candidate_block_count"] == 1
    assert summary["reviewed_candidate_block_indices"] == [10]
    assert summary["changed_block_count"] == 0
    assert adjusted[0].label == "OTHER"
    assert adjusted[0].decided_by == "codex"
    assert "nonrecipe_authority:other" in adjusted[0].reason_tags


def test_nonrecipe_authority_projection_preserves_row_level_exclude_inside_knowledge_block() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Think about making a grilled cheese sandwich.",
            within_recipe_span=False,
            label="NONRECIPE_EXCLUDE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        )
    ]
    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({10: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[10]),
        authority=make_authority_result({10: "knowledge"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[10],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "knowledge_refined_final",
            "scored_effect": "final_authority",
            "changed_blocks": [{"block_index": 10}],
        },
    )

    adjusted, summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert summary["changed_block_count"] == 1
    assert adjusted[0].label == "OTHER"
    assert adjusted[0].decided_by == "codex"
    assert "nonrecipe_authority:preserved_exclude" in adjusted[0].reason_tags
    assert "nonrecipe_authority:knowledge" not in adjusted[0].reason_tags


def test_nonrecipe_authority_projection_uses_row_level_authority_inside_mixed_source_block() -> None:
    predictions = [
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=10,
            text="Think about making a grilled cheese sandwich.",
            within_recipe_span=False,
            label="NONRECIPE_CANDIDATE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
        CanonicalLineRolePrediction(
            recipe_id=None,
            block_id="block:10",
            block_index=10,
            atomic_index=11,
            text="Slow, even heat melts the cheese before the bread burns.",
            within_recipe_span=False,
            label="NONRECIPE_CANDIDATE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
    ]
    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({10: "candidate", 11: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[10, 11]),
        authority=make_authority_result(
            {10: "knowledge"},
            row_category_by_index={10: "other", 11: "knowledge"},
            row_source_block_index_by_index={10: 10, 11: 10},
        ),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[10, 11],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "knowledge_refined_final",
            "scored_effect": "final_authority",
            "changed_blocks": [{"block_index": 11}],
        },
    )

    adjusted, _summary = _apply_nonrecipe_authority_to_predictions(
        predictions=predictions,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    assert adjusted[0].label == "OTHER"
    assert adjusted[1].label == "KNOWLEDGE"


def test_line_role_projection_stage_payload_marks_unresolved_candidate_outside_recipe(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=[
            "Pancakes",
            "1 cup flour",
            "Balancing Fat",
        ],
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="1 cup flour",
            deterministic_label="INGREDIENT_LINE",
            final_label="INGREDIENT_LINE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:2",
            source_block_index=2,
            atomic_index=2,
            text="Balancing Fat",
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        ),
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=1,
            block_indices=[0, 1],
            source_block_ids=["block:0", "block:1"],
            start_atomic_index=0,
            end_atomic_index=1,
            atomic_indices=[0, 1],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({2: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[2]),
        authority=make_authority_result({}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[],
            unreviewed_block_category_by_index={2: "candidate"},
        ),
        refinement_report={
            "authority_mode": "deterministic_route_only",
            "scored_effect": "route_only",
            "changed_blocks": [],
        },
    )

    artifacts, summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path / "run",
        source_file=str(source),
        source_hash="hash",
        workbook_slug="book",
        label_first_result=label_first_result,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    line_role_rows = [
        json.loads(line)
        for line in artifacts["line_role_predictions_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    balancing_fat_row = next(row for row in line_role_rows if row["text"] == "Balancing Fat")
    assert balancing_fat_row["label"] == "NONRECIPE_CANDIDATE"

    stage_payload = json.loads(
        artifacts["semantic_row_predictions_path"].read_text(encoding="utf-8")
    )
    assert stage_payload["block_labels"]["2"] == "OTHER"
    assert stage_payload["unresolved_candidate_block_indices"] == [2]
    assert stage_payload["unresolved_candidate_route_by_index"] == {"2": "candidate"}
    assert (
        "Unresolved candidate outside-recipe rows were marked unresolved and excluded from semantic scoring."
        in stage_payload["notes"]
    )

    telemetry_payload = json.loads(
        artifacts["telemetry_summary_path"].read_text(encoding="utf-8")
    )
    assert telemetry_payload["unresolved_candidate_line_count"] == 1
    assert telemetry_payload["unresolved_candidate_block_indices"] == [2]
    assert summary["unresolved_candidate_line_count"] == 1


def test_line_role_artifacts_write_semantic_predictions_for_reviewed_nonrecipe_candidates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=["Pancakes", "Salt and heat work together."],
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Salt and heat work together.",
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="fallback",
            reason_tags=["outside_recipe_route"],
        ),
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=0,
            block_indices=[0],
            source_block_ids=["block:0"],
            start_atomic_index=0,
            end_atomic_index=0,
            atomic_indices=[0],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({1: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[1]),
        authority=make_authority_result({1: "other"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[1],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "nonrecipe_finalized_candidates",
            "scored_effect": "final_authority",
            "changed_blocks": [],
        },
    )

    artifacts, summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path / "run",
        source_file=str(source),
        source_hash="hash",
        workbook_slug="book",
        label_first_result=label_first_result,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    route_rows = [
        json.loads(line)
        for line in artifacts["line_role_predictions_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    semantic_rows = [
        json.loads(line)
        for line in artifacts["semantic_line_role_predictions_path"].read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    route_row = next(row for row in route_rows if row["text"] == "Salt and heat work together.")
    semantic_row = next(
        row for row in semantic_rows if row["text"] == "Salt and heat work together."
    )

    assert route_row["label"] == "NONRECIPE_CANDIDATE"
    assert route_row["decided_by"] == "fallback"
    assert semantic_row["label"] == "OTHER"
    assert semantic_row["decided_by"] == "codex"
    assert summary["authoritative_stage_outputs_mutated"] is True
    assert summary["reviewed_candidate_block_indices"] == [1]


def test_line_role_stage_payload_overrides_outside_recipe_howto_with_final_authority(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=["The Four Elements of Good Cooking"],
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=23,
            atomic_index=0,
            text="The Four Elements of Good Cooking",
            deterministic_label="HOWTO_SECTION",
            final_label="HOWTO_SECTION",
            decided_by="codex",
            reason_tags=["codex_line_role"],
        )
    ]
    label_first_result.recipe_spans = []

    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({23: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[23]),
        authority=make_authority_result({23: "knowledge"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[23],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "knowledge_refined_final",
            "scored_effect": "final_authority",
            "changed_blocks": [{"block_index": 23}],
        },
    )

    artifacts, _summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path / "run",
        source_file=str(source),
        source_hash="hash",
        workbook_slug="book",
        label_first_result=label_first_result,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    route_rows = [
        json.loads(line)
        for line in artifacts["line_role_predictions_path"].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert route_rows[0]["label"] == "HOWTO_SECTION"

    stage_payload = json.loads(
        artifacts["semantic_row_predictions_path"].read_text(encoding="utf-8")
    )
    assert stage_payload["block_labels"]["0"] == "KNOWLEDGE"
    assert stage_payload["unresolved_candidate_block_indices"] == []


def test_authoritative_line_role_artifacts_preserve_runtime_telemetry_summary(
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    fake_result = _make_projection_conversion_result(
        source=source,
        block_texts=["Pancakes", "Salt and heat work together."],
    )
    label_first_result = _make_label_first_result(
        source=source,
        raw_artifacts=fake_result.raw_artifacts,
    )
    label_first_result.labeled_lines = [
        AuthoritativeLabeledLine(
            source_block_id="block:0",
            source_block_index=0,
            atomic_index=0,
            text="Pancakes",
            deterministic_label="RECIPE_TITLE",
            final_label="RECIPE_TITLE",
            decided_by="rule",
        ),
        AuthoritativeLabeledLine(
            source_block_id="block:1",
            source_block_index=1,
            atomic_index=1,
            text="Salt and heat work together.",
            deterministic_label="OTHER",
            final_label="NONRECIPE_CANDIDATE",
            decided_by="codex",
            reason_tags=["outside_recipe_route"],
        ),
    ]
    label_first_result.recipe_spans = [
        RecipeSpan(
            span_id="recipe_span_0",
            start_block_index=0,
            end_block_index=0,
            block_indices=[0],
            source_block_ids=["block:0"],
            start_atomic_index=0,
            end_atomic_index=0,
            atomic_indices=[0],
            title_block_index=0,
            title_atomic_index=0,
        )
    ]

    telemetry_summary_path = (
        tmp_path / "run" / "line-role-pipeline" / "telemetry_summary.json"
    )
    telemetry_summary_path.parent.mkdir(parents=True, exist_ok=True)
    telemetry_summary_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pipeline": "codex-line-role-route-v2",
                "summary": {
                    "batch_count": 1,
                    "attempt_count": 1,
                    "tokens_input": 100,
                    "tokens_cached_input": 10,
                    "tokens_output": 20,
                    "tokens_reasoning": 0,
                    "tokens_total": 130,
                },
                "phases": [
                    {
                        "phase_key": "line_role",
                        "summary": {"batch_count": 1},
                        "runtime_artifacts": {"worker_count": 1},
                    }
                ],
                "runtime_artifacts": {"runtime_root": "line-role-pipeline/runtime"},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    nonrecipe_stage_result = make_stage_result(
        seed=make_seed_result({1: "candidate"}),
        routing=make_routing_result(candidate_block_indices=[1]),
        authority=make_authority_result({1: "knowledge"}),
        candidate_status=make_finalize_status_result(
            reviewed_block_indices=[1],
            unreviewed_block_category_by_index={},
        ),
        refinement_report={
            "authority_mode": "knowledge_refined_final",
            "scored_effect": "final_authority",
            "changed_blocks": [{"block_index": 1}],
        },
    )

    artifacts, summary = _write_authoritative_line_role_artifacts(
        run_root=tmp_path / "run",
        source_file=str(source),
        source_hash="hash",
        workbook_slug="book",
        label_first_result=label_first_result,
        nonrecipe_stage_result=nonrecipe_stage_result,
    )

    telemetry_payload = json.loads(
        artifacts["telemetry_summary_path"].read_text(encoding="utf-8")
    )

    assert telemetry_payload["schema_version"] == 1
    assert telemetry_payload["projection_schema_version"] == (
        "line_role_final_authority_projection.v1"
    )
    assert telemetry_payload["mode"] == "final_authority_projection"
    assert telemetry_payload["summary"]["tokens_total"] == 130
    assert telemetry_payload["phases"][0]["phase_key"] == "line_role"
    assert telemetry_payload["runtime_artifacts"]["runtime_root"] == (
        "line-role-pipeline/runtime"
    )
    assert telemetry_payload["reviewed_candidate_block_indices"] == [1]
    assert telemetry_payload["changed_block_indices"] == [1]
    assert summary["reviewed_candidate_block_indices"] == [1]


def test_generate_pred_run_artifacts_line_role_lets_labeler_resolve_inflight_default(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Example line"},
        ],
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

    observed_codex_max_inflight: list[int | None] = []

    def _fake_label_atomic_lines_with_baseline(candidates, _settings, **kwargs):
        observed_codex_max_inflight.append(kwargs.get("codex_max_inflight"))
        predictions = [
            CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=candidate.block_id,
                block_index=candidate.block_index,
                atomic_index=candidate.atomic_index,
                text=str(candidate.text),
                label="OTHER",
                decided_by="rule",
                reason_tags=["test_label"],
            )
            for candidate in candidates
        ]
        return predictions, predictions

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.build_extracted_archive",
        lambda *_args, **_kwargs: [
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_label_first_stage_result",
        lambda **_kwargs: _make_label_first_result(
            source=source,
            raw_artifacts=[],
        ),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash",
        lambda _path: "hash-123",
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._build_line_role_candidates_from_archive",
        lambda **_kwargs: [
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id="block:0",
                block_index=0,
                atomic_index=0,
                text="Example line",
                within_recipe_span=True,
            ),
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.label_atomic_lines_with_baseline",
        _fake_label_atomic_lines_with_baseline,
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        split_phase_slots=1,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert observed_codex_max_inflight in ([], [None])


def test_generate_pred_run_artifacts_writes_authoritative_line_role_artifacts_after_llm_recipe_update(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    initial_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Toast",
                identifier="urn:test:toast",
                recipeIngredient=["1 slice bread"],
                recipeInstructions=["Toast the bread."],
                provenance={"location": {"start_block": 99, "end_block": 99}},
            )
        ],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Toast"},
            {"blockId": "b1", "orderIndex": 1, "text": "1 slice bread"},
            {"blockId": "b2", "orderIndex": 2, "text": "Toast the bread."},
        ],
        raw_artifacts=[],
        report=ConversionReport(),
        workbook="book",
        workbook_path=str(source),
    )
    updated_result = initial_result.model_copy(deep=True)
    updated_result.recipes[0].provenance = {
        "location": {"start_block": 0, "end_block": 0}
    }

    def _fake_run_codex_farm_recipe_pipeline(**_kwargs):
        return SimpleNamespace(
            updated_conversion_result=updated_result.model_copy(deep=True),
            llm_report={"enabled": True, "pipeline": "codex-recipe-shard-v1"},
        )

    authoritative_calls: list[int] = []

    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=initial_result.model_copy(deep=True),
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="Toast the bread.",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_label_first_stage_result",
        lambda **_kwargs: _make_label_first_result(
            source=source,
            raw_artifacts=[],
        ),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.run_codex_farm_recipe_pipeline",
        _fake_run_codex_farm_recipe_pipeline,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._write_authoritative_line_role_artifacts",
        lambda **_kwargs: (
            authoritative_calls.append(1) or {
                "line_role_predictions_path": tmp_path / "line_role_predictions.jsonl",
                "projected_spans_path": tmp_path / "projected_spans.jsonl",
                "semantic_row_predictions_path": tmp_path / "semantic_row_predictions.json",
                "extracted_archive_path": tmp_path / "extracted_archive.json",
            },
            {
                "recipes_applied": 0,
                "span_count": 0,
                "authoritative_stage_outputs_mutated": False,
                "mode": "authoritative_reuse",
            },
        ),
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        llm_recipe_pipeline="codex-recipe-shard-v1",
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert authoritative_calls == [1]


def test_generate_pred_run_artifacts_passes_allow_codex_to_line_role_live_llm(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = _make_empty_conversion_result(source)

    observed_live_llm_allowed: list[bool | None] = []

    def _fake_label_atomic_lines_with_baseline(candidates, _settings, **kwargs):
        observed_live_llm_allowed.append(kwargs.get("live_llm_allowed"))
        predictions = [
            CanonicalLineRolePrediction(
                recipe_id=candidate.recipe_id,
                block_id=candidate.block_id,
                block_index=candidate.block_index,
                atomic_index=candidate.atomic_index,
                text=str(candidate.text),
                label="OTHER",
                decided_by="rule",
                reason_tags=["test_label"],
            )
            for candidate in candidates
        ]
        return predictions, predictions

    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=fake_result,
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="Example line",
                location={"block_index": 0, "line_index": 0},
                source_kind="raw",
            )
        ],
        patch_parsing_archive=True,
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run._build_line_role_candidates_from_archive",
        lambda **_kwargs: [
            AtomicLineCandidate(
                recipe_id="recipe:0",
                block_id="block:0",
                block_index=0,
                atomic_index=0,
                text="Example line",
                within_recipe_span=True,
                rule_tags=["recipe_span_fallback"],
            ),
        ],
    )
    monkeypatch.setattr(
        "cookimport.parsing.label_source_of_truth.label_atomic_lines_with_baseline",
        _fake_label_atomic_lines_with_baseline,
    )

    generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        line_role_pipeline="codex-line-role-route-v2",
        allow_codex=True,
        split_phase_slots=1,
        write_label_studio_tasks=False,
        write_markdown=False,
    )

    assert observed_live_llm_allowed == [True]


def test_generate_pred_run_artifacts_passes_write_markdown_to_processed_outputs(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = _make_empty_conversion_result(source)
    _install_basic_generate_pred_run_artifacts_mocks(
        monkeypatch,
        fake_result=fake_result,
        archive_blocks=[
            ArchiveBlock(
                index=0,
                text="hello",
                location={"block_index": 0},
                source_kind="raw",
            )
        ],
        source_hash="hash",
        coverage_payload={
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )

    captured: dict[str, object] = {}

    def _fake_execute_stage_import_session_from_result(**kwargs):
        captured["write_markdown"] = kwargs.get("write_markdown")
        run_root = tmp_path / "processed-output" / "2026-03-03_02.00.00"
        run_root.mkdir(parents=True, exist_ok=True)
        stage_predictions_path = run_root / ".bench" / "book" / "semantic_row_predictions.json"
        stage_predictions_path.parent.mkdir(parents=True, exist_ok=True)
        stage_predictions_path.write_text(
            json.dumps(
                {
                    "schema_version": "stage_block_predictions.v1",
                    "block_labels": {},
                    "label_blocks": {},
                    "workbook_slug": "book",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        full_text_path = run_root / "raw" / "fake" / "hash-123" / "full_text.json"
        full_text_path.parent.mkdir(parents=True, exist_ok=True)
        full_text_path.write_text("[]", encoding="utf-8")
        report_path = run_root / "book.excel_import_report.json"
        report_path.write_text("{}", encoding="utf-8")
        result = kwargs["result"]
        return StageImportSessionResult(
            run_root=run_root,
            workbook_slug="book",
            source_file=source,
            source_hash="hash-123",
            importer_name="fake",
            conversion_result=result,
            report_path=report_path,
            semantic_row_predictions_path=stage_predictions_path,
            run_config={"write_markdown": kwargs.get("write_markdown")},
            run_config_hash=None,
            run_config_summary=None,
            llm_report={"enabled": False, "pipeline": "off"},
            timing={},
        )

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.execute_stage_import_session_from_result",
        _fake_execute_stage_import_session_from_result,
    )

    result = generate_pred_run_artifacts(
        path=source,
        output_dir=output_dir,
        pipeline="fake",
        processed_output_root=tmp_path / "processed-output",
        write_markdown=False,
    )

    assert captured["write_markdown"] is False
    assert result["run_config"]["write_markdown"] is False


def test_prepare_extracted_archive_matches_legacy_payload(tmp_path: Path) -> None:
    source = tmp_path / "book.pdf"
    source.write_text("source", encoding="utf-8")
    raw_artifacts = [
        RawArtifact(
            importer="pdf",
            source_hash="hash-123",
            location_id="full_text",
            extension="json",
            content={
                "blocks": [
                    {"index": 0, "text": "First block", "page": 1},
                    {"index": 1, "text": "Second block", "page": 1},
                ]
            },
            metadata={"artifact_type": "extracted_blocks"},
        )
    ]
    result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "First block", "location": {"page": 1}},
            {"blockId": "b1", "orderIndex": 1, "text": "Second block", "location": {"page": 1}},
        ],
        raw_artifacts=raw_artifacts,
        report=ConversionReport(),
        workbook=source.stem,
        workbook_path=str(source),
    )

    legacy_archive = build_extracted_archive(result, raw_artifacts)
    prepared_archive = prepare_extracted_archive(
        result=result,
        raw_artifacts=raw_artifacts,
        source_file=source.name,
        source_hash="hash-123",
        archive_builder=build_extracted_archive,
    )
    legacy_payload = [
        {
            "index": block.index,
            "text": block.text,
            "location": block.location,
            "source_kind": block.source_kind,
        }
        for block in legacy_archive
    ]

    assert prepared_archive_payload(prepared_archive) == legacy_payload
    assert list(prepared_archive.blocks) == legacy_archive
    assert prepared_archive.block_count == len(legacy_archive)


def test_generate_pred_run_artifacts_markdown_toggle_keeps_stage_predictions_identical(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")

    fake_result = ConversionResult(
        recipes=[
            RecipeCandidate(
                name="Recipe",
                provenance={"location": {"start_block": 0}},
            )
        ],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "Recipe"},
        ],
        raw_artifacts=[
            RawArtifact(
                importer="epub",
                source_hash="hash",
                location_id="full_text",
                extension="json",
                content={"blocks": [{"index": 0, "text": "Recipe"}]},
                metadata={"artifact_type": "extracted_blocks"},
            )
        ],
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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_freeform_span_tasks",
        lambda **_kwargs: [{"data": {"segment_id": "seg-1"}}],
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "segment_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
        lambda tasks, **_kwargs: tasks,
    )

    with_markdown = generate_pred_run_artifacts(
        path=source,
        output_dir=tmp_path / "golden-a",
        pipeline="fake",
        processed_output_root=tmp_path / "processed-a",
        write_markdown=True,
        write_label_studio_tasks=False,
    )
    without_markdown = generate_pred_run_artifacts(
        path=source,
        output_dir=tmp_path / "golden-b",
        pipeline="fake",
        processed_output_root=tmp_path / "processed-b",
        write_markdown=False,
        write_label_studio_tasks=False,
    )

    assert with_markdown["semantic_row_predictions_path"] is not None
    assert without_markdown["semantic_row_predictions_path"] is not None
    with_stage_path = Path(with_markdown["semantic_row_predictions_path"])
    without_stage_path = Path(without_markdown["semantic_row_predictions_path"])
    with_stage_payload = json.loads(with_stage_path.read_text(encoding="utf-8"))
    without_stage_payload = json.loads(without_stage_path.read_text(encoding="utf-8"))
    assert with_stage_payload == without_stage_payload

    with_archive_payload = json.loads(
        (Path(with_markdown["run_root"]) / "extracted_archive.json").read_text(
            encoding="utf-8"
        )
    )
    without_archive_payload = json.loads(
        (Path(without_markdown["run_root"]) / "extracted_archive.json").read_text(
            encoding="utf-8"
        )
    )
    assert with_archive_payload == without_archive_payload


def test_generate_pred_run_artifacts_freeform_focus_and_target_manifest_fields(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "block 0"},
            {"blockId": "b1", "orderIndex": 1, "text": "block 1"},
            {"blockId": "b2", "orderIndex": 2, "text": "block 2"},
            {"blockId": "b3", "orderIndex": 3, "text": "block 3"},
            {"blockId": "b4", "orderIndex": 4, "text": "block 4"},
            {"blockId": "b5", "orderIndex": 5, "text": "block 5"},
            {"blockId": "b6", "orderIndex": 6, "text": "block 6"},
            {"blockId": "b7", "orderIndex": 7, "text": "block 7"},
            {"blockId": "b8", "orderIndex": 8, "text": "block 8"},
        ],
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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
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
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
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
    assert first_source_map["focus_start_row_index"] == 1
    assert first_source_map["focus_end_row_index"] == 2
    assert first_source_map["focus_row_indices"] == [1, 2]
    assert first_source_map["context_before_row_range"] == "0"
    assert first_source_map["context_after_row_range"] == "3"


def test_generate_pred_run_artifacts_freeform_focus_floor_adjusts_overlap_without_target(
    monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "book.epub"
    source.write_text("source", encoding="utf-8")
    output_dir = tmp_path / "golden"

    fake_result = ConversionResult(
        recipes=[],
        sourceBlocks=[
            {"blockId": "b0", "orderIndex": 0, "text": "block 0"},
            {"blockId": "b1", "orderIndex": 1, "text": "block 1"},
            {"blockId": "b2", "orderIndex": 2, "text": "block 2"},
            {"blockId": "b3", "orderIndex": 3, "text": "block 3"},
            {"blockId": "b4", "orderIndex": 4, "text": "block 4"},
            {"blockId": "b5", "orderIndex": 5, "text": "block 5"},
            {"blockId": "b6", "orderIndex": 6, "text": "block 6"},
            {"blockId": "b7", "orderIndex": 7, "text": "block 7"},
            {"blockId": "b8", "orderIndex": 8, "text": "block 8"},
        ],
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

    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.registry.get_importer",
        lambda _name: FakeImporter(),
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.build_extracted_archive",
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
    monkeypatch.setattr("cookimport.labelstudio.ingest_flows.prediction_run.compute_file_hash", lambda _path: "hash")
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.compute_freeform_task_coverage",
        lambda *_args, **_kwargs: {
            "extracted_chars": 100,
            "chunked_chars": 90,
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "cookimport.labelstudio.ingest_flows.prediction_run.sample_freeform_tasks",
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
