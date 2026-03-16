from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import cookimport.cli as cli
from cookimport.bench import oracle_upload


runner = CliRunner()


def _make_bundle(bundle_dir: Path) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for file_name in oracle_upload.BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
        (bundle_dir / file_name).write_text(f"{file_name}\n", encoding="utf-8")
    return bundle_dir


def test_resolve_oracle_benchmark_bundle_accepts_bundle_dir_and_parent(tmp_path: Path) -> None:
    session_root = tmp_path / "single-profile-benchmark"
    bundle_dir = _make_bundle(session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME)

    from_bundle = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)
    assert from_bundle.source_root == session_root
    assert from_bundle.bundle_dir == bundle_dir
    assert from_bundle.scope == "single_profile_group"

    from_parent = oracle_upload.resolve_oracle_benchmark_bundle(session_root)
    assert from_parent.source_root == session_root
    assert from_parent.bundle_dir == bundle_dir
    assert from_parent.scope == "single_profile_group"


def test_resolve_oracle_benchmark_bundle_rejects_missing_files(tmp_path: Path) -> None:
    session_root = tmp_path / "single-offline-benchmark"
    bundle_dir = session_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "upload_bundle_overview.md").write_text("overview\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        oracle_upload.resolve_oracle_benchmark_bundle(session_root)


def test_run_oracle_benchmark_upload_assembles_browser_command(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="browser ok\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="browser",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "browser"
    assert result.bundle_dir == bundle_dir
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:3] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--model",
        oracle_upload.ORACLE_DEFAULT_MODEL,
    ]
    assert command.count("--file") == 3
    for file_argument in oracle_upload._oracle_file_arguments(bundle_dir):
        assert file_argument in command
    assert "-p" in command
    kwargs = captured["kwargs"]
    assert kwargs == {"check": False, "capture_output": True, "text": True}


def test_run_oracle_benchmark_upload_assembles_dry_run_command(tmp_path: Path) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir.parent)

    captured: dict[str, object] = {}

    def fake_runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="dry run ok\n",
            stderr="",
        )

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="dry-run",
        runner=fake_runner,
    )

    assert result.success is True
    assert result.mode == "dry-run"
    command = captured["command"]
    assert isinstance(command, list)
    assert command[:6] == list(oracle_upload.ORACLE_DRY_RUN_BASE_COMMAND)
    assert "--model" in command
    assert oracle_upload.ORACLE_DEFAULT_MODEL in command
    assert command.count("--file") == 3
    for file_argument in oracle_upload._oracle_file_arguments(bundle_dir):
        assert file_argument in command


def test_run_oracle_benchmark_upload_dry_run_falls_back_to_local_preview_for_large_bundle(
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-profile-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    (bundle_dir / "upload_bundle_payload.jsonl").write_text(
        "x" * (oracle_upload.ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES + 1),
        encoding="utf-8",
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    result = oracle_upload.run_oracle_benchmark_upload(
        target=target,
        mode="dry-run",
    )

    assert result.success is True
    assert result.mode == "dry-run"
    assert result.returncode == 0
    assert "Local dry-run preview only" in result.stdout
    assert "upload_bundle_payload.jsonl" in result.stdout
    assert result.command[:3] == [
        oracle_upload.ORACLE_BROWSER_CMD,
        "--model",
        oracle_upload.ORACLE_DEFAULT_MODEL,
    ]


def test_bench_oracle_upload_command_resolves_existing_single_profile_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sample_single_profile_root = tmp_path / "single-profile-benchmark"
    _make_bundle(sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME)
    captured: dict[str, object] = {}

    def fake_run_oracle_benchmark_upload(
        *,
        target: oracle_upload.OracleBenchmarkBundleTarget,
        mode: str,
        model: str,
    ) -> oracle_upload.OracleUploadResult:
        captured["target"] = target
        captured["mode"] = mode
        captured["model"] = model
        return oracle_upload.OracleUploadResult(
            success=True,
            mode=mode,
            command=["npx", "-y", "@steipete/oracle", "--dry-run"],
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout="files-report ok\n",
            stderr="",
        )

    monkeypatch.setattr(cli, "run_oracle_benchmark_upload", fake_run_oracle_benchmark_upload)

    result = runner.invoke(
        cli.app,
        [
            "bench",
            "oracle-upload",
            str(sample_single_profile_root),
            "--mode",
            "dry-run",
        ],
    )

    assert result.exit_code == 0
    assert captured["mode"] == "dry-run"
    target = captured["target"]
    assert isinstance(target, oracle_upload.OracleBenchmarkBundleTarget)
    assert target.bundle_dir == (
        sample_single_profile_root / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    assert str(target.bundle_dir) in result.output
    assert "Oracle mode: dry-run" in result.output


def test_maybe_upload_benchmark_bundle_to_oracle_is_best_effort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundle_dir = _make_bundle(
        tmp_path / "single-offline-benchmark" / oracle_upload.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME
    )
    target = oracle_upload.resolve_oracle_benchmark_bundle(bundle_dir)

    monkeypatch.setattr(cli, "resolve_oracle_benchmark_bundle", lambda _path: target)
    monkeypatch.setattr(
        cli,
        "run_oracle_benchmark_upload",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("oracle broke")),
    )

    cli._maybe_upload_benchmark_bundle_to_oracle(
        bundle_dir=bundle_dir,
        scope="single_offline",
    )
