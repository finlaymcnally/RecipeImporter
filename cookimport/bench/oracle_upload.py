from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


ORACLE_BROWSER_CMD = "/home/mcnal/.local/bin/oracle"
ORACLE_BROWSER_CHROME_PATH = "/home/mcnal/.local/bin/chromium-oracle-auto"
ORACLE_BROWSER_REMOTE_DEBUG_HOST = "127.0.0.1"
ORACLE_BROWSER_MODEL_STRATEGY = "select"
ORACLE_HOME_DIR = str(Path.home() / ".local" / "share" / "oracle")
ORACLE_BROWSER_PROFILE_DIR = str(Path(ORACLE_HOME_DIR) / "browser-profile")
ORACLE_LEGACY_HOME_DIR = str(Path.home() / ".oracle")
ORACLE_LEGACY_BROWSER_PROFILE_DIR = str(Path(ORACLE_LEGACY_HOME_DIR) / "browser-profile")
ORACLE_TEST_MODEL = os.environ.get(
    "ORACLE_TEST_MODEL",
    os.environ.get(
        "ORACLE_INSTANT_MODEL",
        os.environ.get(
            "ORACLE_FAST_MODEL",
            os.environ.get("ORACLE_FAST_SMOKE_MODEL", "gpt-5.3"),
        ),
    ),
)
ORACLE_DEFAULT_MODEL = os.environ.get(
    "ORACLE_GENUINE_MODEL",
    os.environ.get(
        "ORACLE_PRO_MODEL",
        os.environ.get(
            "ORACLE_REVIEW_MODEL",
            os.environ.get("ORACLE_DEEP_REVIEW_MODEL", "gpt-5-pro"),
        ),
    ),
)
ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES = 1_000_000
ORACLE_BROWSER_SHARD_TARGET_BYTES = 900_000
ORACLE_BROWSER_STARTER_PACKET_ROW_LOCATOR_SECTIONS = (
    "root_files",
    "starter_pack",
    "per_run_summaries",
)
ORACLE_BROWSER_REUSE_WAIT = "5m"
ORACLE_BROWSER_PROFILE_LOCK_TIMEOUT = "30m"
ORACLE_BROWSER_AUTO_REATTACH_DELAY = "30s"
ORACLE_BROWSER_AUTO_REATTACH_INTERVAL = "30s"
ORACLE_BROWSER_AUTO_REATTACH_TIMEOUT = "120s"
ORACLE_BACKGROUND_SESSION_POLL_SECONDS = 3.0
ORACLE_BACKGROUND_SESSION_POLL_INTERVAL_SECONDS = 0.1
ORACLE_CHATGPT_URL_ENV = "COOKIMPORT_ORACLE_CHATGPT_URL"
ORACLE_TEST_HELPER_ENV = "COOKIMPORT_ORACLE_TEST_HELPER"
ORACLE_TEST_HELPER_LABEL_ENV = "COOKIMPORT_ORACLE_TEST_HELPER_LABEL"
ORACLE_DRY_RUN_BASE_COMMAND = (
    "npx",
    "-y",
    "@steipete/oracle",
    "--dry-run",
    "summary",
    "--files-report",
)
BENCHMARK_UPLOAD_BUNDLE_DIR_NAME = "upload_bundle_v1"
BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES = (
    "upload_bundle_overview.md",
    "upload_bundle_index.json",
    "upload_bundle_payload.jsonl",
)
ORACLE_UPLOAD_RUNS_DIR_NAME = ".oracle_upload_runs"
ORACLE_UPLOAD_LOG_FILE_NAME = "oracle_upload.log"
ORACLE_UPLOAD_METADATA_FILE_NAME = "oracle_upload.json"
ORACLE_UPLOAD_STATUS_FILE_NAME = "oracle_upload_status.json"
ORACLE_BENCHMARK_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "benchmark.oracle-upload.prompt.md"
)
ORACLE_BENCHMARK_PROMPT_TEMPLATE_FALLBACK = "\n".join(
    [
        "{{HELPER_BANNER}}",
        "You are reviewing a benchmark upload bundle for the local `cookimport` CLI.",
        "The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.",
        "Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.",
        "Within that attachment, start with `upload_bundle_overview.md`, then use `upload_bundle_index.json` and `upload_bundle_payload.jsonl` only as needed to verify details.",
        "The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.",
        "Your primary goal is to help improve Codex benchmark accuracy, not merely to judge whether the current packet is internally consistent.",
        "Prioritize the remaining highest-leverage errors, regressions, and observability gaps that block the next concrete accuracy improvement.",
        "Return a concise review with exactly three sections: `Top regressions`, `Likely cause buckets`, and `Immediate next checks`.",
        "Keep the response factual and grounded in the attached bundle. Do not suggest rerunning the benchmark unless the bundle is clearly missing required evidence.",
    ]
)
_ORACLE_SESSION_RE = re.compile(r"oracle session (?P<session_id>[A-Za-z0-9._-]+)")
_ORACLE_COUNT_RE = re.compile(
    r"\b(?P<name>run_count|pair_count|changed_lines_total)\s*[:=]\s*(?P<value>\d+)",
    re.IGNORECASE,
)
_ORACLE_ROOT_REF_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2}/(?:single-profile-benchmark|single-book-benchmark)(?:/[A-Za-z0-9._-]+)?"
)
_TIMESTAMP_DIR_RE = re.compile(r"\d{4}-\d{2}-\d{2}_\d{2}\.\d{2}\.\d{2}")
_ORACLE_BENCHMARK_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}
_ORACLE_CHATGPT_ROOT_URLS = {
    "https://chatgpt.com",
    "https://chatgpt.com/",
}


@dataclass(frozen=True)
class OracleBenchmarkBundleTarget:
    requested_path: Path
    source_root: Path
    bundle_dir: Path
    scope: str


@dataclass(frozen=True)
class OracleUploadResult:
    success: bool
    mode: str
    command: list[str]
    bundle_dir: Path
    returncode: int
    stdout: str
    stderr: str
    oracle_version: str = ""
    status: str = ""
    status_reason: str = ""
    session_id: str = ""
    reattach_command: str = ""
    conversation_url: str = ""
    conversation_id: str = ""


