from __future__ import annotations

from pathlib import Path

from cookimport.analytics.perf_report import resolve_run_dir


def test_resolve_run_dir_detects_stage_timestamp_format(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    older = out_dir / "2026-02-16_11.00.00"
    newer = out_dir / "2026-02-16_12.30.45"
    older.mkdir()
    newer.mkdir()

    resolved = resolve_run_dir(None, out_dir)
    assert resolved == newer


def test_resolve_run_dir_accepts_legacy_timestamp_format(tmp_path: Path) -> None:
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    legacy = out_dir / "2026-01-01-10-00-00"
    modern = out_dir / "2026-01-02_08.00.00"
    legacy.mkdir()
    modern.mkdir()

    resolved = resolve_run_dir(None, out_dir)
    assert resolved == modern
