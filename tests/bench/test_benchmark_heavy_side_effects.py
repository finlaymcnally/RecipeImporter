from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import cookimport.cli as cli
from cookimport.cli_support.test_safety import HeavyTestSideEffectBlocked


def test_benchmark_upload_bundle_is_blocked_by_default_under_pytest(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        HeavyTestSideEffectBlocked,
        match="benchmark upload bundle generation",
    ):
        cli._write_benchmark_upload_bundle(
            source_root=tmp_path,
            output_dir=tmp_path / cli.BENCHMARK_UPLOAD_BUNDLE_DIR_NAME,
            suppress_summary=False,
        )


def test_dashboard_refresh_is_blocked_by_default_under_pytest(tmp_path: Path) -> None:
    with pytest.raises(
        HeavyTestSideEffectBlocked,
        match="dashboard refresh",
    ):
        cli._refresh_dashboard_after_history_write(
            csv_path=tmp_path / "performance_history.csv",
            output_root=tmp_path / "output",
            golden_root=tmp_path / "golden",
            reason="test",
        )


@pytest.mark.heavy_side_effects
def test_allow_heavy_test_side_effects_fixture_allows_dashboard_refresh(
    allow_heavy_test_side_effects: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / ".history" / "performance_history.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text("header\n", encoding="utf-8")

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "stats_dashboard",
        lambda **kwargs: calls.append(dict(kwargs)),
    )

    cli._refresh_dashboard_after_history_write(
        csv_path=csv_path,
        output_root=tmp_path / "output",
        golden_root=tmp_path / "golden",
        dashboard_out_dir=tmp_path / "dashboard",
        reason="test",
    )

    assert calls == [
        {
            "output_root": tmp_path / "output",
            "golden_root": tmp_path / "golden",
            "out_dir": tmp_path / "dashboard",
            "open_browser": False,
            "since_days": None,
            "scan_reports": False,
            "scan_benchmark_reports": False,
        }
    ]


@pytest.mark.heavy_side_effects
def test_allow_heavy_test_side_effects_fixture_propagates_to_subprocess(
    allow_heavy_test_side_effects: None,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os, sys; "
                "sys.stdout.write(os.environ.get('COOKIMPORT_ALLOW_HEAVY_TEST_SIDE_EFFECTS', ''))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "1"
