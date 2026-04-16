from __future__ import annotations

import os

import pytest

import cookimport.c4imp_entrypoint as entrypoint


def test_c4imp_entrypoint_sets_defaults_and_calls_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_app() -> None:
        captured["called"] = True
        captured["limit"] = os.getenv("C4IMP_LIMIT")

    monkeypatch.setattr(entrypoint, "app", _fake_app)
    monkeypatch.setattr(entrypoint.sys, "argv", ["C4imp"])
    for name in (
        "COOKIMPORT_WORKER_UTILIZATION",
        "COOKIMPORT_IO_PACE_EVERY_WRITES",
        "COOKIMPORT_IO_PACE_SLEEP_MS",
        "COOKIMPORT_BENCH_WRITE_MARKDOWN",
        "COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS",
        "COOKIMPORT_PLAIN_PROGRESS",
        "C4IMP_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    entrypoint.main()

    assert captured["called"] is True
    assert captured["limit"] is None
    assert os.environ["COOKIMPORT_WORKER_UTILIZATION"] == "90"
    assert os.environ["COOKIMPORT_IO_PACE_EVERY_WRITES"] == "16"
    assert os.environ["COOKIMPORT_IO_PACE_SLEEP_MS"] == "8"
    assert os.environ["COOKIMPORT_BENCH_WRITE_MARKDOWN"] == "1"
    assert os.environ["COOKIMPORT_BENCH_WRITE_LABELSTUDIO_TASKS"] == "0"
    assert os.environ["COOKIMPORT_PLAIN_PROGRESS"] == "0"


def test_c4imp_entrypoint_supports_integer_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _fake_app() -> None:
        captured["argv"] = list(entrypoint.sys.argv)
        captured["limit"] = os.getenv("C4IMP_LIMIT")

    monkeypatch.setattr(entrypoint, "app", _fake_app)
    monkeypatch.setattr(entrypoint.sys, "argv", ["C4imp", "12"])
    monkeypatch.delenv("C4IMP_LIMIT", raising=False)

    entrypoint.main()

    assert captured["argv"] == ["C4imp"]
    assert captured["limit"] == "12"


def test_c4imp_entrypoint_rejects_nonpositive_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entrypoint.sys, "argv", ["C4imp", "0"])

    with pytest.raises(SystemExit, match="Limit must be a positive integer."):
        entrypoint.main()
