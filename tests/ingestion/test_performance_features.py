from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import pickle
from typer.testing import CliRunner
from cookimport import cli
from cookimport.cli import app
from cookimport.core.executor_fallback import ProcessThreadExecutorResolution
from cookimport.ocr.doctr_engine import resolve_ocr_device
import pytest
from tests.fast_stage_pipeline import install_fake_source_job_stage
from tests.paths import FIXTURES_DIR as TESTS_FIXTURES_DIR

runner = CliRunner()

def test_resolve_ocr_device():
    # Test explicit selection
    assert resolve_ocr_device("cpu") == "cpu"
    
    # Test auto (depends on environment, but should return a valid string)
    resolved = resolve_ocr_device("auto")
    assert resolved in ("cpu", "cuda", "mps")
    
    # Test invalid selection
    with pytest.raises(ValueError, match="Unsupported OCR device"):
        resolve_ocr_device("invalid")

def test_stage_with_performance_flags(tmp_path, monkeypatch: pytest.MonkeyPatch):
    install_fake_source_job_stage(monkeypatch, importer_name="text")
    monkeypatch.setattr(
        "cookimport.cli_commands.stage.resolve_process_thread_executor",
        lambda **_kwargs: ProcessThreadExecutorResolution(
            backend="serial",
            executor=None,
            messages=(),
        ),
    )
    fixtures_dir = TESTS_FIXTURES_DIR
    source_file = fixtures_dir / "simple_text.txt"
    output_dir = tmp_path / "output"
    
    # Test sequential with performance flags
    result = runner.invoke(app, [
        "stage", str(source_file), 
        "--out", str(output_dir), 
        "--warm-models",
        "--workers", "1",
        "--ocr-device", "cpu",
        "--ocr-batch-size", "1"
    ])
    assert result.exit_code == 0
    
    # Find the timestamped directory
    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    
    # Verify timing data in report
    report_file = timestamp_dir / "simple_text.excel_import_report.json"
    assert report_file.exists()
    with open(report_file) as f:
        report = json.load(f)
    
    assert "timing" in report
    assert report["timing"]["total_seconds"] >= 0
    assert "parsing_seconds" in report["timing"]
    assert "writing_seconds" in report["timing"]

def test_stage_parallel(tmp_path, monkeypatch: pytest.MonkeyPatch):
    install_fake_source_job_stage(monkeypatch, importer_name="text")
    monkeypatch.setattr(
        "cookimport.cli_commands.stage.resolve_process_thread_executor",
        lambda **_kwargs: ProcessThreadExecutorResolution(
            backend="serial",
            executor=None,
            messages=(),
        ),
    )
    fixtures_dir = TESTS_FIXTURES_DIR
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    
    # Create two files to process in parallel
    file1 = input_dir / "file1.txt"
    file2 = input_dir / "file2.txt"
    with open(fixtures_dir / "simple_text.txt") as f:
        content = f.read()
    file1.write_text(content)
    file2.write_text(content)
    
    output_dir = tmp_path / "output"
    
    result = runner.invoke(app, [
        "stage", str(input_dir), 
        "--out", str(output_dir), 
        "--workers", "2"
    ])
    assert result.exit_code == 0
    
    # Find the timestamped directory
    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    
    # Check that both reports were created
    assert (timestamp_dir / "file1.excel_import_report.json").exists()
    assert (timestamp_dir / "file2.excel_import_report.json").exists()
    
    # Check that outputs are correct
    assert (timestamp_dir / "final drafts" / "file1").exists()
    assert (timestamp_dir / "final drafts" / "file2").exists()


def test_stage_process_pool_permission_error_falls_back_to_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_source_job_stage(monkeypatch, importer_name="text")
    fixtures_dir = TESTS_FIXTURES_DIR
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    content = (fixtures_dir / "simple_text.txt").read_text(encoding="utf-8")
    (input_dir / "file1.txt").write_text(content, encoding="utf-8")
    (input_dir / "file2.txt").write_text(content, encoding="utf-8")

    class BrokenProcessPoolExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("sandbox denied")

    monkeypatch.setattr(
        "cookimport.core.executor_fallback.ProcessPoolExecutor",
        BrokenProcessPoolExecutor,
    )
    monkeypatch.setattr(
        "cookimport.cli_commands.stage.resolve_process_thread_executor",
        lambda **_kwargs: ProcessThreadExecutorResolution(
            backend="thread",
            executor=ThreadPoolExecutor(max_workers=2),
            messages=(
                "Process-based worker concurrency unavailable (sandbox denied); using in-process thread worker concurrency.",
            ),
        ),
    )

    real_subprocess_run = cli.subprocess.run

    def _fake_subprocess_run(command, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if (
            isinstance(command, list)
            and "--stage-worker-self-test" in command
        ):
            return cli.subprocess.CompletedProcess(command, 1, "", "")
        return real_subprocess_run(command, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", _fake_subprocess_run)

    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stage",
            str(input_dir),
            "--out",
            str(output_dir),
            "--workers",
            "2",
        ],
    )

    assert result.exit_code == 0
    output_text = result.output.lower()
    normalized_output_text = " ".join(output_text.split())
    assert (
        "using subprocess-backed worker concurrency" in normalized_output_text
        or "using in-process thread worker concurrency" in normalized_output_text
    )
    assert "running jobs serially" not in normalized_output_text

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    assert (timestamp_dir / "file1.excel_import_report.json").exists()
    assert (timestamp_dir / "file2.excel_import_report.json").exists()


