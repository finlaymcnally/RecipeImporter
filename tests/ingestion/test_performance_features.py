from pathlib import Path
import json
from typer.testing import CliRunner
from cookimport.cli import app
from cookimport.ocr.doctr_engine import resolve_ocr_device
import pytest
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

def test_stage_with_performance_flags(tmp_path):
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

def test_stage_parallel(tmp_path):
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
        ],
    )

    assert result.exit_code == 0
    output_text = result.output.lower()
    assert "using thread-based worker concurrency" in output_text
    assert "running jobs serially" not in output_text

    timestamp_dirs = [
        path
        for path in output_dir.glob("*")
        if path.is_dir() and not path.name.startswith(".")
    ]
    assert len(timestamp_dirs) == 1
    timestamp_dir = timestamp_dirs[0]
    assert (timestamp_dir / "file1.excel_import_report.json").exists()
    assert (timestamp_dir / "file2.excel_import_report.json").exists()
