from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class LabelStudioClient:
    def __init__(self, base_url: str, api_key: str, *, timeout: int = 30) -> None:
        if not base_url:
            raise ValueError("Label Studio base_url is required")
        if not api_key:
            raise ValueError("Label Studio api_key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._refresh_token: str | None = None
        self._access_token: str | None = None
        self._access_scheme: str | None = None
        self._inspect_jwt_token()

    def _make_url(self, path: str) -> str:
        if not path.startswith("/"):
            path = f"/{path}"
        return f"{self.base_url}{path}"

    def _looks_like_jwt(self) -> bool:
        key = self.api_key.strip()
        return key.startswith("ey") and key.count(".") == 2

    def _decode_jwt_payload(self, token: str) -> dict[str, Any] | None:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        padding = "=" * (-len(payload_b64) % 4)
        try:
            decoded = base64.urlsafe_b64decode((payload_b64 + padding).encode("utf-8"))
            return json.loads(decoded.decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return None

    def _inspect_jwt_token(self) -> None:
        if not self._looks_like_jwt():
            return
        payload = self._decode_jwt_payload(self.api_key)
        if not payload:
            return
        token_type = payload.get("token_type")
        if token_type == "refresh":
            self._refresh_token = self.api_key
            return
        if token_type == "access":
            self._access_token = self.api_key
            self._access_scheme = "Bearer"

    def _ensure_access_token(self) -> None:
        if self._access_token or not self._refresh_token:
            return
        payload = {"refresh": self._refresh_token}
        for path in ("/api/token/refresh/", "/api/token/refresh", "/api/jwt/refresh/"):
            try:
                raw = self._request_refresh("POST", path, payload)
            except Exception:
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            access = data.get("access") or data.get("token") or data.get("access_token")
            if access:
                self._access_token = access
                self._access_scheme = "Bearer"
                return

    def _request_refresh(self, method: str, path: str, payload: Any) -> bytes:
        url = self._make_url(path)
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return response.read()

    def _auth_header(self, scheme: str) -> dict[str, str]:
        token = self._access_token or self.api_key
        if scheme:
            return {"Authorization": f"{scheme} {token}"}
        return {}

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        *,
        auth_scheme: str | None = None,
        allow_retry: bool = True,
    ) -> bytes:
        self._ensure_access_token()
        url = self._make_url(path)
        data = None
        scheme = auth_scheme
        if scheme is None:
            if self._access_scheme:
                scheme = self._access_scheme
            else:
                scheme = "Bearer" if self._looks_like_jwt() else "Token"
        headers = {
            **self._auth_header(scheme),
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            if exc.code == 401 and allow_retry:
                alt_scheme = "Bearer" if scheme == "Token" else "Token"
                return self._request(
                    method,
                    path,
                    payload,
                    auth_scheme=alt_scheme,
                    allow_retry=False,
                )
            raise RuntimeError(f"Label Studio API error {exc.code} on {path}: {detail}") from exc

    def _request_json(self, method: str, path: str, payload: Any | None = None) -> Any:
        raw = self._request(method, path, payload)
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def list_projects(self) -> list[dict[str, Any]]:
        projects: list[dict[str, Any]] = []
        page = 1
        while True:
            payload = self._request_json(
                "GET", f"/api/projects?page={page}&page_size=100"
            )
            if isinstance(payload, dict) and "results" in payload:
                results = payload.get("results", [])
                if isinstance(results, list):
                    projects.extend(results)
                if not payload.get("next"):
                    break
            elif isinstance(payload, list):
                projects.extend(payload)
                break
            else:
                break
            page += 1
        return projects

    def find_project_by_title(self, title: str) -> dict[str, Any] | None:
        for project in self.list_projects():
            if project.get("title") == title:
                return project
        return None

    def create_project(self, title: str, label_config: str, description: str) -> dict[str, Any]:
        payload = {
            "title": title,
            "label_config": label_config,
            "description": description,
        }
        return self._request_json("POST", "/api/projects", payload)

    def delete_project(self, project_id: int) -> None:
        self._request("DELETE", f"/api/projects/{project_id}")

    def import_tasks(self, project_id: int, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        return self._request_json("POST", f"/api/projects/{project_id}/import", tasks)

    def list_project_tasks(self, project_id: int) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urllib.parse.urlencode(
                {"project": project_id, "page": page, "page_size": 100}
            )
            payload = self._request_json("GET", f"/api/tasks?{query}")
            if isinstance(payload, dict) and "results" in payload:
                results = payload.get("results", [])
                if isinstance(results, list):
                    tasks.extend(
                        [item for item in results if isinstance(item, dict)]
                    )
                if not payload.get("next"):
                    break
            elif isinstance(payload, list):
                tasks.extend([item for item in payload if isinstance(item, dict)])
                break
            else:
                break
            page += 1
        return tasks

    def create_annotation(self, task_id: int, annotation: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "result": annotation.get("result") or [],
        }
        meta = annotation.get("meta")
        if isinstance(meta, dict):
            payload["meta"] = meta
        return self._request_json("POST", f"/api/tasks/{task_id}/annotations", payload)

    def export_tasks(self, project_id: int) -> list[dict[str, Any]]:
        paths = [
            f"/api/projects/{project_id}/export?download_all_tasks=true&exportType=JSON",
            f"/api/projects/{project_id}/export?download_all_tasks=true",
            f"/api/projects/{project_id}/export",
        ]
        last_error: Exception | None = None
        for path in paths:
            try:
                raw = self._request("GET", path)
                if not raw:
                    continue
                text = raw.decode("utf-8")
                return json.loads(text)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                continue
        if last_error:
            raise last_error
        raise RuntimeError("Unable to export Label Studio tasks")
