from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
import urllib.error
import urllib.request

import pytest

from cookimport.analytics.dashboard_render import render_dashboard
from cookimport.analytics.dashboard_schema import DashboardData
from cookimport.analytics.dashboard_state_server import start_dashboard_server


def _state_url_for_index(index_url: str) -> str:
    return index_url.rsplit("/index.html", 1)[0] + "/assets/dashboard_ui_state.json"


def test_dashboard_state_server_reads_and_writes_ui_state(tmp_path: Path) -> None:
    dashboard_dir = tmp_path / "dash"
    render_dashboard(dashboard_dir, DashboardData())

    server, index_url = start_dashboard_server(
        dashboard_dir=dashboard_dir,
        host="127.0.0.1",
        port=0,
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state_url = _state_url_for_index(index_url)

    try:
        with urllib.request.urlopen(state_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload["version"] == 1

        expected = {
            "version": 1,
            "saved_at": "2026-03-03T18:35:00Z",
            "previous_runs": {
                "visible_columns": ["run_timestamp", "strict_accuracy", "ai_model"],
                "quick_filters": {"exclude_ai_tests": False, "official_full_golden_only": True},
            },
        }
        write_request = urllib.request.Request(
            state_url,
            data=json.dumps(expected).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(write_request, timeout=2) as response:
            write_payload = json.loads(response.read().decode("utf-8"))
        assert write_payload == {"ok": True}

        with urllib.request.urlopen(state_url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        assert payload == expected
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_dashboard_state_server_rejects_non_object_payload(tmp_path: Path) -> None:
    dashboard_dir = tmp_path / "dash"
    render_dashboard(dashboard_dir, DashboardData())

    server, index_url = start_dashboard_server(
        dashboard_dir=dashboard_dir,
        host="127.0.0.1",
        port=0,
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state_url = _state_url_for_index(index_url)

    try:
        write_request = urllib.request.Request(
            state_url,
            data=json.dumps(["not", "an", "object"]).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(write_request, timeout=2)
        assert exc_info.value.code == 400
        exc_info.value.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
