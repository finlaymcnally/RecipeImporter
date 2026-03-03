"""Serve the generated stats dashboard with a writable UI-state endpoint."""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlsplit

_UI_STATE_ROUTE_PATH = "/assets/dashboard_ui_state.json"
_MAX_UI_STATE_BYTES = 512 * 1024
_DEFAULT_UI_STATE = {"version": 1}
_ui_state_lock = Lock()


def _ui_state_path_for_dashboard(dashboard_dir: Path) -> Path:
    return dashboard_dir / "assets" / "dashboard_ui_state.json"


def ensure_dashboard_ui_state_file(dashboard_dir: Path) -> Path:
    """Create the program-side UI-state file if it does not exist yet."""
    ui_state_path = _ui_state_path_for_dashboard(dashboard_dir)
    ui_state_path.parent.mkdir(parents=True, exist_ok=True)
    if not ui_state_path.exists():
        ui_state_path.write_text(
            json.dumps(_DEFAULT_UI_STATE, indent=2) + "\n",
            encoding="utf-8",
        )
    return ui_state_path


def _normalized_ui_state_payload(raw_payload: Any) -> dict[str, Any]:
    if not isinstance(raw_payload, dict):
        raise ValueError("Expected JSON object payload.")
    payload = dict(raw_payload)

    raw_version = payload.get("version")
    if raw_version is None or str(raw_version).strip() == "":
        payload["version"] = int(_DEFAULT_UI_STATE["version"])
    else:
        payload["version"] = int(raw_version)

    raw_saved_at = payload.get("saved_at")
    if raw_saved_at is None:
        payload.pop("saved_at", None)
    else:
        payload["saved_at"] = str(raw_saved_at)

    return payload


def _read_ui_state_payload(ui_state_path: Path) -> dict[str, Any]:
    try:
        raw_text = ui_state_path.read_text(encoding="utf-8")
    except OSError:
        return dict(_DEFAULT_UI_STATE)
    try:
        payload = json.loads(raw_text or "{}")
    except json.JSONDecodeError:
        return dict(_DEFAULT_UI_STATE)
    try:
        return _normalized_ui_state_payload(payload)
    except (TypeError, ValueError):
        return dict(_DEFAULT_UI_STATE)


def _write_ui_state_payload(ui_state_path: Path, payload: dict[str, Any]) -> None:
    normalized = _normalized_ui_state_payload(payload)
    temp_path = ui_state_path.with_suffix(ui_state_path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(normalized, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(ui_state_path)


class DashboardStateRequestHandler(SimpleHTTPRequestHandler):
    """Serve dashboard static files and support read/write UI-state JSON."""

    def __init__(
        self,
        *args: Any,
        directory: str,
        ui_state_path: Path,
        **kwargs: Any,
    ) -> None:
        self._ui_state_path = ui_state_path
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, _format: str, *_args: Any) -> None:  # noqa: D401
        """Silence per-request logs to keep console output focused."""

    def _request_path(self) -> str:
        return urlsplit(self.path).path

    def _is_ui_state_route(self) -> bool:
        return self._request_path() == _UI_STATE_ROUTE_PATH

    def _send_json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json_response(status, {"error": message})

    def _handle_ui_state_read(self) -> None:
        with _ui_state_lock:
            payload = _read_ui_state_payload(self._ui_state_path)
        self._send_json_response(HTTPStatus.OK, payload)

    def _handle_ui_state_write(self) -> None:
        content_length_text = self.headers.get("Content-Length", "0").strip()
        try:
            content_length = int(content_length_text)
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid Content-Length.")
            return
        if content_length <= 0:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Request body is required.")
            return
        if content_length > _MAX_UI_STATE_BYTES:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Payload too large.")
            return

        raw_body = self.rfile.read(content_length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Body must be valid JSON.")
            return

        try:
            with _ui_state_lock:
                _write_ui_state_payload(self._ui_state_path, payload)
        except (OSError, TypeError, ValueError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid dashboard UI-state payload.")
            return

        self._send_json_response(HTTPStatus.OK, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if self._is_ui_state_route():
            self._handle_ui_state_read()
            return
        super().do_GET()

    def do_HEAD(self) -> None:  # noqa: N802
        if self._is_ui_state_route():
            self._handle_ui_state_read()
            return
        super().do_HEAD()

    def do_POST(self) -> None:  # noqa: N802
        if self._is_ui_state_route():
            self._handle_ui_state_write()
            return
        self.send_error(int(HTTPStatus.METHOD_NOT_ALLOWED), "Method not allowed.")

    def do_PUT(self) -> None:  # noqa: N802
        if self._is_ui_state_route():
            self._handle_ui_state_write()
            return
        self.send_error(int(HTTPStatus.METHOD_NOT_ALLOWED), "Method not allowed.")


def _url_host_for_browser(host: str) -> str:
    text = str(host).strip()
    if text in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    return text


def start_dashboard_server(
    *,
    dashboard_dir: Path,
    host: str,
    port: int,
) -> tuple[ThreadingHTTPServer, str]:
    """Create a running-ready dashboard server and return (server, index_url)."""
    resolved_dashboard_dir = dashboard_dir.expanduser().resolve()
    index_path = resolved_dashboard_dir / "index.html"
    if not index_path.exists():
        raise FileNotFoundError(f"Dashboard index not found: {index_path}")

    ui_state_path = ensure_dashboard_ui_state_file(resolved_dashboard_dir)
    handler = partial(
        DashboardStateRequestHandler,
        directory=str(resolved_dashboard_dir),
        ui_state_path=ui_state_path,
    )
    server = ThreadingHTTPServer((host, int(port)), handler)
    browser_host = _url_host_for_browser(host)
    url = f"http://{browser_host}:{server.server_port}/index.html"
    return server, url

