from __future__ import annotations
import base64
import binascii
import hashlib
import json
import os
import re
import shlex
import subprocess
import threading
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Protocol
from cookimport.config.runtime_support import resolve_prelabel_cache_dir
from cookimport.llm.codex_farm_runner import (
    CodexFarmRunner,
    SubprocessCodexFarmRunner,
    as_pipeline_run_result_payload,
    ensure_codex_farm_pipelines_exist,
)
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    FREEFORM_LABEL_CONTROL_NAME,
    FREEFORM_LABEL_RESULT_TYPE,
    FREEFORM_TEXT_NAME,
    normalize_freeform_label,
)
_MODEL_CONFIG_LINE_RE = re.compile(r"^\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$")
_MODEL_REASONING_EFFORT_CONFIG_LINE_RE = re.compile(
    r"^\s*model_reasoning_effort\s*=\s*['\"]([^'\"]+)['\"]\s*$"
)
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
_CODEX_ALT_EXECUTABLE_RE = re.compile(r"^codex[0-9]+(?:\.exe)?$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PRELABEL_CODEX_FARM_PIPELINE_ID = "prelabel.freeform.v1"
_PRELABEL_CODEX_FARM_DEFAULT_CMD = "codex-farm"
_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_SPAN_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-span.prompt.md"
_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}
PRELABEL_GRANULARITY_SPAN = "span"
CODEX_REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)
_RATE_LIMIT_MESSAGE_RE = re.compile(
    r"\b429\b|too many requests|rate[ -]?limit(?:ed|ing)?",
    re.IGNORECASE,
)
_SPAN_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text spans for a "freeform spans" golden set.

GOAL
- Return only the specific spans that should be labeled.
- You may return zero, one, or many spans per row.
- Use only these labels:
  {{ALLOWED_LABELS}}

FOCUS SCOPE (READ THIS FIRST)
- The row list appears once at the end as one stream with explicit zone markers.
- Label only spans from rows between:
  <<<START_LABELING_ROWS_HERE>>>
  <<<STOP_LABELING_ROWS_HERE_CONTEXT_ONLY>>>
