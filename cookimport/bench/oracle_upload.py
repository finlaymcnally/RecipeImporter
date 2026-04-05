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

from cookimport.config.runtime_support import (
    resolve_oracle_background_session_poll_interval_seconds,
    resolve_oracle_background_session_poll_seconds,
    resolve_oracle_browser_shard_target_bytes,
)

ORACLE_BROWSER_CMD = "/home/mcnal/.local/bin/oracle"
ORACLE_BROWSER_CHROME_PATH = "/home/mcnal/.local/bin/chromium-oracle-auto"
ORACLE_BROWSER_REMOTE_DEBUG_HOST = "127.0.0.1"
ORACLE_BROWSER_MODEL_STRATEGY = "select"
ORACLE_HOME_DIR = str(Path.home() / ".local" / "share" / "oracle")
ORACLE_BROWSER_PROFILE_DIR = str(Path(ORACLE_HOME_DIR) / "browser-profile")
ORACLE_MODEL_LANE_INSTANT = "instant"
ORACLE_MODEL_LANE_PRO = "pro"
ORACLE_MODEL_LANE_THINKING = "thinking"
_ORACLE_MODEL_SELECTOR_ALIASES = {
    "instant": ORACLE_MODEL_LANE_INSTANT,
    "test": ORACLE_MODEL_LANE_INSTANT,
    "fast": ORACLE_MODEL_LANE_INSTANT,
    "smoke": ORACLE_MODEL_LANE_INSTANT,
    "pro": ORACLE_MODEL_LANE_PRO,
    "genuine": ORACLE_MODEL_LANE_PRO,
    "review": ORACLE_MODEL_LANE_PRO,
    "thinking": ORACLE_MODEL_LANE_THINKING,
    "deep-review": ORACLE_MODEL_LANE_THINKING,
    "deep_review": ORACLE_MODEL_LANE_THINKING,
}
ORACLE_INSTANT_DEFAULT_MODEL = os.environ.get("ORACLE_INSTANT_MODEL", "gpt-5.3")
ORACLE_PRO_DEFAULT_MODEL = os.environ.get("ORACLE_PRO_MODEL", "gpt-5-pro")
ORACLE_THINKING_DEFAULT_MODEL = os.environ.get("ORACLE_THINKING_MODEL", "")
ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES = 1_000_000
ORACLE_BROWSER_SHARD_TARGET_BYTES = resolve_oracle_browser_shard_target_bytes()
ORACLE_BROWSER_REUSE_WAIT = "5m"
ORACLE_BROWSER_PROFILE_LOCK_TIMEOUT = "30m"
ORACLE_BROWSER_AUTO_REATTACH_DELAY = "30s"
ORACLE_BROWSER_AUTO_REATTACH_INTERVAL = "30s"
ORACLE_BROWSER_AUTO_REATTACH_TIMEOUT = "120s"
ORACLE_BACKGROUND_SESSION_POLL_SECONDS = resolve_oracle_background_session_poll_seconds()
ORACLE_BACKGROUND_SESSION_POLL_INTERVAL_SECONDS = (
    resolve_oracle_background_session_poll_interval_seconds()
)
ORACLE_CHATGPT_URL_ENV = "COOKIMPORT_ORACLE_CHATGPT_URL"
ORACLE_DEFAULT_CHATGPT_URL = "https://chatgpt.com/"
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
ORACLE_REVIEW_PROFILE_QUALITY = "quality"
ORACLE_REVIEW_PROFILE_TOKEN = "token"
BENCHMARK_UPLOAD_BUNDLE_DIR_NAME = "upload_bundle_v1"
BENCHMARK_UPLOAD_BUNDLE_OVERVIEW_FILE_NAME = "overview.md"
BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME = "index.json"
BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME = "payload.json"
BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES = (
    BENCHMARK_UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
    BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
    BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
)
BENCHMARK_UPLOAD_BUNDLE_REVIEW_DIR_NAMES = (
    ORACLE_REVIEW_PROFILE_QUALITY,
    ORACLE_REVIEW_PROFILE_TOKEN,
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
ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "benchmark.oracle-upload.token.prompt.md"
)
ORACLE_BENCHMARK_QUALITY_PROMPT_TEMPLATE_FALLBACK = "\n".join(
    [
        "{{HELPER_BANNER}}",
        "You are the quality lane for a benchmark review of the local `cookimport` CLI.",
        "The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.",
        "Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.",
        "Start with `overview.md`, then `index.json`, and use `payload.json` only as needed.",
        "The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.",
        "Your job is to identify the shortest concrete path from the current benchmark quality toward `>95%`.",
        "Treat token spend as secondary unless it is directly blocking the best quality fix.",
        "The current anchor metrics are already summarized in `overview.md`; use them instead of re-deriving the topline from scratch.",
        "Prioritize remaining label-choice, routing, and outside-span mistakes, especially `KNOWLEDGE` versus `OTHER`.",
        "This is a solo local project. Do not spend time on organizational process or enterprise reporting suggestions.",
        "Follow-up data is available locally. Ask for narrow follow-up artifacts whenever they would materially sharpen the next quality-improvement step.",
        "Return exactly four sections: `Top blockers to 95%`, `Likely fix buckets`, `Immediate experiments`, and `Requested follow-up data`.",
        "In `Requested follow-up data`, either write `None` or use the existing parse-friendly Ask format from the benchmark review contract.",
        "Keep the response factual and grounded in the attached packet. Do not ask for a rerun unless the packet is missing evidence required to choose the next step.",
    ]
)
ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_FALLBACK = "\n".join(
    [
        "{{HELPER_BANNER}}",
        "You are the token lane for a benchmark review of the local `cookimport` CLI.",
        "The logical contents come from an existing `upload_bundle_v1` benchmark package, not raw repo source code.",
        "Oracle browser transport may package those logical files into one synthetic text attachment such as `attachments-bundle.txt`.",
        "Start with `overview.md`, then `index.json`, and use `payload.json` only as needed.",
        "The bundle scope is `{{BUNDLE_SCOPE}}` and the benchmark root is `{{BENCHMARK_ROOT}}`.",
        "Your job is to identify the sharpest token-spend reductions that preserve at least the current benchmark quality.",
        "Treat proposals that are likely to undo the current quality gains as unacceptable unless the packet shows a compensating safer path.",
        "The current anchor spend metrics are already summarized in `overview.md`; use them instead of re-deriving the topline from scratch.",
        "Prioritize recurring stage spend, wrapper overhead, prompt/readback waste, and review-packet waste.",
        "Do not default to generic smaller-model advice unless the attached evidence shows that a stage is clearly overpowered for its job.",
        "This is a solo local project. Prefer concrete prompt, packet, and worker-contract changes over enterprise observability suggestions.",
        "Follow-up data is available locally. Ask for narrow follow-up artifacts only when the attached packet is insufficient to rank the best low-risk spend cuts.",
        "Return exactly four sections: `Top spend sinks`, `Likely waste buckets`, `Lowest-risk cuts`, and `Requested follow-up data`.",
        "In `Requested follow-up data`, either write `None` or use the existing parse-friendly Ask format from the benchmark review contract.",
        "Keep the response factual and grounded in the attached packet. Do not ask for a rerun unless the packet is missing evidence required to choose the next step.",
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
class OracleBenchmarkReviewProfile:
    profile_id: str
    display_name: str
    prompt_template_path: Path
    prompt_template_fallback: str
    lane_brief_file_name: str
    payload_paths: tuple[str, ...]


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
    review_profile: str = ""
    review_profile_display_name: str = ""
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
    review_profile: str = ""
    review_profile_display_name: str = ""
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


ORACLE_BENCHMARK_REVIEW_PROFILES: tuple[OracleBenchmarkReviewProfile, ...] = (
    OracleBenchmarkReviewProfile(
        profile_id=ORACLE_REVIEW_PROFILE_QUALITY,
        display_name="Quality",
        prompt_template_path=ORACLE_BENCHMARK_PROMPT_TEMPLATE_PATH,
        prompt_template_fallback=ORACLE_BENCHMARK_QUALITY_PROMPT_TEMPLATE_FALLBACK,
        lane_brief_file_name="oracle_quality_focus.md",
        payload_paths=(
            "codex-exec/run_manifest.json",
            "codex-exec/eval_report.json",
            "codex-exec/prompts/prompt_type_samples_from_full_prompt_log.md",
            "vanilla/run_manifest.json",
            "vanilla/eval_report.json",
            "_upload_bundle_derived/root/comparison_summary.json",
            "_upload_bundle_derived/root/per_recipe_or_per_span_breakdown.json",
            "_upload_bundle_derived/root/01_recipe_triage.packet.jsonl",
            "_upload_bundle_derived/root/net_error_blame_summary.json",
            "_upload_bundle_derived/root/config_version_metadata.json",
            "_upload_bundle_derived/root/explicit_escalation_changed_lines.packet.jsonl",
            "_upload_bundle_derived/root/group_high_level_packet.json",
        ),
    ),
    OracleBenchmarkReviewProfile(
        profile_id=ORACLE_REVIEW_PROFILE_TOKEN,
        display_name="Token",
        prompt_template_path=ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_PATH,
        prompt_template_fallback=ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_FALLBACK,
        lane_brief_file_name="oracle_token_focus.md",
        payload_paths=(
            "codex-exec/run_manifest.json",
            "codex-exec/prompt_budget_summary.json",
            "codex-exec/prompts/prompt_type_samples_from_full_prompt_log.md",
            "_upload_bundle_derived/root/comparison_summary.json",
            "_upload_bundle_derived/root/net_error_blame_summary.json",
            "_upload_bundle_derived/root/config_version_metadata.json",
            "_upload_bundle_derived/root/group_high_level_packet.json",
            "_upload_bundle_derived/root/process_manifest.json",
            "_upload_bundle_derived/starter_pack_v1/02_call_inventory.jsonl",
            "_upload_bundle_derived/starter_pack_v1/04_warning_and_trace_summary.json",
        ),
    ),
)


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


def _normalize_review_profile_name(value: str | None) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    if normalized in {"", "default"}:
        return ORACLE_REVIEW_PROFILE_QUALITY
    return normalized


def resolve_oracle_benchmark_review_profile(
    review_profile: str | None = None,
) -> OracleBenchmarkReviewProfile:
    normalized = _normalize_review_profile_name(review_profile)
    for profile in ORACLE_BENCHMARK_REVIEW_PROFILES:
        if profile.profile_id == normalized:
            return profile
    valid = ", ".join(profile.profile_id for profile in ORACLE_BENCHMARK_REVIEW_PROFILES)
    raise ValueError(f"Unsupported Oracle benchmark review profile: {review_profile!r} (expected one of: {valid}).")


def resolve_oracle_benchmark_review_profiles(
    review_profile: str | None = None,
) -> list[OracleBenchmarkReviewProfile]:
    normalized = _normalize_review_profile_name(review_profile)
    if normalized == "all":
        return list(ORACLE_BENCHMARK_REVIEW_PROFILES)
    return [resolve_oracle_benchmark_review_profile(normalized)]


def _current_profile_prompt_template(
    profile: OracleBenchmarkReviewProfile,
) -> tuple[Path, str]:
    if profile.profile_id == ORACLE_REVIEW_PROFILE_QUALITY:
        return (
            ORACLE_BENCHMARK_PROMPT_TEMPLATE_PATH,
            ORACLE_BENCHMARK_QUALITY_PROMPT_TEMPLATE_FALLBACK,
        )
    if profile.profile_id == ORACLE_REVIEW_PROFILE_TOKEN:
        return (
            ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_PATH,
            ORACLE_BENCHMARK_TOKEN_PROMPT_TEMPLATE_FALLBACK,
        )
    return profile.prompt_template_path, profile.prompt_template_fallback


def _missing_bundle_files(bundle_dir: Path) -> list[str]:
    if _bundle_has_lane_layout(bundle_dir):
        return []
    missing: list[str] = []
    for review_dir_name in BENCHMARK_UPLOAD_BUNDLE_REVIEW_DIR_NAMES:
        review_dir = bundle_dir / review_dir_name
        for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
            if not (review_dir / file_name).is_file():
                missing.append(f"{review_dir_name}/{file_name}")
    return missing


def oracle_benchmark_review_packet_dir(bundle_dir: Path, review_profile: str | None) -> Path:
    normalized = _normalize_review_profile_name(review_profile)
    if normalized == "all":
        normalized = ORACLE_REVIEW_PROFILE_QUALITY
    return bundle_dir / normalized


def oracle_upload_runs_dir(bundle_dir: Path) -> Path:
    return bundle_dir.parent / ORACLE_UPLOAD_RUNS_DIR_NAME


def _bundle_has_lane_layout(bundle_dir: Path) -> bool:
    for review_dir_name in BENCHMARK_UPLOAD_BUNDLE_REVIEW_DIR_NAMES:
        review_dir = bundle_dir / review_dir_name
        if not review_dir.is_dir():
            return False
        for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
            if not (review_dir / file_name).is_file():
                return False
    return True


def oracle_benchmark_review_packet_file(
    bundle_dir: Path,
    review_profile: str | None,
    file_name: str,
) -> Path:
    return oracle_benchmark_review_packet_dir(bundle_dir, review_profile) / file_name


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


def build_oracle_benchmark_prompt(
    *,
    target: OracleBenchmarkBundleTarget,
    review_profile: str | None = None,
) -> str:
    profile = resolve_oracle_benchmark_review_profile(review_profile)
    template_path, template_fallback = _current_profile_prompt_template(profile)
    return _render_oracle_benchmark_prompt_template(
        path=template_path,
        fallback=template_fallback,
        replacements={
            "{{HELPER_BANNER}}": _oracle_benchmark_helper_banner(),
            "{{BUNDLE_SCOPE}}": target.scope,
            "{{BENCHMARK_ROOT}}": str(target.source_root),
            "{{REVIEW_PROFILE}}": profile.profile_id,
            "{{REVIEW_PROFILE_DISPLAY_NAME}}": profile.display_name,
            "{{LANE_BRIEF_FILE}}": profile.lane_brief_file_name,
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


def _resolve_oracle_instant_model(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    return str(source_env.get("ORACLE_INSTANT_MODEL") or ORACLE_INSTANT_DEFAULT_MODEL).strip()


def _resolve_oracle_pro_model(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    return str(source_env.get("ORACLE_PRO_MODEL") or ORACLE_PRO_DEFAULT_MODEL).strip()


def _resolve_oracle_thinking_model(*, env: Mapping[str, str] | None = None) -> str:
    source_env = env if env is not None else os.environ
    return str(source_env.get("ORACLE_THINKING_MODEL") or ORACLE_THINKING_DEFAULT_MODEL).strip()


def normalize_oracle_model_selector(model: str | None) -> str:
    cleaned = str(model or "").strip()
    if not cleaned:
        return ""
    return _ORACLE_MODEL_SELECTOR_ALIASES.get(cleaned.lower(), cleaned)


def resolve_oracle_benchmark_model(
    model: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    explicit_model = normalize_oracle_model_selector(model)
    if explicit_model:
        return explicit_model
    if oracle_test_helper_enabled(env=env):
        return ORACLE_MODEL_LANE_INSTANT
    return ORACLE_MODEL_LANE_PRO


def normalize_oracle_browser_model(
    model: str | None,
    *,
    env: Mapping[str, str] | None = None,
) -> str:
    cleaned = normalize_oracle_model_selector(model)
    if not cleaned:
        return ""
    if cleaned == ORACLE_MODEL_LANE_INSTANT:
        return _resolve_oracle_instant_model(env=env)
    if cleaned == ORACLE_MODEL_LANE_PRO:
        return _resolve_oracle_pro_model(env=env)
    if cleaned == ORACLE_MODEL_LANE_THINKING:
        resolved = _resolve_oracle_thinking_model(env=env)
        if resolved:
            return resolved
        raise ValueError(
            "Oracle thinking lane requested but no thinking model is configured. "
            "Set ORACLE_THINKING_MODEL or pass a literal --model value."
        )
    return cleaned


def _resolve_oracle_launch_model(
    *,
    mode: str,
    model: str,
    env: Mapping[str, str] | None = None,
) -> str:
    cleaned = str(model).strip()
    if not cleaned:
        return ""
    if mode.strip().lower() == "browser":
        return normalize_oracle_browser_model(cleaned, env=env)
    return normalize_oracle_browser_model(cleaned, env=env)


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


def _load_json_object_path(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return float(number)


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    rows: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows


def _format_metric(value: Any, *, digits: int = 6) -> str:
    number = _coerce_float(value)
    if number is None:
        return "unavailable"
    return f"{number:.{digits}f}"


def _format_int_metric(value: Any) -> str:
    try:
        if value is None:
            return "unavailable"
        return f"{int(value)}"
    except (TypeError, ValueError):
        return "unavailable"


def _read_comparison_payload(target: OracleBenchmarkBundleTarget) -> dict[str, Any]:
    return _load_json_object_path(target.source_root / "codex_vs_vanilla_comparison.json")


def _read_prompt_budget_payload(target: OracleBenchmarkBundleTarget) -> dict[str, Any]:
    return _load_json_object_path(target.source_root / "codex-exec" / "prompt_budget_summary.json")


def _build_quality_lane_brief(
    *,
    target: OracleBenchmarkBundleTarget,
    profile: OracleBenchmarkReviewProfile,
    missing_paths: list[str],
) -> str:
    index_payload = _read_oracle_upload_bundle_index_payload(
        target.bundle_dir,
        review_profile=profile.profile_id,
    ) or {}
    analysis_payload = index_payload.get("analysis") if isinstance(index_payload, dict) else {}
    analysis_payload = analysis_payload if isinstance(analysis_payload, dict) else {}
    comparison_payload = _read_comparison_payload(target)
    metrics_payload = comparison_payload.get("metrics") if isinstance(comparison_payload, dict) else {}
    codex_metrics = metrics_payload.get("codex-exec") if isinstance(metrics_payload, dict) else {}
    codex_metrics = codex_metrics if isinstance(codex_metrics, dict) else {}
    structure_report = analysis_payload.get("structure_label_report")
    structure_report = structure_report if isinstance(structure_report, dict) else {}
    slices_payload = structure_report.get("slices")
    slices_payload = slices_payload if isinstance(slices_payload, dict) else {}
    nonrecipe_slice = slices_payload.get("nonrecipe_core")
    nonrecipe_slice = nonrecipe_slice if isinstance(nonrecipe_slice, dict) else {}
    active_recipe_span = (index_payload.get("topline") or {}).get("active_recipe_span_breakout")
    active_recipe_span = active_recipe_span if isinstance(active_recipe_span, dict) else {}
    top_confusions = analysis_payload.get("top_confusion_deltas")
    top_confusions = top_confusions if isinstance(top_confusions, list) else []
    top_confusion_row = top_confusions[0] if top_confusions and isinstance(top_confusions[0], dict) else {}

    lines = [
        "# Oracle Quality Focus",
        "",
        f"- Review profile: `{profile.profile_id}`",
        f"- Benchmark root: `{target.source_root}`",
        f"- Current strict_accuracy: `{_format_metric(codex_metrics.get('strict_accuracy'))}`",
        f"- Current macro_f1_excluding_other: `{_format_metric(codex_metrics.get('macro_f1_excluding_other'))}`",
        f"- structure_core f1 avg: `{_format_metric(((slices_payload.get('structure_core') or {}) if isinstance(slices_payload.get('structure_core'), dict) else {}).get('codex_f1_avg'))}`",
        f"- nonrecipe_core f1 avg: `{_format_metric(nonrecipe_slice.get('codex_f1_avg'))}`",
        f"- boundary exact ratio: `{_format_metric((structure_report.get('boundary') or {}).get('codex_exact_ratio_avg'))}`",
        f"- outside share of scored lines: `{_format_metric(active_recipe_span.get('outside_share_of_scored_lines'))}`",
        (
            f"- dominant confusion family: `{top_confusion_row.get('gold_label', 'unavailable')}` -> "
            f"`{top_confusion_row.get('pred_label', 'unavailable')}`"
        ),
        "",
        "This packet is intentionally quality-first. It includes eval summaries, prompt samples, triage, per-recipe breakdown, net-error blame, and explicit-escalation changed-line evidence.",
        "It intentionally omits the heaviest raw wrong-line context and full changed-line dumps on turn 1. Request narrow follow-up data if the next concrete quality fix cannot be chosen from this packet.",
    ]
    if missing_paths:
        lines.extend(
            [
                "",
                "Missing requested payload paths in this bundle:",
                *[f"- `{path}`" for path in missing_paths],
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_token_lane_brief(
    *,
    target: OracleBenchmarkBundleTarget,
    profile: OracleBenchmarkReviewProfile,
    missing_paths: list[str],
) -> str:
    index_payload = _read_oracle_upload_bundle_index_payload(
        target.bundle_dir,
        review_profile=profile.profile_id,
    ) or {}
    analysis_payload = index_payload.get("analysis") if isinstance(index_payload, dict) else {}
    analysis_payload = analysis_payload if isinstance(analysis_payload, dict) else {}
    runtime_payload = analysis_payload.get("call_inventory_runtime")
    runtime_payload = runtime_payload if isinstance(runtime_payload, dict) else {}
    runtime_summary = runtime_payload.get("summary")
    runtime_summary = runtime_summary if isinstance(runtime_summary, dict) else {}
    prompt_budget = _read_prompt_budget_payload(target)
    by_stage = prompt_budget.get("by_stage") if isinstance(prompt_budget, dict) else {}
    by_stage = by_stage if isinstance(by_stage, dict) else {}
    knowledge_stage = by_stage.get("nonrecipe_finalize")
    if not isinstance(knowledge_stage, dict):
        knowledge_stage = by_stage.get("knowledge")
    knowledge_stage = knowledge_stage if isinstance(knowledge_stage, dict) else {}
    line_role_stage = by_stage.get("line_role")
    line_role_stage = line_role_stage if isinstance(line_role_stage, dict) else {}
    recipe_stage = by_stage.get("recipe_refine")
    if not isinstance(recipe_stage, dict):
        recipe_stage = by_stage.get("recipe_correction")
    recipe_stage = recipe_stage if isinstance(recipe_stage, dict) else {}

    lines = [
        "# Oracle Token Focus",
        "",
        f"- Review profile: `{profile.profile_id}`",
        f"- Benchmark root: `{target.source_root}`",
        f"- benchmark total tokens: `{_format_int_metric(runtime_summary.get('total_tokens'))}`",
        f"- knowledge tokens: `{_format_int_metric(knowledge_stage.get('tokens_total'))}`",
        f"- knowledge token share: `{_format_metric(runtime_summary.get('nonrecipe_finalize_token_share'), digits=4)}`",
        f"- knowledge wrapper overhead tokens: `{_format_int_metric(knowledge_stage.get('wrapper_overhead_tokens'))}`",
        f"- line-role tokens: `{_format_int_metric(line_role_stage.get('tokens_total'))}`",
        f"- recipe correction tokens: `{_format_int_metric(recipe_stage.get('tokens_total'))}`",
        f"- current benchmark Oracle turn-1 estimate: `~443667` tokens on the inspected 2026-03-22 run",
        "",
        "This packet is intentionally spend-first. It includes prompt-budget, call-inventory, warning/trace summary, and the small amount of prompt-sample context needed to judge whether the spend is doing useful work.",
        "It intentionally omits raw wrong-line case dumps. Request narrow follow-up data only if that extra evidence is required to rank low-risk spend cuts.",
    ]
    if missing_paths:
        lines.extend(
            [
                "",
                "Missing requested payload paths in this bundle:",
                *[f"- `{path}`" for path in missing_paths],
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _build_review_lane_brief(
    *,
    target: OracleBenchmarkBundleTarget,
    profile: OracleBenchmarkReviewProfile,
    missing_paths: list[str],
) -> str:
    if profile.profile_id == ORACLE_REVIEW_PROFILE_TOKEN:
        return _build_token_lane_brief(target=target, profile=profile, missing_paths=missing_paths)
    return _build_quality_lane_brief(target=target, profile=profile, missing_paths=missing_paths)


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


def _read_oracle_upload_bundle_index_payload(
    bundle_dir: Path,
    *,
    review_profile: str | None = None,
) -> dict[str, Any] | None:
    index_path = oracle_benchmark_review_packet_file(
        bundle_dir,
        review_profile,
        BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
    )
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _read_payload_rows(payload_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if payload_path.suffix.lower() == ".json":
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, dict):
            rows_payload = payload.get("rows")
            if isinstance(rows_payload, list):
                return [row for row in rows_payload if isinstance(row, dict)]
            return []
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        return []
    try:
        with payload_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                rows.append(payload)
    except OSError:
        return []
    return rows


def _read_payload_row_map(payload_path: Path) -> dict[str, dict[str, Any]]:
    path_to_row: dict[str, dict[str, Any]] = {}
    for payload in _read_payload_rows(payload_path):
        logical_path = str(payload.get("path") or "").strip()
        if logical_path and logical_path not in path_to_row:
            path_to_row[logical_path] = payload
    return path_to_row


def _stage_oracle_review_packet(
    *,
    target: OracleBenchmarkBundleTarget,
    staging_dir: Path,
    profile: OracleBenchmarkReviewProfile,
    allow_sharding: bool,
) -> PreparedOracleUploadInputs:
    prompt = build_oracle_benchmark_prompt(target=target, review_profile=profile.profile_id)
    review_packet_dir = oracle_benchmark_review_packet_dir(target.bundle_dir, profile.profile_id)
    overview_path = oracle_benchmark_review_packet_file(
        target.bundle_dir,
        profile.profile_id,
        BENCHMARK_UPLOAD_BUNDLE_OVERVIEW_FILE_NAME,
    )
    index_path = oracle_benchmark_review_packet_file(
        target.bundle_dir,
        profile.profile_id,
        BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
    )
    payload_path = oracle_benchmark_review_packet_file(
        target.bundle_dir,
        profile.profile_id,
        BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
    )
    payload_rows = _read_payload_rows(payload_path)
    payload_packet = (
        _load_json_object_path(payload_path)
        if payload_path.suffix.lower() == ".json"
        else {}
    )
    path_to_row = _read_payload_row_map(payload_path)
    selected_rows: list[dict[str, Any]] = []
    missing_paths: list[str] = []
    for logical_path in profile.payload_paths:
        row = path_to_row.get(logical_path)
        if not isinstance(row, dict):
            missing_paths.append(logical_path)
            continue
        selected_rows.append(row)
    selected_count = len(selected_rows)
    staged_payload_packet = {
        "schema_version": str(payload_packet.get("schema_version") or "upload_bundle.review_payload.v1"),
        "review_profile": profile.profile_id,
        "review_profile_display_name": profile.display_name,
        "generated_at": str(payload_packet.get("generated_at") or ""),
        "benchmark_root": str(payload_packet.get("benchmark_root") or target.source_root),
        "bundle_root": str(payload_packet.get("bundle_root") or target.bundle_dir),
        "selected_paths": list(profile.payload_paths),
        "missing_paths": list(missing_paths),
        "selected_row_count": selected_count,
        "row_count": selected_count,
        "rows": selected_rows,
    }
    staged_payload_source_path = staging_dir / BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME
    staged_payload_source_path.write_text(
        json.dumps(staged_payload_packet, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    selected_bytes = int(staged_payload_source_path.stat().st_size)
    if selected_count <= 0 or selected_bytes <= 0:
        raise ValueError(
            f"Oracle {profile.profile_id} review packet is empty at {payload_path}."
        )
    staged_paths: list[Path] = []
    shard_notes: list[str] = []
    for source_path, staged_name in (
        (overview_path, BENCHMARK_UPLOAD_BUNDLE_OVERVIEW_FILE_NAME),
        (index_path, BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME),
    ):
        file_staged_paths, shard_note = _stage_browser_upload_text_file(
            source_path=source_path,
            staging_dir=staging_dir,
            staged_name=staged_name,
        )
        staged_paths.extend(file_staged_paths)
        if shard_note:
            shard_notes.append(shard_note)
    if allow_sharding:
        payload_staged_paths, payload_shard_note = _stage_browser_upload_text_file(
            source_path=staged_payload_source_path,
            staging_dir=staging_dir,
            staged_name=BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
        )
    else:
        staged_payload_path = staging_dir / BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME
        staged_payload_path.write_text(
            staged_payload_source_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        payload_staged_paths = [staged_payload_path]
        payload_shard_note = ""
    staged_paths.extend(payload_staged_paths)
    if payload_shard_note:
        shard_notes.append(payload_shard_note)

    missing_text = (
        f" Missing requested paths: {', '.join(missing_paths)}."
        if missing_paths
        else ""
    )
    prompt_lines = [
        prompt,
        "",
        "Oracle transport note: browser upload may deliver the logical text files as one synthetic attachment such as `attachments-bundle.txt`.",
        f"Oracle transport note: this `{profile.profile_id}` lane packet comes from `{review_packet_dir}`.",
        "Oracle transport note: artifact `path` values inside `payload.json` still point at the logical benchmark artifacts.",
        f"If you need evidence outside the attached `{profile.profile_id}` packet, request narrow follow-up data instead of asking for the full bundle again.",
        *shard_notes,
        "Read `overview.md` first, then `index.json`, and consult the attached payload rows by `path` as needed.",
    ]
    note = (
        f"Prepared Oracle {profile.profile_id} review packet with {selected_count} payload rows "
        f"({selected_bytes} bytes).{missing_text}"
    )
    return PreparedOracleUploadInputs(
        prompt="\n".join(prompt_lines),
        file_paths=staged_paths,
        note=note,
    )


def _prepare_oracle_upload_inputs(
    *,
    target: OracleBenchmarkBundleTarget,
    staging_dir: Path,
    profile: OracleBenchmarkReviewProfile,
    mode: str,
) -> PreparedOracleUploadInputs:
    normalized_mode = mode.strip().lower()
    return _stage_oracle_review_packet(
        target=target,
        staging_dir=staging_dir,
        profile=profile,
        allow_sharding=normalized_mode == "browser",
    )


def _oracle_upload_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d_%H.%M.%S")


def _oracle_background_launch_dir(bundle_dir: Path, *, suffix: str = "") -> Path:
    parent_dir = oracle_upload_runs_dir(bundle_dir)
    base_name = _oracle_upload_timestamp()
    normalized_suffix = str(suffix or "").strip()
    candidate_name = f"{base_name}-{normalized_suffix}" if normalized_suffix else base_name
    candidate = parent_dir / candidate_name
    suffix = 1
    while candidate.exists():
        candidate = parent_dir / f"{candidate_name}_{suffix:02d}"
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
        chatgpt_url = str(
            os.environ.get(ORACLE_CHATGPT_URL_ENV) or ORACLE_DEFAULT_CHATGPT_URL
        ).strip()
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
    return Path(ORACLE_BROWSER_PROFILE_DIR).expanduser()


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
    payload = _read_oracle_upload_bundle_index_payload(
        target.bundle_dir,
        review_profile=ORACLE_REVIEW_PROFILE_QUALITY,
    )
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
                "review_profile": str(merged_payload.get("review_profile") or ""),
                "review_profile_display_name": str(
                    merged_payload.get("review_profile_display_name") or ""
                ),
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
    review_profile: str | None = None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> OracleBackgroundUploadLaunch:
    normalized_mode = mode.strip().lower()
    resolved_model = resolve_oracle_benchmark_model(model)
    launch_model = _resolve_oracle_launch_model(mode=normalized_mode, model=resolved_model)
    profile = resolve_oracle_benchmark_review_profile(review_profile)
    launch_started_at = datetime.now(timezone.utc)
    launch_dir = _oracle_background_launch_dir(target.bundle_dir, suffix=profile.profile_id)
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
    metadata_path = launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME

    note = ""
    session_prompt = build_oracle_benchmark_prompt(
        target=target,
        review_profile=profile.profile_id,
    )
    if normalized_mode == "browser":
        staging_dir = launch_dir / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        prepared = _prepare_oracle_upload_inputs(
            target=target,
            staging_dir=staging_dir,
            profile=profile,
            mode=normalized_mode,
        )
        command = _oracle_command(
            mode=normalized_mode,
            model=launch_model,
            prompt=prepared.prompt,
            file_paths=prepared.file_paths,
        )
        note = prepared.note
        session_prompt = prepared.prompt
    elif normalized_mode == "dry-run":
        command = _oracle_command(
            mode=normalized_mode,
            model=launch_model,
            prompt=session_prompt,
            file_paths=[
                oracle_benchmark_review_packet_file(
                    target.bundle_dir,
                    profile.profile_id,
                    file_name,
                )
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
        "review_profile": profile.profile_id,
        "review_profile_display_name": profile.display_name,
        "mode": normalized_mode,
        "model": resolved_model,
        "launch_model": launch_model,
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
        review_profile=profile.profile_id,
        review_profile_display_name=profile.display_name,
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
    review_profile: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> OracleUploadResult:
    normalized_mode = mode.strip().lower()
    resolved_model = resolve_oracle_benchmark_model(model)
    launch_model = _resolve_oracle_launch_model(mode=normalized_mode, model=resolved_model)
    profile = resolve_oracle_benchmark_review_profile(review_profile)

    if normalized_mode == "browser":
        oracle_version = _detect_oracle_version()
        launch_started_at = datetime.now(timezone.utc)
        launch_dir = _oracle_background_launch_dir(target.bundle_dir, suffix=profile.profile_id)
        launch_dir.mkdir(parents=True, exist_ok=True)
        log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
        metadata_path = launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME
        staging_dir = launch_dir / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        prepared = _prepare_oracle_upload_inputs(
            target=target,
            staging_dir=staging_dir,
            profile=profile,
            mode=normalized_mode,
        )
        command = _oracle_command(
            mode=normalized_mode,
            model=launch_model,
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
            "review_profile": profile.profile_id,
            "review_profile_display_name": profile.display_name,
            "mode": normalized_mode,
        "model": resolved_model,
        "launch_model": launch_model,
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
            review_profile=profile.profile_id,
            review_profile_display_name=profile.display_name,
            status=audit.status,
            status_reason=audit.status_reason,
            session_id=audit.session_id,
            reattach_command=audit.reattach_command,
            conversation_url=audit.conversation_url,
            conversation_id=audit.conversation_id,
        )

    if normalized_mode == "dry-run":
        with tempfile.TemporaryDirectory(prefix=f"oracle-upload-{profile.profile_id}-") as temp_dir:
            staging_dir = Path(temp_dir)
            prepared = _prepare_oracle_upload_inputs(
                target=target,
                staging_dir=staging_dir,
                profile=profile,
                mode=normalized_mode,
            )
            oversized_staged = [
                path for path in prepared.file_paths if path.stat().st_size > ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES
            ]
            if oversized_staged:
                browser_command = _oracle_command(
                mode="browser",
                    model=launch_model,
                    prompt=prepared.prompt,
                    file_paths=prepared.file_paths,
                )
                oversized_text = ", ".join(
                    f"{path.name} ({path.stat().st_size} bytes)" for path in oversized_staged
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
                        f"was started. Oversized staged files: {oversized_text}. Use browser mode for "
                        "the real upload."
                    ),
                    stderr="",
                    oracle_version=_detect_oracle_version(),
                    review_profile=profile.profile_id,
                    review_profile_display_name=profile.display_name,
                )
            command = _oracle_command(
                mode=normalized_mode,
                model=resolved_model,
                prompt=prepared.prompt,
                file_paths=prepared.file_paths,
            )
            oracle_version = _detect_oracle_version()
            completed = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            stdout = completed.stdout or ""
            if prepared.note:
                stdout = f"{prepared.note}\n{stdout}" if stdout else prepared.note
            return OracleUploadResult(
                success=completed.returncode == 0,
                mode=normalized_mode,
                command=command,
                bundle_dir=target.bundle_dir,
                returncode=int(completed.returncode),
                stdout=stdout,
                stderr=completed.stderr or "",
                oracle_version=oracle_version,
                review_profile=profile.profile_id,
                review_profile_display_name=profile.display_name,
            )

    raise ValueError(f"Unsupported Oracle upload mode: {mode}")