@dataclass(frozen=True)
class PreparedOracleUploadInputs:
    prompt: str
    file_paths: list[Path]
    note: str = ""


@dataclass(frozen=True)
class OracleBackgroundUploadLaunch:
    mode: str
    model: str
    command: list[str]
    bundle_dir: Path
    launch_dir: Path
    log_path: Path
    metadata_path: Path
    pid: int
    note: str = ""
    browser_profile_dir: Path | None = None
    oracle_version: str = ""
    status: str = ""
    status_reason: str = ""
    session_id: str = ""
    reattach_command: str = ""
    conversation_url: str = ""
    conversation_id: str = ""
    auto_followup_worker_pid: int = 0
    auto_followup_log_path: Path | None = None
    auto_followup_status_path: Path | None = None


@dataclass(frozen=True)
class OracleUploadAudit:
    status: str
    status_reason: str
    session_id: str = ""
    reattach_command: str = ""
    conversation_url: str = ""
    conversation_id: str = ""


@dataclass(frozen=True)
class OracleSessionSnapshot:
    session_id: str
    status: str
    prompt: str
    created_at: str
    conversation_url: str = ""
    conversation_id: str = ""


def _infer_bundle_scope(source_root: Path) -> str:
    name = source_root.name.strip().lower()
    parent_name = source_root.parent.name.strip().lower()
    if name == "single-profile-benchmark":
        return "single_profile_group"
    if name == "single-book-benchmark":
        return "single_book"
    if parent_name == "single-profile-benchmark":
        return "single_profile_target"
    if parent_name == "single-book-benchmark":
        return "single_book"
    return "benchmark_bundle"


def _missing_bundle_files(bundle_dir: Path) -> list[str]:
    return [
        file_name
        for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES
        if not (bundle_dir / file_name).is_file()
    ]


def resolve_oracle_benchmark_bundle(path: Path) -> OracleBenchmarkBundleTarget:
    requested_path = path.expanduser().resolve(strict=False)
    if requested_path.name == BENCHMARK_UPLOAD_BUNDLE_DIR_NAME:
        bundle_dir = requested_path
        source_root = requested_path.parent
    else:
        source_root = requested_path
        bundle_dir = source_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME

    missing = _missing_bundle_files(bundle_dir)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"Benchmark upload bundle not found at {bundle_dir} (missing: {missing_text})."
        )

    return OracleBenchmarkBundleTarget(
        requested_path=requested_path,
        source_root=source_root,
        bundle_dir=bundle_dir,
        scope=_infer_bundle_scope(source_root),
    )


def build_oracle_benchmark_prompt(*, target: OracleBenchmarkBundleTarget) -> str:
    return _render_oracle_benchmark_prompt_template(
        path=ORACLE_BENCHMARK_PROMPT_TEMPLATE_PATH,
        fallback=ORACLE_BENCHMARK_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{HELPER_BANNER}}": _oracle_benchmark_helper_banner(),
            "{{BUNDLE_SCOPE}}": target.scope,
            "{{BENCHMARK_ROOT}}": str(target.source_root),
        },
    )