- Marker legend:
  <<<CONTEXT_BEFORE_LABELING_ONLY>>> = context before focus (read-only)
  <<<CONTEXT_AFTER_LABELING_ONLY>>> = context after focus (read-only)

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary.
Each item must be one of:
1) quote-anchored span (preferred):
   {"row_index": <int>, "label": "<LABEL>", "quote": "<exact text from that row>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

RULES
- Return spans only for focus rows. Non-focus rows are context only.
- quote text must be copied exactly from row text (case and internal whitespace must match).
- You may omit leading/trailing spaces in quote.
- If the quote appears multiple times in the same row, include occurrence.
- Do not return labels outside the allowed list.

Segment id: {{SEGMENT_ID}}
Rows (one row per line as "<row_index><TAB><row_text>"):
{{ROWS_WITH_FOCUS_MARKERS_COMPACT_LINES}}"""
_PRELABEL_SELECTION_LABEL_ALIASES = {
    "YIELD": "YIELD_LINE",
    "TIME": "TIME_LINE",
    "TIP": "KNOWLEDGE",
    "NOTES": "RECIPE_NOTES",
    "NOTE": "RECIPE_NOTES",
    "VARIANT": "RECIPE_VARIANT",
}

class LlmProvider(Protocol):
    """Small interface for LLM completion providers."""

    def complete(self, prompt: str) -> str:
        """Return raw model output."""
class CodexFarmProvider:
    """Run prelabel prompts through codex-farm and cache prompt/response pairs."""

    def __init__(
        self,
        *,
        cmd: str,
        timeout_s: int,
        cache_dir: Path | None = None,
        track_usage: bool = False,
        model: str | None = None,
        reasoning_effort: str | None = None,
        codex_farm_root: Path | str | None = None,
        codex_farm_workspace_root: Path | str | None = None,
        runner: CodexFarmRunner | None = None,
    ) -> None:
        normalized_cmd = cmd.strip()
        if not normalized_cmd:
            raise ValueError("codex-farm command cannot be empty")
        self.cmd = normalized_cmd
        self.timeout_s = max(1, int(timeout_s))
        self.track_usage = bool(track_usage)
        self.model = resolve_codex_model(model, cmd=self.cmd)
        self.reasoning_effort = normalize_codex_reasoning_effort(reasoning_effort)
        self.codex_farm_root = _resolve_codex_farm_root(codex_farm_root)
        self.codex_farm_workspace_root = _resolve_codex_farm_workspace_root(
            codex_farm_workspace_root
        )
        self.runner = runner
        self.cache_dir = resolve_prelabel_cache_dir(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._usage_lock = threading.Lock()
        self._calls_total = 0
        self._usage_totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "calls_with_usage": 0,
        }

    def complete(self, prompt: str) -> str:
        with self._usage_lock:
            self._calls_total += 1
        cache_key = hashlib.sha256(
            (
                f"{self.cmd}\n"
                f"track_usage={self.track_usage}\n"
                f"model={self.model or ''}\n"
                f"reasoning={self.reasoning_effort or ''}\n"
                f"root={self.codex_farm_root}\n"
                f"workspace={self.codex_farm_workspace_root or ''}\n"
                f"{prompt}"
            ).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                response = cached.get("response")
                if isinstance(response, str):
                    self._record_usage(cached.get("usage"))
                    return response
            except (json.JSONDecodeError, OSError):
                pass

        payload = run_codex_farm_json_prompt(
            prompt=prompt,
            timeout_seconds=self.timeout_s,
            cmd=self.cmd,
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            codex_farm_root=self.codex_farm_root,
            codex_farm_workspace_root=self.codex_farm_workspace_root,
            track_usage=self.track_usage,
            runner=self.runner,
        )
        turn_failed_message = str(payload.get("turn_failed_message") or "").strip()
        if turn_failed_message:
            raise RuntimeError(f"CodexFarm command failed: {turn_failed_message}")
        response = str(payload.get("response") or "")
        usage = payload.get("usage")
        returncode = int(payload.get("returncode") or 0)
        if returncode != 0:
            allow_nonzero_with_response = self.track_usage and bool(response)
            if not allow_nonzero_with_response:
                stderr = str(payload.get("stderr") or "").strip()
                stdout = str(payload.get("stdout") or "").strip()
                detail = _normalize_codex_error_detail(stderr or stdout or "unknown error")
                raise RuntimeError(
                    f"CodexFarm command failed (exit={returncode}): {detail}"
                )

        if not response:
            raise RuntimeError("CodexFarm command returned empty output")

        self._record_usage(usage)
        try:
            cache_path.write_text(
                json.dumps(
                    {
                        "cmd": self.cmd,
                        "track_usage": self.track_usage,
                        "model": self.model,
                        "reasoning_effort": self.reasoning_effort,
                        "codex_farm_root": str(self.codex_farm_root),
                        "codex_farm_workspace_root": (
                            str(self.codex_farm_workspace_root)
                            if self.codex_farm_workspace_root is not None
                            else None
                        ),
                        "prompt": prompt,
                        "response": response,
                        "usage": usage,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return response

    def _run(self, argv: list[str], prompt: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
            check=False,
        )

    @staticmethod
    def _is_plain_codex_command(argv: list[str]) -> bool:
        if len(argv) != 1:
            return False
        return _is_codex_executable(argv[0])

    def _argv_with_json_events(self, argv: list[str]) -> list[str]:
        return _argv_with_json_events(argv, track_usage=self.track_usage)

    def _response_and_usage(
        self, completed: subprocess.CompletedProcess[str]
    ) -> tuple[str, dict[str, int] | None]:
        if self.track_usage:
            response, usage = self._extract_json_event_response_and_usage(completed)
            if response:
                return response, usage
        response = (completed.stdout or "").strip()
        if not response:
            return "", None
        return response, None

    @staticmethod
    def _extract_json_event_response_and_usage(
        completed: subprocess.CompletedProcess[str],
    ) -> tuple[str, dict[str, int] | None]:
        response = ""
        usage: dict[str, int] | None = None
        streams = [completed.stdout or "", completed.stderr or ""]
        for stream in streams:
            for raw_line in stream.splitlines():
                line = raw_line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                event_type = payload.get("type")
                if event_type == "item.completed":
                    item = payload.get("item")
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") != "agent_message":
                        continue
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        response = text.strip()
                if event_type == "turn.completed":
                    usage = CodexFarmProvider._normalize_usage(payload.get("usage"))
        return response, usage

    @staticmethod
    def _normalize_usage(payload: Any) -> dict[str, int] | None:
        if not isinstance(payload, dict):
            return None
        usage: dict[str, int] = {}
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            value = payload.get(key)
            try:
                usage[key] = int(value)
            except (TypeError, ValueError):
                usage[key] = 0
        usage["reasoning_tokens"] = CodexFarmProvider._extract_reasoning_tokens(payload)
        return usage

    @staticmethod
    def _extract_reasoning_tokens(payload: dict[str, Any]) -> int:
        def _read_int(mapping: Any, *path: str) -> int | None:
            current: Any = mapping
            for key in path:
                if not isinstance(current, dict):
                    return None
                current = current.get(key)
            try:
                if current is None:
                    return None
                return int(current)
            except (TypeError, ValueError):
                return None

        candidate_paths = (
            ("reasoning_tokens",),
            ("output_tokens_reasoning",),
            ("inference_tokens",),
            ("processing_tokens",),
            ("output_tokens_details", "reasoning_tokens"),
            ("output_tokens_details", "inference_tokens"),
            ("output_tokens_details", "processing_tokens"),
            ("output_token_details", "reasoning_tokens"),
            ("output_token_details", "inference_tokens"),
            ("completion_tokens_details", "reasoning_tokens"),
            ("completion_tokens_details", "inference_tokens"),
        )
        for path in candidate_paths:
            value = _read_int(payload, *path)
            if value is not None:
                return max(0, value)
        return 0

    @staticmethod
    def _extract_turn_failed_message(completed: subprocess.CompletedProcess[str]) -> str | None:
        streams = [completed.stdout or "", completed.stderr or ""]
        for stream in streams:
            for raw_line in stream.splitlines():
                line = raw_line.strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") != "turn.failed":
                    continue
                error_payload = payload.get("error")
                if isinstance(error_payload, dict):
                    message = str(
                        error_payload.get("message")
                        or error_payload.get("detail")
                        or ""
                    ).strip()
                    normalized = _normalize_codex_error_detail(message)
                    if normalized:
                        return normalized
                if isinstance(error_payload, str):
                    normalized = _normalize_codex_error_detail(error_payload)
                    if normalized:
                        return normalized
        return None

    def _record_usage(self, usage: Any) -> None:
        normalized = self._normalize_usage(usage)
        if normalized is None:
            return
        with self._usage_lock:
            for key in (
                "input_tokens",
                "cached_input_tokens",
                "output_tokens",
                "reasoning_tokens",
            ):
                self._usage_totals[key] += normalized.get(key, 0)
            self._usage_totals["calls_with_usage"] += 1

    def usage_summary(self) -> dict[str, int]:
        with self._usage_lock:
            return {
                **self._usage_totals,
                "calls_total": self._calls_total,
            }

    @staticmethod
    def _is_stdin_tty_error(completed: subprocess.CompletedProcess[str]) -> bool:
        detail = f"{completed.stderr or ''}\n{completed.stdout or ''}".lower()
        return "stdin is not a terminal" in detail
def normalize_prelabel_granularity(value: str | None) -> str:
    normalized = (value or PRELABEL_GRANULARITY_SPAN).strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    if normalized != PRELABEL_GRANULARITY_SPAN:
        raise ValueError(
            "prelabel_granularity must be: span."
        )
    return PRELABEL_GRANULARITY_SPAN
def normalize_codex_reasoning_effort(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    if normalized not in CODEX_REASONING_EFFORT_VALUES:
        allowed = ", ".join(CODEX_REASONING_EFFORT_VALUES)
        raise ValueError(
            f"codex thinking effort must be one of: {allowed}"
        )
    return normalized
def _normalize_codex_error_detail(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(payload, dict):
        for key in ("detail", "message", "error"):
            candidate = payload.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return raw
def is_rate_limit_message(value: str | None) -> bool:
    """Return True when provider text indicates HTTP 429/rate limiting."""
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    return _RATE_LIMIT_MESSAGE_RE.search(text) is not None
def _argv_with_json_events(argv: list[str], *, track_usage: bool) -> list[str]:
    del track_usage
    return list(argv)
def _is_codex_executable(executable: str) -> bool:
    name = Path(executable).name.lower()
    if name in _CODEX_EXECUTABLES:
        return True
    if name in {"codex-farm", "codex-farm.exe"}:
        return False
    return bool(_CODEX_ALT_EXECUTABLE_RE.match(name))
def _split_command_env_and_argv(cmd: str) -> tuple[dict[str, str], list[str]]:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return {}, []
    if not tokens:
        return {}, []
    env_vars: dict[str, str] = {}
    index = 0
    if tokens[0] == "env":
        index = 1
        while index < len(tokens):
            token = tokens[index]
            if token == "--":
                index += 1
                break
            if token.startswith("-"):
                index += 1
                continue
            if not _ENV_ASSIGNMENT_RE.match(token):
                break
            key, value = token.split("=", 1)
            env_vars[key] = value
            index += 1
        return env_vars, tokens[index:]
    while index < len(tokens) and _ENV_ASSIGNMENT_RE.match(tokens[index]):
        key, value = tokens[index].split("=", 1)
        env_vars[key] = value
        index += 1
    return env_vars, tokens[index:]
def _extract_config_override_value(value: str, *, key: str) -> str | None:
    stripped = value.strip()
    if "=" not in stripped:
        return None
    parsed_key, parsed_value = stripped.split("=", 1)
    if parsed_key.strip() != key:
        return None
    parsed = parsed_value.strip()
    if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
        parsed = parsed[1:-1]
    normalized = parsed.strip()
    return normalized or None
def _extract_model_from_config_override(value: str) -> str | None:
    return _extract_config_override_value(value, key="model")
def _extract_reasoning_effort_from_config_override(value: str) -> str | None:
    parsed = _extract_config_override_value(value, key="model_reasoning_effort")
    try:
        return normalize_codex_reasoning_effort(parsed)
    except ValueError:
        return None
def _dedupe_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique
def _codex_home_roots(cmd: str | None = None) -> list[Path]:
    roots: list[Path] = []
    if cmd:
        env_vars, argv = _split_command_env_and_argv(cmd)
        cmd_codex_home = (env_vars.get("CODEX_HOME") or "").strip()
        if cmd_codex_home:
            roots.append(Path(cmd_codex_home).expanduser())
        if argv:
            executable = Path(argv[0]).name.lower()
            if _is_codex_executable(executable):
                stem = executable[:-4] if executable.endswith(".exe") else executable
                if stem != "codex":
                    roots.append((Path.home() / f".{stem}").expanduser())
    env_root = (os.environ.get("CODEX_HOME") or "").strip()
    if env_root:
        roots.append(Path(env_root).expanduser())
    # Default to primary Codex login first, then alt home.
    roots.extend([Path.home() / ".codex", Path.home() / ".codex-alt"])
    for path in sorted(Path.home().glob(".codex*")):
        if path.is_dir():
            roots.append(path)
    return _dedupe_paths(roots)
def _codex_config_paths(cmd: str | None = None) -> list[Path]:
    return [root / "config.toml" for root in _codex_home_roots(cmd=cmd)]
def _codex_models_cache_paths(cmd: str | None = None) -> list[Path]:
    return [root / "models_cache.json" for root in _codex_home_roots(cmd=cmd)]
def _codex_auth_paths(cmd: str | None = None) -> list[Path]:
    return [root / "auth.json" for root in _codex_home_roots(cmd=cmd)]
def _decode_jwt_claims(token: str) -> dict[str, Any] | None:
    pieces = token.split(".")
    if len(pieces) < 2:
        return None
    payload = pieces[1].strip()
    if not payload:
        return None
    pad = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode((payload + pad).encode("ascii"))
    except (binascii.Error, UnicodeError):
        return None
    try:
        parsed = json.loads(decoded.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(parsed, dict):
        return parsed
    return None
def _claims_email(claims: dict[str, Any]) -> str | None:
    candidate = claims.get("email")
    if isinstance(candidate, str) and candidate.strip():
        return candidate.strip()
    profile_payload = claims.get("https://api.openai.com/profile")
    if isinstance(profile_payload, dict):
        profile_email = profile_payload.get("email")
        if isinstance(profile_email, str) and profile_email.strip():
            return profile_email.strip()
    return None
def _claims_plan(claims: dict[str, Any]) -> str | None:
    auth_payload = claims.get("https://api.openai.com/auth")
    if isinstance(auth_payload, dict):
        plan = auth_payload.get("chatgpt_plan_type") or auth_payload.get("plan_type")
        if isinstance(plan, str) and plan.strip():
            return plan.strip()
    return None
def codex_account_info(cmd: str | None = None) -> dict[str, str] | None:
    """Best-effort account identity for a codex command from local auth files."""
    for auth_path in _codex_auth_paths(cmd=cmd):
        if not auth_path.exists():
            continue
        try:
            payload = json.loads(auth_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            continue
        for token_key in ("id_token", "access_token"):
            raw_token = tokens.get(token_key)
            if not isinstance(raw_token, str) or not raw_token.strip():
                continue
            claims = _decode_jwt_claims(raw_token)
            if not claims:
                continue
            email = _claims_email(claims)
            if not email:
                continue
            info = {"email": email, "auth_path": str(auth_path)}
            plan = _claims_plan(claims)
            if plan:
                info["plan"] = plan
            return info
    return None
def codex_account_summary(cmd: str | None = None) -> str | None:
    info = codex_account_info(cmd=cmd)
    if not info:
        return None
    plan = (info.get("plan") or "").strip()
    email = info.get("email") or ""
    if not email:
        return None
    if plan:
        return f"{email} ({plan})"
    return email
def _argv_has_model_setting(argv: list[str]) -> bool:
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-m", "--model"}:
            return True
        if token.startswith("--model="):
            return True
        if token in {"-c", "--config"} and index + 1 < len(argv):
            if _extract_model_from_config_override(argv[index + 1]):
                return True
            index += 2
            continue
        if token.startswith("--config="):
            if _extract_model_from_config_override(token.split("=", 1)[1]):
                return True
            index += 1
            continue
        if token.startswith("-c"):
            candidate = token[2:]
            if _extract_model_from_config_override(candidate):
                return True
        index += 1
    return False
def _argv_has_reasoning_effort_setting(argv: list[str]) -> bool:
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-c", "--config"} and index + 1 < len(argv):
            if _extract_reasoning_effort_from_config_override(argv[index + 1]):
                return True
            index += 2
            continue
        if token.startswith("--config="):
            if _extract_reasoning_effort_from_config_override(token.split("=", 1)[1]):
                return True
            index += 1
            continue
        if token.startswith("-c"):
            candidate = token[2:]
            if _extract_reasoning_effort_from_config_override(candidate):
                return True
        index += 1
    return False
def codex_cmd_with_model(cmd: str, model: str | None) -> str:
    """Append `--model` when command is codex-based and no model override exists."""
    normalized_cmd = cmd.strip()
    normalized_model = (model or "").strip()
    if not normalized_cmd or not normalized_model:
        return normalized_cmd
    try:
        argv = shlex.split(normalized_cmd)
    except ValueError:
        return normalized_cmd
    if not argv or not _is_codex_executable(argv[0]):
        return normalized_cmd
    if _argv_has_model_setting(argv):
        return normalized_cmd
    if len(argv) >= 2 and argv[1].lower() in {"exec", "e"}:
        updated = [argv[0], argv[1], "--model", normalized_model, *argv[2:]]
        return shlex.join(updated)
    if len(argv) == 1:
        return shlex.join([argv[0], "--model", normalized_model])
    return normalized_cmd
def codex_cmd_with_reasoning_effort(cmd: str, effort: str | None) -> str:
    """Append `-c model_reasoning_effort=...` when command is codex-based."""
    normalized_cmd = cmd.strip()
    normalized_effort = normalize_codex_reasoning_effort(effort)
    if not normalized_cmd or not normalized_effort:
        return normalized_cmd
    try:
        argv = shlex.split(normalized_cmd)
    except ValueError:
        return normalized_cmd
    if not argv or not _is_codex_executable(argv[0]):
        return normalized_cmd
    if _argv_has_reasoning_effort_setting(argv):
        return normalized_cmd
    config_arg = f'model_reasoning_effort="{normalized_effort}"'
    if len(argv) >= 2 and argv[1].lower() in {"exec", "e"}:
        updated = [argv[0], argv[1], "-c", config_arg, *argv[2:]]
        return shlex.join(updated)
    if len(argv) == 1:
        return shlex.join([argv[0], "-c", config_arg])
    return normalized_cmd
def codex_model_from_cmd(cmd: str) -> str | None:
    """Best-effort extraction of `--model` from a codex command string."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if not argv or not _is_codex_executable(argv[0]):
        return None
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-m", "--model"} and index + 1 < len(argv):
            candidate = str(argv[index + 1]).strip()
            return candidate or None
        if token.startswith("--model="):
            candidate = token.split("=", 1)[1].strip()
            return candidate or None
        if token == "-c" and index + 1 < len(argv):
            candidate = _extract_model_from_config_override(str(argv[index + 1]))
            if candidate:
                return candidate
            index += 2
            continue
        if token.startswith("-c"):
            candidate = _extract_model_from_config_override(token[2:])
            if candidate:
                return candidate
        index += 1
    return None
def codex_reasoning_effort_from_cmd(cmd: str) -> str | None:
    """Best-effort extraction of model_reasoning_effort from codex command config overrides."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return None
    if not argv or not _is_codex_executable(argv[0]):
        return None
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-c", "--config"} and index + 1 < len(argv):
            candidate = _extract_reasoning_effort_from_config_override(
                str(argv[index + 1])
            )
            if candidate:
                return candidate
            index += 2
            continue
        if token.startswith("--config="):
            candidate = _extract_reasoning_effort_from_config_override(
                token.split("=", 1)[1]
            )
            if candidate:
                return candidate
            index += 1
            continue
        if token.startswith("-c"):
            candidate = _extract_reasoning_effort_from_config_override(token[2:])
            if candidate:
                return candidate
        index += 1
    return None
def default_codex_model(cmd: str | None = None) -> str | None:
    """Resolve default codex model from env then local Codex config file."""
    farm_env_model = os.environ.get("COOKIMPORT_CODEX_FARM_MODEL")
    if farm_env_model and farm_env_model.strip():
        return farm_env_model.strip()
    env_model = os.environ.get("COOKIMPORT_CODEX_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()

    for path in _codex_config_paths(cmd=cmd):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _MODEL_CONFIG_LINE_RE.match(line)
            if not match:
                continue
            model = match.group(1).strip()
            if model:
                return model
    return None
def default_codex_reasoning_effort(cmd: str | None = None) -> str | None:
    """Resolve default codex reasoning effort from env/config."""
    farm_env_effort = normalize_codex_reasoning_effort(
        os.environ.get("COOKIMPORT_CODEX_FARM_REASONING_EFFORT")
    )
    if farm_env_effort:
        return farm_env_effort
    for path in _codex_config_paths(cmd=cmd):
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            match = _MODEL_REASONING_EFFORT_CONFIG_LINE_RE.match(line)
            if not match:
                continue
            try:
                effort = normalize_codex_reasoning_effort(match.group(1))
            except ValueError:
                effort = None
            if effort:
                return effort
    return None
def default_codex_reasoning_effort_for_model(
    model: str | None,
    *,
    cmd: str | None = None,
) -> str | None:
    """Resolve model-default reasoning effort from Codex models cache files."""
    target = str(model or "").strip().lower()
    if not target:
        return None

    for cache_path in _codex_models_cache_paths(cmd=cmd):
        if not cache_path.exists():
            continue
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows = payload.get("models")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip().lower()
            if slug != target:
                continue
            try:
                effort = normalize_codex_reasoning_effort(
                    str(row.get("default_reasoning_level") or "").strip()
                )
            except ValueError:
                effort = None
            if effort:
                return effort
    return None
def _supported_reasoning_efforts_from_model_row(row: dict[str, Any]) -> list[str]:
    """Best-effort normalized reasoning-effort list from one models_cache row."""
    raw_levels = row.get("supported_reasoning_levels")
    if not isinstance(raw_levels, list):
        return []
    efforts: list[str] = []
    seen: set[str] = set()
    for level in raw_levels:
        candidate: Any = level
        if isinstance(level, dict):
            candidate = level.get("effort")
        if not isinstance(candidate, str):
            continue
        try:
            normalized = normalize_codex_reasoning_effort(candidate)
        except ValueError:
            continue
        if not normalized or normalized in seen:
            continue
        efforts.append(normalized)
        seen.add(normalized)
    return efforts
def list_codex_models(cmd: str | None = None) -> list[dict[str, Any]]:
    """Read visible Codex model rows from local Codex model cache files."""
    models: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cache_path in _codex_models_cache_paths(cmd=cmd):
        if not cache_path.exists():
            continue
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        rows = payload.get("models")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug or slug in seen:
                continue
            visibility = str(row.get("visibility") or "").strip().lower()
            if visibility and visibility not in {"list", "default"}:
                continue
            display_name = str(row.get("display_name") or slug).strip() or slug
            description = str(row.get("description") or "").strip()
            entry: dict[str, Any] = {
                "slug": slug,
                "display_name": display_name,
                "description": description,
            }
            supported_efforts = _supported_reasoning_efforts_from_model_row(row)
            if supported_efforts:
                entry["supported_reasoning_efforts"] = supported_efforts
            models.append(entry)
            seen.add(slug)
    return models
def resolve_codex_model(value: str | None, *, cmd: str | None = None) -> str | None:
    normalized = (value or "").strip()
    if normalized:
        return normalized
    return default_codex_model(cmd=cmd)
def _resolve_codex_farm_root(value: Path | str | None) -> Path:
    if value is not None:
        configured = str(value).strip()
        if configured:
            return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "llm_pipelines"
def _resolve_codex_farm_workspace_root(
    value: Path | str | None,
) -> Path | None:
    if value is None:
        return None
    configured = str(value).strip()
    if not configured:
        return None
    return Path(configured).expanduser()
def _ensure_prelabel_codex_farm_pipeline(
    *,
    cmd: str,
    root_dir_str: str,
) -> None:
    root_dir = Path(root_dir_str)
    ensure_codex_farm_pipelines_exist(
        cmd=cmd,
        root_dir=root_dir,
        pipeline_ids=(_PRELABEL_CODEX_FARM_PIPELINE_ID,),
        env={"CODEX_FARM_ROOT": str(root_dir)},
    )
def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
def _codex_farm_return_code(process_run_payload: dict[str, Any] | None) -> int:
    if not isinstance(process_run_payload, dict):
        return 1
    subprocess_exit = _coerce_int(process_run_payload.get("subprocess_exit_code"))
    process_exit = _coerce_int(process_run_payload.get("process_exit_code"))
    if subprocess_exit is not None and subprocess_exit != 0:
        return subprocess_exit
    if process_exit is not None and process_exit != 0:
        return process_exit
    return 0
def _codex_farm_usage_payload(
    process_run_payload: dict[str, Any] | None,
) -> dict[str, int] | None:
    if not isinstance(process_run_payload, dict):
        return None
    telemetry = process_run_payload.get("telemetry")
    if not isinstance(telemetry, dict):
        return None
    summary = telemetry.get("summary")
    if not isinstance(summary, dict):
        return None
    tokens_input = _coerce_int(summary.get("tokens_input"))
    tokens_cached_input = _coerce_int(summary.get("tokens_cached_input"))
    tokens_output = _coerce_int(summary.get("tokens_output"))
    tokens_reasoning = _coerce_int(summary.get("tokens_reasoning"))
    if (
        tokens_input is None
        and tokens_cached_input is None
        and tokens_output is None
        and tokens_reasoning is None
    ):
        return None
    return {
        "input_tokens": max(0, int(tokens_input or 0)),
        "cached_input_tokens": max(0, int(tokens_cached_input or 0)),
        "output_tokens": max(0, int(tokens_output or 0)),
        "reasoning_tokens": max(0, int(tokens_reasoning or 0)),
    }
def run_codex_farm_json_prompt(
    *,
    prompt: str,
    timeout_seconds: int,
    cmd: str | None,
    model: str | None,
    reasoning_effort: str | None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
    allow_llm: bool = True,
    track_usage: bool = False,
    runner: CodexFarmRunner | None = None,
) -> dict[str, Any]:
    if not allow_llm:
        raise RuntimeError(
            "LLM call blocked by safety kill switch. Explicit Codex approval is required."
        )
    resolved_cmd = str(cmd or _PRELABEL_CODEX_FARM_DEFAULT_CMD).strip()
    if not resolved_cmd:
        raise ValueError("codex-farm command cannot be empty")
    try:
        resolved_argv = shlex.split(resolved_cmd)
    except ValueError:
        resolved_argv = []
    if resolved_argv:
        executable = Path(resolved_argv[0]).name.lower().strip()
        if executable.startswith("codex") and "farm" not in executable:
            raise RuntimeError(
                "prelabel codex cmd must point at codex-farm (direct local Codex CLI is unsupported)."
            )
    resolved_root = _resolve_codex_farm_root(codex_farm_root)
    resolved_workspace_root = _resolve_codex_farm_workspace_root(
        codex_farm_workspace_root
    )
    if runner is None:
        _ensure_prelabel_codex_farm_pipeline(
            cmd=resolved_cmd,
            root_dir_str=str(resolved_root),
        )
        codex_runner: CodexFarmRunner = SubprocessCodexFarmRunner(cmd=resolved_cmd)
    else:
        codex_runner = runner

    with TemporaryDirectory(prefix="cookimport-prelabel-") as temp_dir:
        temp_root = Path(temp_dir)
        in_dir = temp_root / "in"
        out_dir = temp_root / "out"
        in_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        input_path = in_dir / "prelabel_prompt.json"
        input_path.write_text(
            json.dumps({"prompt": prompt}, ensure_ascii=False),
            encoding="utf-8",
        )
        process_run = codex_runner.run_pipeline(
            _PRELABEL_CODEX_FARM_PIPELINE_ID,
            in_dir,
            out_dir,
            {"CODEX_FARM_ROOT": str(resolved_root)},
            root_dir=resolved_root,
            workspace_root=resolved_workspace_root,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        process_run_payload = as_pipeline_run_result_payload(process_run)
        returncode = _codex_farm_return_code(process_run_payload)
        output_payload: dict[str, Any] | None = None
        output_path = out_dir / input_path.name
        if output_path.exists():
            try:
                parsed = json.loads(output_path.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    output_payload = parsed
            except (OSError, json.JSONDecodeError):
                output_payload = None
        selections = None
        if isinstance(output_payload, dict):
            raw_selections = output_payload.get("selections")
            if isinstance(raw_selections, list):
                selections = raw_selections
        response = json.dumps(selections, ensure_ascii=False) if isinstance(
            selections, list
        ) else ""
        usage = _codex_farm_usage_payload(process_run_payload) if track_usage else None
        turn_failed_message = None
        if returncode != 0:
            if isinstance(process_run_payload, dict):
                turn_failed_message = (
                    str(process_run_payload.get("error_summary") or "").strip() or None
                )
            if turn_failed_message is None:
                turn_failed_message = "codex-farm process failed"
        return {
            "cmd": resolved_cmd,
            "argv": [resolved_cmd],
            "returncode": returncode,
            "stdout": "",
            "stderr": "",
            "response": response,
            "usage": usage,
            "turn_failed_message": turn_failed_message,
            "completed": None,
            "process_run": process_run_payload,
            "timeout_seconds": max(1, int(timeout_seconds)),
        }
def preflight_codex_model_access(
    *,
    cmd: str,
    timeout_s: int = 600,
    model: str | None = None,
    reasoning_effort: str | None = None,
    codex_farm_root: Path | str | None = None,
    codex_farm_workspace_root: Path | str | None = None,
) -> None:
    """Run one codex-farm probe call and fail fast for invalid model access."""
    normalized_cmd = cmd.strip()
    if not normalized_cmd:
        raise RuntimeError("codex-farm command cannot be empty")
    probe_payload = run_codex_farm_json_prompt(
        prompt="Return exactly an empty list.",
        timeout_seconds=max(1, int(timeout_s)),
        cmd=normalized_cmd,
        model=model,
        reasoning_effort=reasoning_effort,
        codex_farm_root=codex_farm_root,
        codex_farm_workspace_root=codex_farm_workspace_root,
        track_usage=True,
        allow_llm=True,
    )
    turn_failed_message = str(probe_payload.get("turn_failed_message") or "").strip()
    if turn_failed_message:
        raise RuntimeError(turn_failed_message)
    returncode = int(probe_payload.get("returncode") or 0)
    if returncode != 0:
        stderr = str(probe_payload.get("stderr") or "").strip()
        stdout = str(probe_payload.get("stdout") or "").strip()
        detail = _normalize_codex_error_detail(stderr or stdout or "unknown error")
        raise RuntimeError(detail)
def default_codex_cmd() -> str:
    """Resolve default codex-farm command used by prelabel flows."""
    explicit = (os.environ.get("COOKIMPORT_CODEX_CMD") or "").strip()
    if explicit:
        return explicit
    farm_override = (os.environ.get("COOKIMPORT_CODEX_FARM_CMD") or "").strip()
    if farm_override:
        return farm_override
    return _PRELABEL_CODEX_FARM_DEFAULT_CMD
