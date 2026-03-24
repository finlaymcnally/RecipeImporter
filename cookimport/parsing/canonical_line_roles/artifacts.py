from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

def _write_runtime_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_optional_runtime_text(path: Path, text: str | None) -> None:
    rendered = str(text or "")
    if not rendered.strip():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _write_runtime_jsonl(path: Path, rows: Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def _write_worker_debug_input(path: Path, *, payload: Any, input_text: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if input_text is not None:
        path.write_text(str(input_text), encoding="utf-8")
        return
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
        return
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _relative_runtime_path(base: Path, path: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def _line_role_asdict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _line_role_asdict(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {key: _line_role_asdict(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_line_role_asdict(item) for item in value]
    if isinstance(value, list):
        return [_line_role_asdict(item) for item in value]
    return value


class _PromptArtifactState:
    def __init__(self, *, artifact_root: Path | None) -> None:
        self._prompt_dir = (
            None
            if artifact_root is None
            else artifact_root / "line-role-pipeline" / "prompts"
        )
        if self._prompt_dir is not None:
            self._prompt_dir.mkdir(parents=True, exist_ok=True)

    def _phase_dir(self, phase_key: str) -> Path | None:
        if self._prompt_dir is None:
            return None
        path = self._prompt_dir / phase_key
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(
        self,
        phase_key: str,
        stem: str,
        prompt_index: int,
        suffix: str,
    ) -> Path | None:
        if self._prompt_dir is None:
            return None
        phase_dir = self._phase_dir(phase_key)
        if phase_dir is None:
            return None
        return phase_dir / f"{stem}_{prompt_index:04d}{suffix}"

    def write_prompt(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        prompt_text: str,
    ) -> None:
        path = self._path(phase_key, prompt_stem, prompt_index, ".txt")
        if path is not None:
            path.write_text(prompt_text, encoding="utf-8")

    def write_response(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        response_payload: Mapping[str, Any],
    ) -> None:
        response_path = self._path(phase_key, f"{prompt_stem}_response", prompt_index, ".txt")
        parsed_path = self._path(phase_key, f"{prompt_stem}_parsed", prompt_index, ".json")
        response_text = json.dumps(
            response_payload.get("rows") if isinstance(response_payload.get("rows"), list) else response_payload,
            ensure_ascii=False,
            sort_keys=True,
        )
        if response_path is not None:
            response_path.write_text(response_text, encoding="utf-8")
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(response_payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        self._append_dedup(
            phase_key=phase_key,
            prompt_stem=prompt_stem,
            prompt_index=prompt_index,
            response_text=response_text,
        )

    def write_failure(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        error: str,
        response_payload: Any | None = None,
    ) -> None:
        parsed_path = self._path(phase_key, f"{prompt_stem}_parsed", prompt_index, ".json")
        if parsed_path is not None:
            parsed_path.write_text(
                json.dumps(
                    {
                        "error": str(error).strip() or "invalid_proposal",
                        "response_payload": response_payload,
                        "fallback_applied": True,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        self._append_dedup(
            phase_key=phase_key,
            prompt_stem=prompt_stem,
            prompt_index=prompt_index,
            response_text=json.dumps(
                {"error": str(error).strip() or "invalid_proposal"},
                sort_keys=True,
            ),
        )

    def _append_dedup(
        self,
        *,
        phase_key: str,
        prompt_stem: str,
        prompt_index: int,
        response_text: str,
    ) -> None:
        if self._prompt_dir is None:
            return
        prompt_path = self._path(phase_key, prompt_stem, prompt_index, ".txt")
        prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path is not None and prompt_path.exists() else ""
        dedup_path = self._phase_dir(phase_key) / "codex_prompt_log.dedup.txt"
        stable_hash = hashlib.sha256(
            f"{prompt_text}\n---\n{response_text}".encode("utf-8")
        ).hexdigest()
        existing_hashes: set[str] = set()
        if dedup_path.exists():
            try:
                for line in dedup_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    existing_hashes.add(line.split("\t", 1)[0].strip())
            except OSError:
                existing_hashes = set()
        if stable_hash in existing_hashes:
            return
        with dedup_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{stable_hash}\t{prompt_stem}_{prompt_index:04d}\n")

    def finalize(self, *, phase_key: str, parse_error_count: int) -> None:
        phase_dir = self._phase_dir(phase_key)
        if phase_dir is None:
            return
        (phase_dir / "parse_errors.json").write_text(
            json.dumps(
                {
                    "parse_error_count": int(parse_error_count),
                    "parse_error_present": bool(parse_error_count > 0),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