def _load_oracle_benchmark_prompt_template(path: Path, *, fallback: str) -> str:
    cached = _ORACLE_BENCHMARK_PROMPT_TEMPLATE_CACHE.get(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        if text:
            _ORACLE_BENCHMARK_PROMPT_TEMPLATE_CACHE[path] = (mtime_ns, text)
            return text
    except OSError:
        pass
    return fallback


def _render_oracle_benchmark_prompt_template(
    *,
    path: Path,
    fallback: str,
    replacements: Mapping[str, str],
) -> str:
    rendered = _load_oracle_benchmark_prompt_template(path, fallback=fallback)
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered.strip()


def _env_truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def oracle_test_helper_enabled(*, env: Mapping[str, str] | None = None) -> bool:
    source_env = env if env is not None else os.environ
    return _env_truthy(str(source_env.get(ORACLE_TEST_HELPER_ENV) or ""))


def _resolve_oracle_test_model(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    return str(
        source_env.get("ORACLE_TEST_MODEL")
        or source_env.get("ORACLE_INSTANT_MODEL")
        or source_env.get("ORACLE_FAST_MODEL")
        or source_env.get("ORACLE_FAST_SMOKE_MODEL")
        or ORACLE_TEST_MODEL
    ).strip()


def _resolve_oracle_genuine_model(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    return str(
        source_env.get("ORACLE_GENUINE_MODEL")
        or source_env.get("ORACLE_PRO_MODEL")
        or source_env.get("ORACLE_REVIEW_MODEL")
        or source_env.get("ORACLE_DEEP_REVIEW_MODEL")
        or ORACLE_DEFAULT_MODEL
    ).strip()


def resolve_oracle_benchmark_model(
    model: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    explicit_model = str(model or "").strip()
    if explicit_model:
        return explicit_model
    if oracle_test_helper_enabled(env=env):
        return _resolve_oracle_test_model(env=env)
    return _resolve_oracle_genuine_model(env=env)


def _oracle_benchmark_helper_banner(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    if not oracle_test_helper_enabled(env=source_env):
        return ""
    helper_label = str(source_env.get(ORACLE_TEST_HELPER_LABEL_ENV) or "").strip()
    helper_name = helper_label or "local pytest benchmark helper"
    return "\n".join(
        [
            "TEST HELPER ONLY.",
            f"This benchmark upload came from `{helper_name}` and is not a real operator benchmark run.",
            "Treat filesystem paths, scores, and artifacts as disposable test data.",
            "",
        ]
    )


def _oracle_file_argument(path: Path) -> str:
    try:
        return os.path.relpath(path, Path.cwd())
    except Exception:
        return str(path)


def _oracle_file_arguments(file_paths: list[Path]) -> list[str]:
    return [_oracle_file_argument(path) for path in file_paths]


def _oversized_bundle_files(bundle_dir: Path) -> list[tuple[str, int]]:
    oversized: list[tuple[str, int]] = []
    for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
        path = bundle_dir / file_name
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        if size_bytes > ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES:
            oversized.append((file_name, size_bytes))
    return oversized


def _split_text_to_byte_sized_chunks(text: str, *, max_bytes: int) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    current_parts: list[str] = []
    current_bytes = 0

    def flush() -> None:
        nonlocal current_parts, current_bytes
        if not current_parts:
            return
        chunks.append("".join(current_parts))
        current_parts = []
        current_bytes = 0

    def append_piece(piece: str) -> None:
        nonlocal current_bytes
        piece_bytes = len(piece.encode("utf-8"))
        if current_parts and current_bytes + piece_bytes > max_bytes:
            flush()
        if piece_bytes <= max_bytes:
            current_parts.append(piece)
            current_bytes += piece_bytes
            return
        oversized_chars: list[str] = []
        oversized_bytes = 0
        for char in piece:
            char_bytes = len(char.encode("utf-8"))
            if oversized_chars and oversized_bytes + char_bytes > max_bytes:
                chunks.append("".join(oversized_chars))
                oversized_chars = []
                oversized_bytes = 0
            oversized_chars.append(char)
            oversized_bytes += char_bytes
        if oversized_chars:
            chunks.append("".join(oversized_chars))

    for line in text.splitlines(keepends=True):
        append_piece(line)
    flush()
    return chunks or [text]


def _copy_or_shard_browser_upload_files(
    *,
    bundle_dir: Path,
    staging_dir: Path,
) -> tuple[list[Path], list[str]]:
    staged_paths: list[Path] = []
    shard_notes: list[str] = []
    for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
        source_path = bundle_dir / file_name
        file_staged_paths, shard_note = _stage_browser_upload_text_file(
            source_path=source_path,
            staging_dir=staging_dir,
            staged_name=file_name,
        )
        staged_paths.extend(file_staged_paths)
        if shard_note:
            shard_notes.append(shard_note)
    return staged_paths, shard_notes


def _stage_browser_upload_text_file(
    *,
    source_path: Path,
    staging_dir: Path,
    staged_name: str | None = None,
) -> tuple[list[Path], str]:
    target_name = staged_name or source_path.name
    target_path = Path(target_name)
    size_bytes = source_path.stat().st_size
    if size_bytes <= ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES:
        staged_path = staging_dir / target_path.name
        staged_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return [staged_path], ""

    shard_chunks = _split_text_to_byte_sized_chunks(
        source_path.read_text(encoding="utf-8"),
        max_bytes=ORACLE_BROWSER_SHARD_TARGET_BYTES,
    )
    shard_paths: list[Path] = []
    for index, chunk in enumerate(shard_chunks, start=1):
        shard_name = f"{target_path.stem}.part{index:03d}{target_path.suffix}"
        shard_path = staging_dir / shard_name
        shard_path.write_text(chunk, encoding="utf-8")
        shard_paths.append(shard_path)
    first_name = shard_paths[0].name
    last_name = shard_paths[-1].name
    shard_note = (
        f"`{target_path.name}` was split into {len(shard_paths)} ordered shards named "
        f"`{first_name}` through `{last_name}`."
    )
    return shard_paths, shard_note


def _read_oracle_upload_bundle_index_payload(bundle_dir: Path) -> dict[str, Any] | None:
    index_path = bundle_dir / "upload_bundle_index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _collect_payload_row_numbers(value: Any, selected_rows: set[int]) -> None:
    if isinstance(value, dict):
        payload_row = value.get("payload_row")
        if isinstance(payload_row, int):
            selected_rows.add(payload_row)
        for nested_value in value.values():
            _collect_payload_row_numbers(nested_value, selected_rows)
        return
    if isinstance(value, list):
        for nested_value in value:
            _collect_payload_row_numbers(nested_value, selected_rows)


def _collect_browser_safe_payload_rows(index_payload: Mapping[str, Any]) -> list[int]:
    navigation_payload = index_payload.get("navigation")
    if not isinstance(navigation_payload, dict):
        return []
    row_locators = navigation_payload.get("row_locators")
    if not isinstance(row_locators, dict):
        return []
    selected_rows: set[int] = set()
    for section_name in ORACLE_BROWSER_STARTER_PACKET_ROW_LOCATOR_SECTIONS:
        _collect_payload_row_numbers(row_locators.get(section_name), selected_rows)
    return sorted(row for row in selected_rows if row > 0)


def _write_selected_payload_rows(
    *,
    source_path: Path,
    output_path: Path,
    selected_rows: list[int],
) -> tuple[int, int]:
    selected_row_set = set(selected_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_count = 0
    selected_bytes = 0
    with source_path.open("r", encoding="utf-8") as source_handle, output_path.open(
        "w",
        encoding="utf-8",
    ) as output_handle:
        for row_number, line in enumerate(source_handle, start=1):
            if row_number not in selected_row_set:
                continue
            output_handle.write(line)
            selected_count += 1
            selected_bytes += len(line.encode("utf-8"))
    return selected_count, selected_bytes


def _prepare_browser_safe_starter_upload_inputs(
    *,
    target: OracleBenchmarkBundleTarget,
    staging_dir: Path,
    prompt: str,
    oversized_files: list[tuple[str, int]],
) -> PreparedOracleUploadInputs | None:
    index_payload = _read_oracle_upload_bundle_index_payload(target.bundle_dir)
    if index_payload is None:
        return None
    selected_rows = _collect_browser_safe_payload_rows(index_payload)
    if not selected_rows:
        return None

    original_payload_path = target.bundle_dir / "upload_bundle_payload.jsonl"
    subset_source_path = staging_dir / "upload_bundle_payload.browser-safe-subset.jsonl"
    selected_count, selected_bytes = _write_selected_payload_rows(
        source_path=original_payload_path,
        output_path=subset_source_path,
        selected_rows=selected_rows,
    )
    if selected_count <= 0 or selected_bytes <= 0:
        return None

    staged_paths: list[Path] = []
    shard_notes: list[str] = []
    for file_name in ("upload_bundle_overview.md", "upload_bundle_index.json"):
        file_staged_paths, shard_note = _stage_browser_upload_text_file(
            source_path=target.bundle_dir / file_name,
            staging_dir=staging_dir,
            staged_name=file_name,
        )
        staged_paths.extend(file_staged_paths)
        if shard_note:
            shard_notes.append(shard_note)
    payload_staged_paths, payload_shard_note = _stage_browser_upload_text_file(
        source_path=subset_source_path,
        staging_dir=staging_dir,
        staged_name="upload_bundle_payload.jsonl",
    )
    staged_paths.extend(payload_staged_paths)
    if payload_shard_note:
        shard_notes.append(payload_shard_note)

    oversized_text = ", ".join(f"{name} ({size_bytes} bytes)" for name, size_bytes in oversized_files)
    prompt_lines = [
        prompt,
        "",
        "Oracle transport note: browser upload may deliver the logical text files as one synthetic attachment such as `attachments-bundle.txt`.",
        "Oracle transport note: the attached `upload_bundle_payload.jsonl` is a browser-safe starter-pack subset selected from the full local payload using `upload_bundle_index.json` row locators from `root_files`, `starter_pack`, and `per_run_summaries`.",
        "Oracle transport note: artifact `path` values in that trimmed payload stay unchanged, but `payload_row` numbers in `upload_bundle_index.json` still refer to the full local bundle rather than this browser-safe subset.",
        "If you need evidence outside the attached starter-pack subset, request narrow follow-up data instead of asking for the full bundle again.",
        *shard_notes,
        "Read `upload_bundle_overview.md` first, then `upload_bundle_index.json`, and consult the attached starter-pack payload rows by `path` as needed.",
    ]
    note = (
        "Prepared browser-safe Oracle starter-pack upload for oversized bundle files: "
        f"{oversized_text}. Trimmed `upload_bundle_payload.jsonl` to {selected_count} starter-pack rows "
        f"({selected_bytes} bytes) before browser upload."
    )
    return PreparedOracleUploadInputs(
        prompt="\n".join(prompt_lines),
        file_paths=staged_paths,
        note=note,
    )


def _prepare_browser_upload_inputs(
    *,
    target: OracleBenchmarkBundleTarget,
    staging_dir: Path,
) -> PreparedOracleUploadInputs:
    prompt = build_oracle_benchmark_prompt(target=target)
    oversized_files = _oversized_bundle_files(target.bundle_dir)
    if not oversized_files:
        return PreparedOracleUploadInputs(
            prompt=prompt,
            file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
        )

    starter_packet = _prepare_browser_safe_starter_upload_inputs(
        target=target,
        staging_dir=staging_dir,
        prompt=prompt,
        oversized_files=oversized_files,
    )
    if starter_packet is not None:
        return starter_packet

    staged_paths, shard_notes = _copy_or_shard_browser_upload_files(
        bundle_dir=target.bundle_dir,
        staging_dir=staging_dir,
    )
    oversized_text = ", ".join(f"{name} ({size_bytes} bytes)" for name, size_bytes in oversized_files)
    prompt_lines = [
        prompt,
        "",
        "Oracle transport note: browser upload may deliver the logical text files as one synthetic attachment such as `attachments-bundle.txt`.",
        "Oracle transport note: some attached bundle files were split into ordered shards to satisfy Oracle's per-file input limit before browser upload.",
        "Treat any `*.partNNN.*` attachments as the logical contents of the original file concatenated in lexical filename order.",
        *shard_notes,
        "Read `upload_bundle_overview.md` first, then `upload_bundle_index.json`, and consult payload shard rows only as needed.",
    ]
    note = (
        "Prepared sharded Oracle browser upload for oversized bundle files: "
        f"{oversized_text}."
    )
    return PreparedOracleUploadInputs(
        prompt="\n".join(prompt_lines),
        file_paths=staged_paths,
        note=note,
    )


def _oracle_upload_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d_%H.%M.%S")


def _oracle_background_launch_dir(bundle_dir: Path) -> Path:
    parent_dir = bundle_dir / ORACLE_UPLOAD_RUNS_DIR_NAME
    base_name = _oracle_upload_timestamp()
    candidate = parent_dir / base_name
    suffix = 1
    while candidate.exists():
        candidate = parent_dir / f"{base_name}_{suffix:02d}"
        suffix += 1
    return candidate


def _oracle_command(
    *,
    mode: str,
    model: str,
    prompt: str,
    file_paths: list[Path],
) -> list[str]:
    normalized_mode = mode.strip().lower()
    file_arguments = _oracle_file_arguments(file_paths)
    if normalized_mode == "browser":
        command = [
            ORACLE_BROWSER_CMD,
            "--engine",
            "browser",
            "--browser-model-strategy",
            ORACLE_BROWSER_MODEL_STRATEGY,
            "--browser-input-timeout",
            "90s",
            "--browser-reuse-wait",
            ORACLE_BROWSER_REUSE_WAIT,
            "--browser-profile-lock-timeout",
            ORACLE_BROWSER_PROFILE_LOCK_TIMEOUT,
            "--browser-auto-reattach-delay",
            ORACLE_BROWSER_AUTO_REATTACH_DELAY,
            "--browser-auto-reattach-interval",
            ORACLE_BROWSER_AUTO_REATTACH_INTERVAL,
            "--browser-auto-reattach-timeout",
            ORACLE_BROWSER_AUTO_REATTACH_TIMEOUT,
            "--browser-attachments",
            "always",
            "--browser-bundle-files",
            "--model",
            model,
            "-p",
            prompt,
        ]
        chatgpt_url = str(os.environ.get(ORACLE_CHATGPT_URL_ENV) or "").strip()
        if chatgpt_url:
            command.extend(["--chatgpt-url", chatgpt_url])
        for file_argument in file_arguments:
            command.extend(["--file", file_argument])
        return command
    if normalized_mode == "dry-run":
        command = [
            *ORACLE_DRY_RUN_BASE_COMMAND,
            "--model",
            model,
            "-p",
            prompt,
        ]
        for file_argument in file_arguments:
            command.extend(["--file", file_argument])
        return command
    raise ValueError(f"Unsupported Oracle upload mode: {mode}")


def _profile_signal_mtime(profile_dir: Path) -> float:
    candidate_paths = (
        profile_dir / "Default" / "Cookies",
        profile_dir / "Local State",
        profile_dir / "Default" / "Preferences",
    )
    mtimes: list[float] = []
    for path in candidate_paths:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    return max(mtimes) if mtimes else 0.0


def _resolve_oracle_browser_profile_dir(*, env: dict[str, str] | None = None) -> Path:
    source_env = env if env is not None else os.environ
    explicit_profile = str(source_env.get("ORACLE_BROWSER_PROFILE_DIR") or "").strip()
    if explicit_profile:
        return Path(explicit_profile).expanduser()

    current_profile = Path(ORACLE_BROWSER_PROFILE_DIR).expanduser()
    legacy_profile = Path(ORACLE_LEGACY_BROWSER_PROFILE_DIR).expanduser()
    candidates = [current_profile, legacy_profile]
    ranked = sorted(
        ((profile_dir, _profile_signal_mtime(profile_dir)) for profile_dir in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    for profile_dir, signal in ranked:
        if signal > 0:
            return profile_dir
    return current_profile


def _oracle_browser_env() -> dict[str, str]:
    env = dict(os.environ)
    browser_profile_dir = _resolve_oracle_browser_profile_dir(env=env)
    oracle_home_dir = browser_profile_dir.parent
    env.setdefault("ORACLE_HOME_DIR", str(oracle_home_dir))
    env.setdefault("ORACLE_BROWSER_PROFILE_DIR", str(browser_profile_dir))
    env.setdefault("ORACLE_BROWSER_REMOTE_DEBUG_HOST", ORACLE_BROWSER_REMOTE_DEBUG_HOST)
    return env


def _detect_oracle_version() -> str:
    try:
        completed = subprocess.run(
            [ORACLE_BROWSER_CMD, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return ""
    version = str(completed.stdout or completed.stderr or "").strip()
    return version.splitlines()[0].strip() if version else ""


def _read_oracle_upload_bundle_topline(target: OracleBenchmarkBundleTarget) -> dict[str, int]:
    index_path = target.bundle_dir / "upload_bundle_index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    topline = payload.get("topline") if isinstance(payload, dict) else None
    if not isinstance(topline, dict):
        return {}
    counts: dict[str, int] = {}
    for key in ("run_count", "pair_count", "changed_lines_total"):
        value = topline.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            counts[key] = value
            continue
        if isinstance(value, float) and value.is_integer():
            counts[key] = int(value)
    return counts


def _expected_root_aliases(source_root: Path) -> set[str]:
    aliases = {str(source_root).strip().replace("\\", "/")}
    parts = list(source_root.parts)
    for index, part in enumerate(parts):
        if _TIMESTAMP_DIR_RE.fullmatch(part):
            aliases.add("/".join(parts[index:]))
            break
    aliases.add(source_root.as_posix())
    return {alias for alias in aliases if alias}


def _parse_oracle_session_metadata(log_text: str) -> tuple[str, str]:
    matches = list(_ORACLE_SESSION_RE.finditer(log_text))
    if not matches:
        return "", ""
    session_id = matches[-1].group("session_id").strip()
    if not session_id:
        return "", ""
    return session_id, f"oracle session {session_id}"


def _extract_answer_block(log_text: str) -> str:
    marker = "Answer:"
    index = log_text.rfind(marker)
    if index < 0:
        return ""
    return log_text[index + len(marker) :].strip()


def audit_oracle_upload_log(
    *,
    target: OracleBenchmarkBundleTarget,
    log_text: str,
) -> OracleUploadAudit:
    session_id, reattach_command = _parse_oracle_session_metadata(log_text)
    lower_text = log_text.lower()
    answer_block = _extract_answer_block(log_text)

    if answer_block:
        expected_counts = _read_oracle_upload_bundle_topline(target)
        expected_root_aliases = _expected_root_aliases(target.source_root)
        observed_roots = {
            match.group(0).strip().replace("\\", "/")
            for match in _ORACLE_ROOT_REF_RE.finditer(answer_block)
        }
        unexpected_roots = sorted(
            observed_root
            for observed_root in observed_roots
            if not any(
                alias in observed_root or observed_root in alias
                for alias in expected_root_aliases
            )
        )
        if unexpected_roots:
            return OracleUploadAudit(
                status="invalid_grounding",
                status_reason=(
                    "Expected benchmark root "
                    f"{target.source_root}, but Oracle cited {unexpected_roots[0]}."
                ),
                session_id=session_id,
                reattach_command=reattach_command,
            )

        observed_counts: dict[str, int] = {}
        for match in _ORACLE_COUNT_RE.finditer(answer_block):
            observed_counts[match.group("name").lower()] = int(match.group("value"))
        for key, expected_value in expected_counts.items():
            observed_value = observed_counts.get(key)
            if observed_value is not None and observed_value != expected_value:
                return OracleUploadAudit(
                    status="invalid_grounding",
                    status_reason=(
                        f"Expected {key} = {expected_value}, but Oracle reported {key} = {observed_value}."
                    ),
                    session_id=session_id,
                    reattach_command=reattach_command,
                )

        return OracleUploadAudit(
            status="succeeded",
            status_reason="Answer block present and grounded in the local bundle.",
            session_id=session_id,
            reattach_command=reattach_command,
        )

    if (
        "chrome disconnected before completion" in lower_text
        or "assistant response timed out; keeping session running for reattach" in lower_text
    ):
        if reattach_command:
            return OracleUploadAudit(
                status="reattachable",
                status_reason="Oracle reported a recoverable browser/session interruption.",
                session_id=session_id,
                reattach_command=reattach_command,
            )
        return OracleUploadAudit(
            status="failed",
            status_reason="Oracle reported a browser/session interruption without a reattach command.",
        )

    if reattach_command and (
        "a session with the same prompt is already running" in lower_text
        or "rerun with --force to start another run" in lower_text
    ):
        return OracleUploadAudit(
            status="reattachable",
            status_reason="Oracle found an already-running matching session; reattach instead of launching a duplicate.",
            session_id=session_id,
            reattach_command=reattach_command,
        )

    if reattach_command and (
        "session running in background" in lower_text
        or "reattach via:" in lower_text
        or "reattach later with:" in lower_text
    ):
        return OracleUploadAudit(
            status="running",
            status_reason="Oracle session launched and awaiting completion.",
            session_id=session_id,
            reattach_command=reattach_command,
        )

    return OracleUploadAudit(
        status="failed",
        status_reason="Oracle did not produce a grounded answer or recovery path.",
        session_id=session_id,
        reattach_command=reattach_command,
    )


def _oracle_upload_status_path(metadata_path: Path) -> Path:
    return metadata_path.with_name(ORACLE_UPLOAD_STATUS_FILE_NAME)


def _persist_oracle_upload_metadata(
    *,
    metadata_path: Path,
    payload: Mapping[str, Any],
    audit: OracleUploadAudit,
) -> None:
    merged_payload = dict(payload)
    merged_payload["status"] = audit.status
    merged_payload["status_reason"] = audit.status_reason
    merged_payload["session_id"] = audit.session_id
    merged_payload["reattach_command"] = audit.reattach_command
    merged_payload["conversation_url"] = audit.conversation_url
    merged_payload["conversation_id"] = audit.conversation_id
    metadata_path.write_text(
        json.dumps(merged_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _oracle_upload_status_path(metadata_path).write_text(
        json.dumps(
            {
                "status": audit.status,
                "status_reason": audit.status_reason,
                "session_id": audit.session_id,
                "reattach_command": audit.reattach_command,
                "conversation_url": audit.conversation_url,
                "conversation_id": audit.conversation_id,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_oracle_upload_log(
    *,
    log_path: Path,
    note: str,
    browser_profile_dir: Path | None,
    command: list[str],
    stdout: str,
    stderr: str,
) -> None:
    parts: list[str] = []
    if note:
        parts.append(note.rstrip())
    if browser_profile_dir is not None:
        parts.append(f"Oracle browser profile: {browser_profile_dir}")
    parts.append(f"Oracle command: {shlex.join(command)}")
    if stdout:
        parts.append(stdout.rstrip())
    if stderr:
        parts.append(stderr.rstrip())
    log_text = "\n".join(part for part in parts if part).rstrip()
    log_path.write_text(log_text + ("\n" if log_text else ""), encoding="utf-8")


def _read_log_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _poll_oracle_background_audit(
    *,
    target: OracleBenchmarkBundleTarget,
    log_path: Path,
) -> OracleUploadAudit:
    deadline = time.monotonic() + ORACLE_BACKGROUND_SESSION_POLL_SECONDS
    latest_log_text = ""
    while time.monotonic() < deadline:
        latest_log_text = _read_log_text(log_path)
        audit = audit_oracle_upload_log(target=target, log_text=latest_log_text)
        if audit.session_id or audit.status in {"succeeded", "invalid_grounding", "reattachable"}:
            return audit
        time.sleep(ORACLE_BACKGROUND_SESSION_POLL_INTERVAL_SECONDS)
    return audit_oracle_upload_log(target=target, log_text=latest_log_text)


def _background_process_still_running(proc: subprocess.Popen[str]) -> bool:
    try:
        return proc.poll() is None
    except Exception:
        return False


def _oracle_sessions_dir(browser_profile_dir: Path | None) -> Path:
    if browser_profile_dir is not None:
        return browser_profile_dir.parent / "sessions"
    return Path(ORACLE_HOME_DIR).expanduser() / "sessions"


def _parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_oracle_conversation_url(
    raw_url: str,
    *,
    conversation_id: str = "",
) -> str:
    normalized_url = str(raw_url or "").strip()
    normalized_id = str(conversation_id or "").strip()
    if normalized_url in _ORACLE_CHATGPT_ROOT_URLS:
        return f"https://chatgpt.com/c/{normalized_id}" if normalized_id else ""
    return normalized_url


def _find_matching_oracle_session_snapshot(
    *,
    prompt: str,
    cwd: Path,
    sessions_dir: Path,
    created_after: datetime,
) -> OracleSessionSnapshot | None:
    if not sessions_dir.is_dir():
        return None
    matches: list[tuple[datetime, OracleSessionSnapshot]] = []
    for meta_path in sessions_dir.glob("*/meta.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        created_at_text = str(payload.get("createdAt") or "")
        created_at = _parse_iso_datetime(created_at_text)
        if created_at is None or created_at < created_after:
            continue
        options_payload = payload.get("options")
        if not isinstance(options_payload, dict):
            continue
        session_prompt = str(options_payload.get("prompt") or "")
        if session_prompt != prompt:
            continue
        session_cwd = str(payload.get("cwd") or "")
        if session_cwd and Path(session_cwd).resolve(strict=False) != cwd.resolve(strict=False):
            continue
        browser_payload = payload.get("browser")
        runtime_payload = browser_payload.get("runtime") if isinstance(browser_payload, dict) else None
        conversation_url = (
            str(runtime_payload.get("tabUrl") or "")
            if isinstance(runtime_payload, dict)
            else ""
        )
        conversation_id = (
            str(runtime_payload.get("conversationId") or "")
            if isinstance(runtime_payload, dict)
            else ""
        )
        conversation_url = _normalize_oracle_conversation_url(
            conversation_url,
            conversation_id=conversation_id,
        )
        snapshot = OracleSessionSnapshot(
            session_id=str(payload.get("id") or ""),
            status=str(payload.get("status") or ""),
            prompt=session_prompt,
            created_at=created_at_text,
            conversation_url=conversation_url,
            conversation_id=conversation_id,
        )
        if snapshot.session_id:
            matches.append((created_at, snapshot))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _read_oracle_session_snapshot_by_id(
    *,
    session_id: str,
    sessions_dir: Path,
) -> OracleSessionSnapshot | None:
    normalized_id = str(session_id or "").strip()
    if not normalized_id:
        return None
    meta_path = sessions_dir / normalized_id / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    options_payload = payload.get("options")
    session_prompt = (
        str(options_payload.get("prompt") or "")
        if isinstance(options_payload, dict)
        else ""
    )
    browser_payload = payload.get("browser")
    runtime_payload = browser_payload.get("runtime") if isinstance(browser_payload, dict) else None
    conversation_url = (
        str(
            (browser_payload.get("conversationUrl") if isinstance(browser_payload, dict) else "")
            or (runtime_payload.get("tabUrl") if isinstance(runtime_payload, dict) else "")
            or ""
        )
    )
    conversation_id = (
        str(
            (browser_payload.get("conversationId") if isinstance(browser_payload, dict) else "")
            or (runtime_payload.get("conversationId") if isinstance(runtime_payload, dict) else "")
            or ""
        )
    )
    conversation_url = _normalize_oracle_conversation_url(
        conversation_url,
        conversation_id=conversation_id,
    )
    return OracleSessionSnapshot(
        session_id=str(payload.get("id") or normalized_id),
        status=str(payload.get("status") or ""),
        prompt=session_prompt,
        created_at=str(payload.get("createdAt") or ""),
        conversation_url=conversation_url,
        conversation_id=conversation_id,
    )


def start_oracle_benchmark_upload_background(
    *,
    target: OracleBenchmarkBundleTarget,
    mode: str,
    model: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> OracleBackgroundUploadLaunch:
    normalized_mode = mode.strip().lower()
    resolved_model = resolve_oracle_benchmark_model(model)
    launch_started_at = datetime.now(timezone.utc)
    launch_dir = _oracle_background_launch_dir(target.bundle_dir)
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
    metadata_path = launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME

    note = ""
    session_prompt = build_oracle_benchmark_prompt(target=target)
    if normalized_mode == "browser":
        oversized_files = _oversized_bundle_files(target.bundle_dir)
        if oversized_files:
            staging_dir = launch_dir / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            prepared = _prepare_browser_upload_inputs(
                target=target,
                staging_dir=staging_dir,
            )
            command = _oracle_command(
                mode=normalized_mode,
                model=resolved_model,
                prompt=prepared.prompt,
                file_paths=prepared.file_paths,
            )
            note = prepared.note
            session_prompt = prepared.prompt
        else:
            command = _oracle_command(
                mode=normalized_mode,
                model=resolved_model,
                prompt=session_prompt,
                file_paths=[
                    target.bundle_dir / file_name
                    for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES
                ],
            )
    elif normalized_mode == "dry-run":
        command = _oracle_command(
            mode=normalized_mode,
            model=resolved_model,
            prompt=session_prompt,
            file_paths=[
                target.bundle_dir / file_name
                for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES
            ],
        )
    else:
        raise ValueError(f"Unsupported Oracle upload mode: {mode}")

    env = _oracle_browser_env() if normalized_mode == "browser" else None
    browser_profile_dir = (
        Path(str(env.get("ORACLE_BROWSER_PROFILE_DIR") or "")).expanduser()
        if env is not None and str(env.get("ORACLE_BROWSER_PROFILE_DIR") or "").strip()
        else None
    )
    oracle_version = _detect_oracle_version()
    with log_path.open("w", encoding="utf-8") as log_handle:
        if note:
            log_handle.write(f"{note}\n")
        if browser_profile_dir is not None:
            log_handle.write(f"Oracle browser profile: {browser_profile_dir}\n")
        log_handle.write(f"Oracle command: {shlex.join(command)}\n")
        log_handle.flush()
        proc = popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            cwd=str(Path.cwd()),
            start_new_session=True,
        )
    metadata_payload = {
        "bundle_dir": str(target.bundle_dir),
        "source_root": str(target.source_root),
        "scope": target.scope,
        "mode": normalized_mode,
        "model": resolved_model,
        "prompt": session_prompt,
        "pid": int(proc.pid),
        "command": command,
        "log_path": str(log_path),
        "metadata_path": str(metadata_path),
        "status_path": str(_oracle_upload_status_path(metadata_path)),
        "started_at": _oracle_upload_timestamp(),
        "launch_started_at_utc": launch_started_at.isoformat(),
        "note": note,
        "browser_profile_dir": str(browser_profile_dir) if browser_profile_dir else "",
        "oracle_version": oracle_version,
    }
    audit = _poll_oracle_background_audit(target=target, log_path=log_path)
    session_snapshot = _find_matching_oracle_session_snapshot(
        prompt=session_prompt,
        cwd=Path.cwd(),
        sessions_dir=_oracle_sessions_dir(browser_profile_dir),
        created_after=launch_started_at,
    )
    if session_snapshot is not None:
        if not audit.session_id:
            audit = OracleUploadAudit(
                status=audit.status,
                status_reason=audit.status_reason,
                session_id=session_snapshot.session_id,
                reattach_command=f"oracle session {session_snapshot.session_id}",
                conversation_url=session_snapshot.conversation_url,
                conversation_id=session_snapshot.conversation_id,
            )
        if audit.status == "failed" and session_snapshot.status == "running":
            audit = OracleUploadAudit(
                status="running",
                status_reason="Oracle session is running; session store metadata is available.",
                session_id=session_snapshot.session_id,
                reattach_command=f"oracle session {session_snapshot.session_id}",
                conversation_url=session_snapshot.conversation_url,
                conversation_id=session_snapshot.conversation_id,
            )
    if audit.session_id and not audit.conversation_url:
        session_snapshot_by_id = _read_oracle_session_snapshot_by_id(
            session_id=audit.session_id,
            sessions_dir=_oracle_sessions_dir(browser_profile_dir),
        )
        if session_snapshot_by_id is not None and session_snapshot_by_id.conversation_url:
            audit = OracleUploadAudit(
                status=audit.status,
                status_reason=audit.status_reason,
                session_id=audit.session_id,
                reattach_command=audit.reattach_command,
                conversation_url=session_snapshot_by_id.conversation_url,
                conversation_id=session_snapshot_by_id.conversation_id,
            )
    if audit.status == "failed" and _background_process_still_running(proc):
        audit = OracleUploadAudit(
            status="running",
            status_reason="Oracle process is still running; awaiting session hint or answer.",
            session_id=audit.session_id,
            reattach_command=audit.reattach_command,
            conversation_url=audit.conversation_url,
            conversation_id=audit.conversation_id,
        )
    _persist_oracle_upload_metadata(
        metadata_path=metadata_path,
        payload=metadata_payload,
        audit=audit,
    )
    return OracleBackgroundUploadLaunch(
        mode=normalized_mode,
        model=resolved_model,
        command=command,
        bundle_dir=target.bundle_dir,
        launch_dir=launch_dir,
        log_path=log_path,
        metadata_path=metadata_path,
        pid=int(proc.pid),
        note=note,
        browser_profile_dir=browser_profile_dir,
        oracle_version=oracle_version,
        status=audit.status,
        status_reason=audit.status_reason,
        session_id=audit.session_id,
        reattach_command=audit.reattach_command,
        conversation_url=audit.conversation_url,
        conversation_id=audit.conversation_id,
    )


def run_oracle_benchmark_upload(
    *,
    target: OracleBenchmarkBundleTarget,
    mode: str,
    model: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> OracleUploadResult:
    normalized_mode = mode.strip().lower()
    resolved_model = resolve_oracle_benchmark_model(model)
    oversized_files = (
        _oversized_bundle_files(target.bundle_dir)
        if normalized_mode == "dry-run"
        else []
    )
    if oversized_files:
        browser_command = _oracle_command(
            mode="browser",
            model=resolved_model,
            prompt=build_oracle_benchmark_prompt(target=target),
            file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
        )
        oversized_text = ", ".join(
            f"{name} ({size_bytes} bytes)" for name, size_bytes in oversized_files
        )
        return OracleUploadResult(
            success=True,
            mode=normalized_mode,
            command=browser_command,
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout=(
                "Local dry-run preview only. Oracle inline dry-run rejects files over "
                f"{ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES} bytes, so no Oracle subprocess "
                f"was started. Oversized files: {oversized_text}. Use browser mode for "
                "the real upload."
            ),
            stderr="",
            oracle_version=_detect_oracle_version(),
        )

    if normalized_mode == "browser":
        oracle_version = _detect_oracle_version()
        launch_started_at = datetime.now(timezone.utc)
        launch_dir = _oracle_background_launch_dir(target.bundle_dir)
        launch_dir.mkdir(parents=True, exist_ok=True)
        log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
        metadata_path = launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME
        staging_dir = launch_dir / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        prepared = _prepare_browser_upload_inputs(
            target=target,
            staging_dir=staging_dir,
        )
        command = _oracle_command(
            mode=normalized_mode,
            model=resolved_model,
            prompt=prepared.prompt,
            file_paths=prepared.file_paths,
        )
        env = _oracle_browser_env()
        browser_profile_dir = (
            Path(str(env.get("ORACLE_BROWSER_PROFILE_DIR") or "")).expanduser()
            if str(env.get("ORACLE_BROWSER_PROFILE_DIR") or "").strip()
            else None
        )
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        stdout = completed.stdout or ""
        if prepared.note:
            stdout = f"{prepared.note}\n{stdout}" if stdout else prepared.note
        combined_log = "\n".join(part for part in (stdout, completed.stderr or "") if part)
        audit = audit_oracle_upload_log(target=target, log_text=combined_log)
        session_snapshot = _find_matching_oracle_session_snapshot(
            prompt=prepared.prompt,
            cwd=Path.cwd(),
            sessions_dir=_oracle_sessions_dir(browser_profile_dir),
            created_after=launch_started_at,
        )
        if session_snapshot is not None:
            if not audit.session_id:
                audit = OracleUploadAudit(
                    status=audit.status,
                    status_reason=audit.status_reason,
                    session_id=session_snapshot.session_id,
                    reattach_command=f"oracle session {session_snapshot.session_id}",
                    conversation_url=session_snapshot.conversation_url,
                    conversation_id=session_snapshot.conversation_id,
                )
            elif not audit.conversation_url and session_snapshot.conversation_url:
                audit = OracleUploadAudit(
                    status=audit.status,
                    status_reason=audit.status_reason,
                    session_id=audit.session_id,
                    reattach_command=audit.reattach_command,
                    conversation_url=session_snapshot.conversation_url,
                    conversation_id=session_snapshot.conversation_id,
                )
        if audit.session_id and not audit.conversation_url:
            session_snapshot_by_id = _read_oracle_session_snapshot_by_id(
                session_id=audit.session_id,
                sessions_dir=_oracle_sessions_dir(browser_profile_dir),
            )
            if session_snapshot_by_id is not None and session_snapshot_by_id.conversation_url:
                audit = OracleUploadAudit(
                    status=audit.status,
                    status_reason=audit.status_reason,
                    session_id=audit.session_id,
                    reattach_command=audit.reattach_command,
                    conversation_url=session_snapshot_by_id.conversation_url,
                    conversation_id=session_snapshot_by_id.conversation_id,
                )
        _write_oracle_upload_log(
            log_path=log_path,
            note=prepared.note,
            browser_profile_dir=browser_profile_dir,
            command=command,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
        metadata_payload = {
            "bundle_dir": str(target.bundle_dir),
            "source_root": str(target.source_root),
            "scope": target.scope,
            "mode": normalized_mode,
            "model": resolved_model,
            "prompt": prepared.prompt,
            "pid": None,
            "command": command,
            "log_path": str(log_path),
            "metadata_path": str(metadata_path),
            "status_path": str(_oracle_upload_status_path(metadata_path)),
            "started_at": _oracle_upload_timestamp(),
            "launch_started_at_utc": launch_started_at.isoformat(),
            "note": prepared.note,
            "browser_profile_dir": str(browser_profile_dir) if browser_profile_dir else "",
            "oracle_version": oracle_version,
            "returncode": int(completed.returncode),
            "launch_dir": str(launch_dir),
        }
        _persist_oracle_upload_metadata(
            metadata_path=metadata_path,
            payload=metadata_payload,
            audit=audit,
        )
        return OracleUploadResult(
            success=completed.returncode == 0 and audit.status == "succeeded",
            mode=normalized_mode,
            command=command,
            bundle_dir=target.bundle_dir,
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=completed.stderr or "",
            oracle_version=oracle_version,
            status=audit.status,
            status_reason=audit.status_reason,
            session_id=audit.session_id,
            reattach_command=audit.reattach_command,
            conversation_url=audit.conversation_url,
            conversation_id=audit.conversation_id,
        )

    command = _oracle_command(
        mode=normalized_mode,
        model=resolved_model,
        prompt=build_oracle_benchmark_prompt(target=target),
        file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
    )
    oracle_version = _detect_oracle_version()
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return OracleUploadResult(
        success=completed.returncode == 0,
        mode=normalized_mode,
        command=command,
        bundle_dir=target.bundle_dir,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        oracle_version=oracle_version,
    )