def test_stage_require_process_workers_fails_when_process_pool_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixtures_dir = TESTS_FIXTURES_DIR
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    content = (fixtures_dir / "simple_text.txt").read_text(encoding="utf-8")
    (input_dir / "file1.txt").write_text(content, encoding="utf-8")
    (input_dir / "file2.txt").write_text(content, encoding="utf-8")

    class BrokenProcessPoolExecutor:
        def __init__(self, *_args, **_kwargs) -> None:
            raise PermissionError("sandbox denied")

    monkeypatch.setattr(
        "cookimport.core.executor_fallback.ProcessPoolExecutor",
        BrokenProcessPoolExecutor,
    )

    output_dir = tmp_path / "output"
    result = runner.invoke(
        app,
        [
            "stage",
            str(input_dir),
            "--out",
            str(output_dir),
            "--workers",
            "2",
            "--require-process-workers",
        ],
    )

    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)
    assert "process-based worker concurrency is required" in str(result.exception).lower()


def test_worker_label_includes_thread_name_for_thread_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cookimport import cli_worker

    class _DummyProcess:
        name = "MainProcess"

    class _DummyThread:
        name = "ThreadPoolExecutor-0_3"

    monkeypatch.setattr(
        "cookimport.cli_worker.multiprocessing.current_process",
        lambda: _DummyProcess(),
    )
    monkeypatch.setattr("cookimport.cli_worker.os.getpid", lambda: 4321)
    monkeypatch.setattr(
        "cookimport.cli_worker.threading.current_thread",
        lambda: _DummyThread(),
    )

    assert cli_worker._worker_label() == "MainProcess (4321) / ThreadPoolExecutor-0_3"


def test_worker_label_keeps_process_only_for_main_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cookimport import cli_worker

    class _DummyProcess:
        name = "ForkProcess-2"

    class _DummyThread:
        name = "MainThread"

    monkeypatch.setattr(
        "cookimport.cli_worker.multiprocessing.current_process",
        lambda: _DummyProcess(),
    )
    monkeypatch.setattr("cookimport.cli_worker.os.getpid", lambda: 2468)
    monkeypatch.setattr(
        "cookimport.cli_worker.threading.current_thread",
        lambda: _DummyThread(),
    )

    assert cli_worker._worker_label() == "ForkProcess-2 (2468)"


def test_stage_worker_request_dispatches_source_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cookimport import cli_worker

    source_file = tmp_path / "example.txt"
    source_file.write_text("example", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result_path = tmp_path / "result.pkl"
    request_path = tmp_path / "request.json"

    called: dict[str, object] = {}

    def _fake_execute_source_job(*args, **kwargs):  # noqa: ANN002, ANN003
        job = kwargs.get("job") or (args[0] if args else None)
        called["file_path"] = getattr(job, "file_path", None)
        called["display_name"] = kwargs.get("display_name")
        return {
            "file": "example.txt",
            "status": "success",
            "recipes": 1,
            "tips": 0,
            "duration": 0.1,
        }

    monkeypatch.setattr(cli_worker, "execute_source_job", _fake_execute_source_job)

    request_payload = {
        "result_path": str(result_path),
        "job": {
            "job_kind": "source_job",
            "file_path": str(source_file),
            "out_path": str(out_dir),
            "mapping_config": None,
            "run_dt": "2026-02-28T12:00:00",
            "display_name": "example.txt",
            "run_config": {},
            "run_config_hash": "abc",
            "run_config_summary": "summary",
            "epub_extractor": None,
            "job_index": 0,
            "job_count": 1,
            "start_page": None,
            "end_page": None,
            "start_spine": None,
            "end_spine": None,
        },
    }
    request_path.write_text(
        json.dumps(request_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    exit_code = cli_worker._run_stage_worker_request(request_path)
    assert exit_code == 0
    assert called.get("file_path") == source_file
    with result_path.open("rb") as handle:
        result_payload = pickle.load(handle)  # noqa: S301
    assert isinstance(result_payload, dict)
    assert result_payload.get("status") == "success"


def test_stage_worker_cli_self_test() -> None:
    from cookimport import cli_worker

    assert cli_worker._main(["--stage-worker-self-test"]) == 0
