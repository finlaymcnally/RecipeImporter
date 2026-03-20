from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

from cookimport.bench.followup_bundle import write_followup_request_packet, write_followup_request_template
from cookimport.bench.oracle_upload import (
    ORACLE_BROWSER_CMD,
    ORACLE_DEFAULT_MODEL,
    ORACLE_UPLOAD_LOG_FILE_NAME,
    ORACLE_UPLOAD_METADATA_FILE_NAME,
    ORACLE_UPLOAD_RUNS_DIR_NAME,
    ORACLE_UPLOAD_STATUS_FILE_NAME,
    OracleBenchmarkBundleTarget,
    OracleUploadAudit,
    OracleUploadResult,
    _detect_oracle_version,
    _find_matching_oracle_session_snapshot,
    _oracle_background_launch_dir,
    _oracle_file_argument,
    _oracle_upload_timestamp,
    _oracle_sessions_dir,
    _parse_oracle_session_metadata,
    _parse_iso_datetime,
    _persist_oracle_upload_metadata,
    _read_oracle_session_snapshot_by_id,
    _render_oracle_benchmark_prompt_template,
    _read_log_text,
    audit_oracle_upload_log,
)


ORACLE_BENCHMARK_FOLLOWUP_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "llm_pipelines"
    / "prompts"
    / "benchmark.oracle-followup.prompt.md"
)
ORACLE_BENCHMARK_FOLLOWUP_PROMPT_TEMPLATE_FALLBACK = "\n".join(
    [
        "You are continuing an existing benchmark investigation for the local `cookimport` CLI.",
        "Stay in the current ChatGPT conversation and treat the attached `followup_data1` packet as additive evidence on top of the earlier `upload_bundle_v1` review.",
        "The benchmark root is `{{BENCHMARK_ROOT}}` and the original bundle scope is `{{BUNDLE_SCOPE}}`.",
        "The prior Oracle session id was `{{SOURCE_SESSION_ID}}`.",
        "The local follow-up packet root is `{{FOLLOWUP_PACKET_PATH}}`.",
        "Update your earlier hypotheses using the new evidence. Be explicit about which theories are strengthened, weakened, or falsified.",
        "Return exactly four sections: `Updated assessment`, `Confirmed hypotheses`, `Rejected hypotheses`, and `Next best follow-up`.",
        "If the new packet is sufficient, write `None` in `Next best follow-up`.",
    ]
)
ORACLE_FOLLOWUP_REQUEST_MARKDOWN_NAME = "oracle_followup_request.md"
ORACLE_FOLLOWUP_REQUEST_JSON_NAME = "oracle_followup_request.json"
ORACLE_FOLLOWUP_HANDOFF_NAME = "codex_followup_handoff.md"
ORACLE_FOLLOWUP_PROMPT_NAME = "turn2_prompt.md"
ORACLE_FOLLOWUP_PACKET_DIR_NAME = "followup_data1"
ORACLE_FOLLOWUP_METADATA_FILE_NAME = ORACLE_UPLOAD_METADATA_FILE_NAME
ORACLE_FOLLOWUP_STATUS_FILE_NAME = ORACLE_UPLOAD_STATUS_FILE_NAME
ORACLE_AUTO_FOLLOWUP_STATUS_NAME = "oracle_auto_followup.json"
ORACLE_AUTO_FOLLOWUP_LOG_NAME = "oracle_auto_followup.log"
ORACLE_AUTO_FOLLOWUP_POLL_INTERVAL_SECONDS = 15.0
ORACLE_AUTO_FOLLOWUP_TIMEOUT_SECONDS = 4 * 60 * 60
ORACLE_FOLLOWUP_ALLOWED_OUTPUTS = {
    "structure_report",
    "case_export",
    "line_role_audit",
    "prompt_link_audit",
    "knowledge_audit",
    "page_context",
    "uncertainty",
    "all",
}
_REQUESTED_FOLLOWUP_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#+\s*)?Requested follow-up data\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ASK_START_RE = re.compile(r"^\s*(?:[-*]\s*)?Ask(?:\s+\d+)?\s*:?\s*$", re.IGNORECASE)
_KEY_VALUE_RE = re.compile(r"^\s*(?:[-*]\s*)?(?P<key>[a-zA-Z0-9_ -]+?)\s*:\s*(?P<value>.*\S)?\s*$")
_CONVERSATION_URL_RE = re.compile(r"https://chatgpt\.com/[^\s)]+")
_ANSWER_MARKER = "Answer:"


@dataclass(frozen=True)
class ParsedOracleFollowupAsk:
    ask_id: str
    question: str
    outputs: list[str]
    stage_filters: list[str]
    include_case_ids: list[str]
    include_recipe_ids: list[str]
    include_line_ranges: list[str]
    include_knowledge_source_keys: list[str]
    include_knowledge_output_subdirs: list[str]
    hypothesis: str = ""
    smallest_useful_packet: str = ""
    raw_fields: dict[str, str] | None = None


@dataclass(frozen=True)
class ParsedOracleFollowupRequest:
    section_text: str
    asks: list[ParsedOracleFollowupAsk]
    none_requested: bool


@dataclass(frozen=True)
class OracleFollowupSource:
    launch_dir: Path
    metadata_path: Path
    log_path: Path
    source_session_id: str
    source_conversation_url: str
    source_conversation_id: str
    answer_text: str
    requested_followup_text: str


@dataclass(frozen=True)
class OracleFollowupWorkspace:
    launch_dir: Path
    metadata_path: Path
    status_path: Path
    log_path: Path
    request_markdown_path: Path
    request_json_path: Path
    handoff_path: Path
    prompt_path: Path
    followup_packet_dir: Path


def _oracle_auto_followup_status_path(source_launch_dir: Path) -> Path:
    return source_launch_dir / ORACLE_AUTO_FOLLOWUP_STATUS_NAME


def _oracle_auto_followup_log_path(source_launch_dir: Path) -> Path:
    return source_launch_dir / ORACLE_AUTO_FOLLOWUP_LOG_NAME


def _write_oracle_auto_followup_status(
    source_launch_dir: Path,
    *,
    status: str,
    status_reason: str,
    extra: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "status": status,
        "status_reason": status_reason,
        "updated_at": _oracle_upload_timestamp(),
    }
    if extra:
        payload.update(extra)
    status_path = _oracle_auto_followup_status_path(source_launch_dir)
    status_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return status_path


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def extract_answer_block(text: str) -> str:
    marker_index = text.rfind(_ANSWER_MARKER)
    if marker_index < 0:
        return text.strip()
    return text[marker_index + len(_ANSWER_MARKER) :].strip()


def extract_requested_followup_section(answer_text: str) -> str | None:
    if not answer_text.strip():
        return None
    match = _REQUESTED_FOLLOWUP_HEADING_RE.search(answer_text)
    if match is None:
        return None
    section = answer_text[match.end() :].strip()
    return section or None


def _split_csv(value: str) -> list[str]:
    rows = [part.strip() for part in value.split(",")]
    return [row for row in rows if row]


def _normalize_output_tokens(tokens: list[str]) -> list[str]:
    normalized: list[str] = []
    for token in tokens:
        lowered = token.strip().lower().replace("-", "_").replace(" ", "_")
        if not lowered:
            continue
        if lowered not in ORACLE_FOLLOWUP_ALLOWED_OUTPUTS:
            continue
        normalized.append(lowered)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in normalized:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped


def _normalize_text_list(tokens: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        value = token.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _slugify(text: str, *, fallback: str) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", text.lower())[:6]).strip("-")
    return slug or fallback


def parse_requested_followup_text(section_text: str) -> ParsedOracleFollowupRequest:
    cleaned = section_text.strip()
    if not cleaned:
        return ParsedOracleFollowupRequest(section_text=section_text, asks=[], none_requested=True)
    if cleaned.lower() == "none":
        return ParsedOracleFollowupRequest(section_text=section_text, asks=[], none_requested=True)

    asks_raw: list[dict[str, str]] = []
    current: dict[str, str] = {}
    last_key = ""
    for raw_line in cleaned.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if _ASK_START_RE.match(line):
            if current:
                asks_raw.append(current)
                current = {}
                last_key = ""
            continue
        key_match = _KEY_VALUE_RE.match(line)
        if key_match:
            key = key_match.group("key").strip().lower().replace(" ", "_").replace("-", "_")
            value = (key_match.group("value") or "").strip()
            current[key] = value
            last_key = key
            continue
        if last_key:
            current[last_key] = f"{current.get(last_key, '').rstrip()} {stripped}".strip()
    if current:
        asks_raw.append(current)

    asks: list[ParsedOracleFollowupAsk] = []
    for index, row in enumerate(asks_raw, start=1):
        question = str(row.get("question") or "").strip()
        ask_id = str(row.get("ask_id") or "").strip() or f"ask_{index:03d}_{_slugify(question, fallback='followup')}"
        outputs = _normalize_output_tokens(_split_csv(str(row.get("outputs") or row.get("output") or "")))
        stage_filters = _normalize_text_list(
            token.lower().replace(" ", "_") for token in _split_csv(str(row.get("stage_filters") or ""))
        )
        include_case_ids = _normalize_text_list(_split_csv(str(row.get("include_case_ids") or "")))
        include_recipe_ids = _normalize_text_list(_split_csv(str(row.get("include_recipe_ids") or "")))
        include_line_ranges = _normalize_text_list(_split_csv(str(row.get("include_line_ranges") or "")))
        include_knowledge_source_keys = _normalize_text_list(
            _split_csv(str(row.get("include_knowledge_source_keys") or ""))
        )
        include_knowledge_output_subdirs = _normalize_text_list(
            _split_csv(str(row.get("include_knowledge_output_subdirs") or ""))
        )
        asks.append(
            ParsedOracleFollowupAsk(
                ask_id=ask_id,
                question=question,
                outputs=outputs,
                stage_filters=stage_filters,
                include_case_ids=include_case_ids,
                include_recipe_ids=include_recipe_ids,
                include_line_ranges=include_line_ranges,
                include_knowledge_source_keys=include_knowledge_source_keys,
                include_knowledge_output_subdirs=include_knowledge_output_subdirs,
                hypothesis=str(row.get("hypothesis") or "").strip(),
                smallest_useful_packet=str(
                    row.get("smallest_useful_packet") or row.get("why_this_is_the_smallest_useful_packet") or ""
                ).strip(),
                raw_fields=dict(row),
            )
        )
    return ParsedOracleFollowupRequest(
        section_text=section_text,
        asks=asks,
        none_requested=False,
    )


def _load_followup_template(bundle_dir: Path) -> dict[str, Any]:
    with NamedTemporaryFile(prefix="oracle-followup-template-", suffix=".json", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        write_followup_request_template(bundle_dir=bundle_dir, out_path=temp_path)
        return json.loads(temp_path.read_text(encoding="utf-8"))
    finally:
        temp_path.unlink(missing_ok=True)


def build_followup_request_manifest(
    *,
    bundle_dir: Path,
    parsed: ParsedOracleFollowupRequest,
) -> dict[str, Any]:
    if parsed.none_requested:
        raise ValueError("Oracle did not request any follow-up data.")
    if not parsed.asks:
        raise ValueError("Could not parse any structured follow-up asks from Oracle's response.")

    template = _load_followup_template(bundle_dir)
    default_stage_filters = [
        str(value).strip()
        for value in template.get("default_stage_filters", [])
        if str(value).strip()
    ] or ["line_role"]
    template_asks = [
        row for row in template.get("asks", [])
        if isinstance(row, dict)
    ]
    fallback_outputs = (
        [str(value).strip() for value in template_asks[0].get("outputs", []) if str(value).strip()]
        if template_asks
        else ["case_export"]
    )
    manifest_asks: list[dict[str, Any]] = []
    for index, ask in enumerate(parsed.asks, start=1):
        template_ask = template_asks[min(index - 1, len(template_asks) - 1)] if template_asks else {}
        selectors_template = (
            dict(template_ask.get("selectors") or {})
            if isinstance(template_ask, dict)
            else {}
        )
        question = ask.question or str(template_ask.get("question") or "").strip() or (
            f"Provide follow-up evidence for {ask.ask_id}."
        )
        outputs = ask.outputs or [
            str(value).strip()
            for value in template_ask.get("outputs", fallback_outputs)
            if str(value).strip()
        ]
        notes_parts = [part for part in [ask.hypothesis, ask.smallest_useful_packet] if part]
        manifest_asks.append(
            {
                "ask_id": ask.ask_id,
                "question": question,
                "outputs": outputs,
                "selectors": {
                    "top_neg": int(selectors_template.get("top_neg") or 0),
                    "top_pos": int(selectors_template.get("top_pos") or 0),
                    "outside_span": int(selectors_template.get("outside_span") or 0),
                    "stage_filters": ask.stage_filters or list(default_stage_filters),
                    "include_case_ids": list(ask.include_case_ids),
                    "include_recipe_ids": list(ask.include_recipe_ids),
                    "include_line_ranges": list(ask.include_line_ranges),
                    "include_knowledge_source_keys": list(ask.include_knowledge_source_keys),
                    "include_knowledge_output_subdirs": list(ask.include_knowledge_output_subdirs),
                },
                "notes": " ".join(notes_parts).strip(),
            }
        )
    return {
        "schema_version": "cf.followup_request.v1",
        "bundle_dir": str(bundle_dir),
        "bundle_sha256": template.get("bundle_sha256", ""),
        "request_id": "oracle_followup_request_01",
        "request_summary": "Follow-up packet built from Oracle turn-1 benchmark review.",
        "requester_context": {
            "already_has_upload_bundle_v1": True,
            "prefer_new_local_artifacts_over_bundle_repeats": True,
            "duplicate_bundle_payloads_only_when_needed_for_context": True,
            "source": "oracle_turn_1",
        },
        "default_stage_filters": list(default_stage_filters),
        "asks": manifest_asks,
    }


def _find_followup_source_launch_dir(
    *,
    bundle_dir: Path,
    from_run: str,
) -> Path:
    runs_dir = bundle_dir / ORACLE_UPLOAD_RUNS_DIR_NAME
    if not runs_dir.is_dir():
        raise ValueError(f"No Oracle upload runs found under {runs_dir}.")
    candidates = sorted(
        [
            path
            for path in runs_dir.iterdir()
            if path.is_dir() and (path / ORACLE_UPLOAD_METADATA_FILE_NAME).is_file()
        ],
        key=lambda path: path.name,
    )
    if not candidates:
        raise ValueError(f"No Oracle upload metadata found under {runs_dir}.")
    if from_run == "latest":
        return candidates[-1]
    exact = runs_dir / from_run
    if exact.is_dir():
        return exact
    raise ValueError(f"Oracle run not found: {from_run}")


def _read_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}.")
    return payload


def _extract_conversation_url(text: str) -> str:
    matches = _CONVERSATION_URL_RE.findall(text)
    return matches[-1] if matches else ""


def load_oracle_followup_source(
    *,
    target: OracleBenchmarkBundleTarget,
    from_run: str = "latest",
    allow_missing_requested_section: bool = False,
) -> OracleFollowupSource:
    launch_dir = _find_followup_source_launch_dir(bundle_dir=target.bundle_dir, from_run=from_run)
    metadata_path = launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME
    log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
    metadata = _read_json_file(metadata_path)
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    answer_text = extract_answer_block(log_text)
    requested_section = extract_requested_followup_section(answer_text or log_text)
    if requested_section is None and not allow_missing_requested_section:
        raise ValueError(
            f"Could not find a `Requested follow-up data` section in {log_path}."
        )
    source_session_id = str(metadata.get("session_id") or "").strip()
    source_conversation_url = str(metadata.get("conversation_url") or "").strip() or _extract_conversation_url(log_text)
    source_conversation_id = str(metadata.get("conversation_id") or "").strip()
    if source_session_id and (not source_conversation_url or not source_conversation_id):
        session_snapshot = _read_oracle_session_snapshot_by_id(
            session_id=source_session_id,
            sessions_dir=_oracle_sessions_dir(None),
        )
        if session_snapshot is not None:
            source_conversation_url = source_conversation_url or session_snapshot.conversation_url
            source_conversation_id = source_conversation_id or session_snapshot.conversation_id
    if not source_session_id:
        raise ValueError(f"No Oracle session_id recorded in {metadata_path}.")
    return OracleFollowupSource(
        launch_dir=launch_dir,
        metadata_path=metadata_path,
        log_path=log_path,
        source_session_id=source_session_id,
        source_conversation_url=source_conversation_url,
        source_conversation_id=source_conversation_id,
        answer_text=answer_text,
        requested_followup_text=requested_section or "",
    )


def refresh_oracle_background_upload_state(
    *,
    target: OracleBenchmarkBundleTarget,
    from_run: str,
) -> tuple[Path, dict[str, Any], OracleUploadAudit]:
    source_launch_dir = _find_followup_source_launch_dir(bundle_dir=target.bundle_dir, from_run=from_run)
    metadata_path = source_launch_dir / ORACLE_UPLOAD_METADATA_FILE_NAME
    metadata = _read_json_file(metadata_path)
    log_path = source_launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
    log_text = _read_log_text(log_path)
    audit = audit_oracle_upload_log(target=target, log_text=log_text)
    browser_profile_text = str(metadata.get("browser_profile_dir") or "").strip()
    browser_profile_dir = Path(browser_profile_text).expanduser() if browser_profile_text else None
    source_session_id = audit.session_id or str(metadata.get("session_id") or "").strip()
    source_conversation_url = audit.conversation_url or str(metadata.get("conversation_url") or "").strip()
    source_conversation_id = audit.conversation_id or str(metadata.get("conversation_id") or "").strip()

    if not source_session_id:
        prompt = str(metadata.get("prompt") or "").strip()
        created_after = _parse_iso_datetime(str(metadata.get("launch_started_at_utc") or ""))
        if prompt and created_after is not None:
            session_snapshot = _find_matching_oracle_session_snapshot(
                prompt=prompt,
                cwd=Path.cwd(),
                sessions_dir=_oracle_sessions_dir(browser_profile_dir),
                created_after=created_after,
            )
            if session_snapshot is not None:
                source_session_id = session_snapshot.session_id
                source_conversation_url = source_conversation_url or session_snapshot.conversation_url
                source_conversation_id = source_conversation_id or session_snapshot.conversation_id

    if source_session_id and (not source_conversation_url or not source_conversation_id):
        session_snapshot = _read_oracle_session_snapshot_by_id(
            session_id=source_session_id,
            sessions_dir=_oracle_sessions_dir(browser_profile_dir),
        )
        if session_snapshot is not None:
            source_conversation_url = source_conversation_url or session_snapshot.conversation_url
            source_conversation_id = source_conversation_id or session_snapshot.conversation_id

    if source_session_id and source_session_id != audit.session_id:
        audit = OracleUploadAudit(
            status=audit.status,
            status_reason=audit.status_reason,
            session_id=source_session_id,
            reattach_command=f"oracle session {source_session_id}",
            conversation_url=source_conversation_url,
            conversation_id=source_conversation_id,
        )
    elif source_conversation_url and source_conversation_url != audit.conversation_url:
        audit = OracleUploadAudit(
            status=audit.status,
            status_reason=audit.status_reason,
            session_id=audit.session_id,
            reattach_command=audit.reattach_command,
            conversation_url=source_conversation_url,
            conversation_id=source_conversation_id,
        )

    pid = int(metadata.get("pid") or 0)
    if audit.status == "failed" and _pid_is_running(pid):
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
        payload=metadata,
        audit=audit,
    )
    metadata = _read_json_file(metadata_path)
    return source_launch_dir, metadata, audit


def wait_for_oracle_background_upload_completion(
    *,
    target: OracleBenchmarkBundleTarget,
    from_run: str,
    poll_interval_seconds: float = ORACLE_AUTO_FOLLOWUP_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = ORACLE_AUTO_FOLLOWUP_TIMEOUT_SECONDS,
) -> tuple[Path, dict[str, Any], OracleUploadAudit] | None:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        launch_dir, metadata, audit = refresh_oracle_background_upload_state(
            target=target,
            from_run=from_run,
        )
        if audit.status != "running":
            return launch_dir, metadata, audit
        if time.monotonic() >= deadline:
            return None
        time.sleep(max(poll_interval_seconds, 0.1))


def build_oracle_followup_prompt(
    *,
    target: OracleBenchmarkBundleTarget,
    source: OracleFollowupSource,
    followup_packet_dir: Path,
) -> str:
    return _render_oracle_benchmark_prompt_template(
        path=ORACLE_BENCHMARK_FOLLOWUP_PROMPT_TEMPLATE_PATH,
        fallback=ORACLE_BENCHMARK_FOLLOWUP_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{BUNDLE_SCOPE}}": target.scope,
            "{{BENCHMARK_ROOT}}": str(target.source_root),
            "{{SOURCE_SESSION_ID}}": source.source_session_id or "<unknown>",
            "{{FOLLOWUP_PACKET_PATH}}": str(followup_packet_dir),
        },
    )


def _codex_handoff_markdown(
    *,
    source: OracleFollowupSource,
    parsed: ParsedOracleFollowupRequest,
    request_path: Path,
    packet_dir: Path,
) -> str:
    lines = [
        "# Oracle Follow-Up Handoff",
        "",
        f"- source_run_dir: `{source.launch_dir}`",
        f"- source_session_id: `{source.source_session_id or '<missing>'}`",
        f"- source_conversation_url: `{source.source_conversation_url or '<missing>'}`",
        f"- followup_request_json: `{request_path}`",
        f"- followup_packet_dir: `{packet_dir}`",
        "",
        "## Raw Requested Follow-Up Data",
        "",
        source.requested_followup_text.strip() or "None",
        "",
        "## Parsed Asks",
        "",
    ]
    if parsed.none_requested or not parsed.asks:
        lines.append("- No follow-up asks were parsed.")
    else:
        for ask in parsed.asks:
            lines.append(f"- `{ask.ask_id}`: {ask.question or '<missing question>'}")
            lines.append(
                "  outputs="
                + (", ".join(ask.outputs) if ask.outputs else "<default>")
                + " stage_filters="
                + (", ".join(ask.stage_filters) if ask.stage_filters else "<default>")
            )
    lines.append("")
    lines.append("## Repair Guidance")
    lines.append("")
    lines.append(
        "If the parsed request is incomplete, edit `oracle_followup_request.json` or supply "
        "`--request-file <path>` when rerunning `cookimport bench oracle-followup`."
    )
    return "\n".join(lines).rstrip() + "\n"


def _build_continue_session_command(
    *,
    source_session_id: str,
    model: str,
    prompt: str,
    followup_packet_dir: Path,
) -> list[str]:
    return [
        ORACLE_BROWSER_CMD,
        "continue-session",
        source_session_id,
        prompt,
        "--model",
        model,
        "--file",
        _oracle_file_argument(followup_packet_dir),
    ]


def _classify_continue_session_result(
    *,
    completed: subprocess.CompletedProcess[str],
) -> tuple[str, str, str, str, str]:
    combined = "\n".join(part for part in [completed.stdout or "", completed.stderr or ""] if part).strip()
    answer_text = extract_answer_block(combined)
    session_id, reattach_command = _parse_oracle_session_metadata(combined)
    conversation_url = _extract_conversation_url(combined)
    if completed.returncode == 0 and answer_text:
        return "succeeded", "Follow-up answer captured from Oracle.", session_id, reattach_command, conversation_url
    if session_id:
        return "reattachable", "Oracle created a follow-up session but the answer was not captured inline.", session_id, reattach_command, conversation_url
    return "failed", "Oracle did not return a follow-up answer.", session_id, reattach_command, conversation_url


def write_oracle_followup_workspace(
    *,
    target: OracleBenchmarkBundleTarget,
    source: OracleFollowupSource,
    parsed: ParsedOracleFollowupRequest,
    request_manifest: dict[str, Any],
) -> OracleFollowupWorkspace:
    launch_dir = _oracle_background_launch_dir(target.bundle_dir)
    launch_dir.mkdir(parents=True, exist_ok=True)
    log_path = launch_dir / ORACLE_UPLOAD_LOG_FILE_NAME
    metadata_path = launch_dir / ORACLE_FOLLOWUP_METADATA_FILE_NAME
    status_path = launch_dir / ORACLE_FOLLOWUP_STATUS_FILE_NAME
    request_markdown_path = launch_dir / ORACLE_FOLLOWUP_REQUEST_MARKDOWN_NAME
    request_json_path = launch_dir / ORACLE_FOLLOWUP_REQUEST_JSON_NAME
    handoff_path = launch_dir / ORACLE_FOLLOWUP_HANDOFF_NAME
    prompt_path = launch_dir / ORACLE_FOLLOWUP_PROMPT_NAME
    followup_packet_dir = launch_dir / ORACLE_FOLLOWUP_PACKET_DIR_NAME

    request_markdown_path.write_text(source.requested_followup_text.strip() + "\n", encoding="utf-8")
    request_json_path.write_text(json.dumps(request_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_followup_request_packet(
        bundle_dir=target.bundle_dir,
        request_path=request_json_path,
        out_dir=followup_packet_dir,
        include_readme=True,
    )
    prompt_text = build_oracle_followup_prompt(
        target=target,
        source=source,
        followup_packet_dir=followup_packet_dir,
    )
    prompt_path.write_text(prompt_text.rstrip() + "\n", encoding="utf-8")
    handoff_path.write_text(
        _codex_handoff_markdown(
            source=source,
            parsed=parsed,
            request_path=request_json_path,
            packet_dir=followup_packet_dir,
        ),
        encoding="utf-8",
    )
    return OracleFollowupWorkspace(
        launch_dir=launch_dir,
        metadata_path=metadata_path,
        status_path=status_path,
        log_path=log_path,
        request_markdown_path=request_markdown_path,
        request_json_path=request_json_path,
        handoff_path=handoff_path,
        prompt_path=prompt_path,
        followup_packet_dir=followup_packet_dir,
    )


def run_oracle_benchmark_followup(
    *,
    target: OracleBenchmarkBundleTarget,
    from_run: str = "latest",
    model: str = ORACLE_DEFAULT_MODEL,
    request_file: Path | None = None,
    dry_run: bool = False,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[OracleUploadResult, OracleFollowupWorkspace]:
    source = load_oracle_followup_source(
        target=target,
        from_run=from_run,
        allow_missing_requested_section=request_file is not None,
    )
    if request_file is not None:
        request_manifest = _read_json_file(request_file)
        parsed = parse_requested_followup_text(source.requested_followup_text)
    else:
        parsed = parse_requested_followup_text(source.requested_followup_text)
        request_manifest = build_followup_request_manifest(
            bundle_dir=target.bundle_dir,
            parsed=parsed,
        )
    workspace = write_oracle_followup_workspace(
        target=target,
        source=source,
        parsed=parsed,
        request_manifest=request_manifest,
    )
    prompt_text = workspace.prompt_path.read_text(encoding="utf-8")
    command = _build_continue_session_command(
        source_session_id=source.source_session_id,
        model=model,
        prompt=prompt_text,
        followup_packet_dir=workspace.followup_packet_dir,
    )
    metadata_payload = {
        "bundle_dir": str(target.bundle_dir),
        "source_root": str(target.source_root),
        "scope": target.scope,
        "mode": "browser",
        "model": model,
        "command": command,
        "log_path": str(workspace.log_path),
        "metadata_path": str(workspace.metadata_path),
        "status_path": str(workspace.status_path),
        "source_run_dir": str(source.launch_dir),
        "source_session_id": source.source_session_id,
        "source_conversation_url": source.source_conversation_url,
        "source_conversation_id": source.source_conversation_id,
        "request_markdown_path": str(workspace.request_markdown_path),
        "request_json_path": str(workspace.request_json_path),
        "handoff_path": str(workspace.handoff_path),
        "followup_packet_path": str(workspace.followup_packet_dir),
        "turn": 2,
    }
    if dry_run:
        preview_lines = [
            f"Local dry-run only. Follow-up workspace prepared at {workspace.launch_dir}.",
            f"Codex handoff: {workspace.handoff_path}",
            f"Follow-up request: {workspace.request_json_path}",
            f"Follow-up packet: {workspace.followup_packet_dir}",
            f"Oracle command: {shlex.join(command)}",
        ]
        stdout = "\n".join(preview_lines)
        workspace.log_path.write_text(stdout + "\n", encoding="utf-8")
        metadata_payload.update(
            {
                "status": "dry_run",
                "status_reason": "Prepared follow-up packet without calling Oracle.",
                "session_id": source.source_session_id,
                "reattach_command": f"oracle session {source.source_session_id}" if source.source_session_id else "",
                "conversation_url": source.source_conversation_url,
                "conversation_id": source.source_conversation_id,
            }
        )
        workspace.metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        workspace.status_path.write_text(
            json.dumps(
                {
                    "status": "dry_run",
                    "status_reason": "Prepared follow-up packet without calling Oracle.",
                    "session_id": source.source_session_id,
                    "conversation_url": source.source_conversation_url,
                    "conversation_id": source.source_conversation_id,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return (
            OracleUploadResult(
                success=True,
                mode="browser",
                command=command,
                bundle_dir=target.bundle_dir,
                returncode=0,
                stdout=stdout,
                stderr="",
                status="dry_run",
                status_reason="Prepared follow-up packet without calling Oracle.",
                session_id=source.source_session_id,
                reattach_command=f"oracle session {source.source_session_id}" if source.source_session_id else "",
                conversation_url=source.source_conversation_url,
                conversation_id=source.source_conversation_id,
            ),
            workspace,
        )

    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    combined = "\n".join(part for part in [completed.stdout or "", completed.stderr or ""] if part).strip()
    workspace.log_path.write_text(
        "\n".join(
            [
                f"Oracle command: {shlex.join(command)}",
                combined,
            ]
        ).rstrip()
        + "\n",
        encoding="utf-8",
    )
    status, status_reason, session_id, reattach_command, conversation_url = _classify_continue_session_result(
        completed=completed
    )
    if session_id and (not conversation_url):
        session_snapshot = _read_oracle_session_snapshot_by_id(
            session_id=session_id,
            sessions_dir=_oracle_sessions_dir(None),
        )
        if session_snapshot is not None:
            conversation_url = session_snapshot.conversation_url or conversation_url
    metadata_payload.update(
        {
            "returncode": int(completed.returncode),
            "status": status,
            "status_reason": status_reason,
            "session_id": session_id,
            "reattach_command": reattach_command,
            "conversation_url": conversation_url,
        }
    )
    workspace.metadata_path.write_text(json.dumps(metadata_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    workspace.status_path.write_text(
        json.dumps(
            {
                "status": status,
                "status_reason": status_reason,
                "session_id": session_id,
                "reattach_command": reattach_command,
                "conversation_url": conversation_url,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return (
        OracleUploadResult(
            success=completed.returncode == 0 and status == "succeeded",
            mode="browser",
            command=command,
            bundle_dir=target.bundle_dir,
            returncode=int(completed.returncode),
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            status=status,
            status_reason=status_reason,
            session_id=session_id,
            reattach_command=reattach_command,
            conversation_url=conversation_url,
        ),
        workspace,
    )


def run_oracle_benchmark_followup_background_worker(
    *,
    target: OracleBenchmarkBundleTarget,
    from_run: str,
    model: str = ORACLE_DEFAULT_MODEL,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    poll_interval_seconds: float = ORACLE_AUTO_FOLLOWUP_POLL_INTERVAL_SECONDS,
    timeout_seconds: float = ORACLE_AUTO_FOLLOWUP_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    source_launch_dir = _find_followup_source_launch_dir(bundle_dir=target.bundle_dir, from_run=from_run)
    status_path = _write_oracle_auto_followup_status(
        source_launch_dir,
        status="waiting_for_turn_1",
        status_reason="Waiting for the first Oracle benchmark review to finish.",
        extra={
            "bundle_dir": str(target.bundle_dir),
            "source_run": from_run,
            "model": model,
            "oracle_version": _detect_oracle_version(),
        },
    )
    print(f"[{_oracle_upload_timestamp()}] Waiting for Oracle turn 1 in {source_launch_dir}")
    completion = wait_for_oracle_background_upload_completion(
        target=target,
        from_run=from_run,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )
    if completion is None:
        _write_oracle_auto_followup_status(
            source_launch_dir,
            status="timed_out",
            status_reason="Timed out while waiting for the first Oracle benchmark review to finish.",
            extra={
                "bundle_dir": str(target.bundle_dir),
                "source_run": from_run,
                "model": model,
            },
        )
        print(f"[{_oracle_upload_timestamp()}] Timed out waiting for Oracle turn 1.")
        return _read_json_file(status_path)

    source_launch_dir, source_metadata, source_audit = completion
    if source_audit.status != "succeeded":
        _write_oracle_auto_followup_status(
            source_launch_dir,
            status="skipped",
            status_reason="Skipped automatic follow-up because Oracle turn 1 did not finish with a grounded answer.",
            extra={
                "bundle_dir": str(target.bundle_dir),
                "source_run": from_run,
                "source_status": source_audit.status,
                "source_status_reason": source_audit.status_reason,
                "source_session_id": source_audit.session_id,
                "source_conversation_url": source_audit.conversation_url,
            },
        )
        print(
            f"[{_oracle_upload_timestamp()}] Skipping automatic follow-up; "
            f"turn 1 ended as {source_audit.status}: {source_audit.status_reason}"
        )
        return _read_json_file(status_path)

    try:
        source = load_oracle_followup_source(target=target, from_run=from_run)
        parsed = parse_requested_followup_text(source.requested_followup_text)
    except Exception as exc:
        _write_oracle_auto_followup_status(
            source_launch_dir,
            status="failed",
            status_reason=f"Could not load Oracle follow-up request: {exc}",
            extra={
                "bundle_dir": str(target.bundle_dir),
                "source_run": from_run,
                "source_session_id": str(source_metadata.get("session_id") or ""),
                "source_conversation_url": str(source_metadata.get("conversation_url") or ""),
            },
        )
        print(f"[{_oracle_upload_timestamp()}] Failed to load follow-up request: {exc}")
        return _read_json_file(status_path)

    if parsed.none_requested:
        _write_oracle_auto_followup_status(
            source_launch_dir,
            status="no_followup_requested",
            status_reason="Oracle turn 1 explicitly requested no follow-up data.",
            extra={
                "bundle_dir": str(target.bundle_dir),
                "source_run": from_run,
                "source_session_id": source.source_session_id,
                "source_conversation_url": source.source_conversation_url,
            },
        )
        print(f"[{_oracle_upload_timestamp()}] Oracle turn 1 requested no follow-up data.")
        return _read_json_file(status_path)

    _write_oracle_auto_followup_status(
        source_launch_dir,
        status="launching_turn_2",
        status_reason="Building follow-up packet and launching Oracle turn 2.",
        extra={
            "bundle_dir": str(target.bundle_dir),
            "source_run": from_run,
            "source_session_id": source.source_session_id,
            "source_conversation_url": source.source_conversation_url,
            "ask_count": len(parsed.asks),
        },
    )
    print(f"[{_oracle_upload_timestamp()}] Launching Oracle turn 2 from {from_run}.")
    try:
        result, workspace = run_oracle_benchmark_followup(
            target=target,
            from_run=from_run,
            model=model,
            runner=runner,
        )
    except Exception as exc:
        _write_oracle_auto_followup_status(
            source_launch_dir,
            status="failed",
            status_reason=f"Oracle follow-up bridge failed: {exc}",
            extra={
                "bundle_dir": str(target.bundle_dir),
                "source_run": from_run,
                "source_session_id": source.source_session_id,
                "source_conversation_url": source.source_conversation_url,
            },
        )
        print(f"[{_oracle_upload_timestamp()}] Oracle turn 2 failed before launch: {exc}")
        return _read_json_file(status_path)

    final_status = "succeeded" if result.success else result.status or "failed"
    final_reason = (
        "Automatic Oracle follow-up completed."
        if result.success
        else (result.status_reason or "Automatic Oracle follow-up did not complete successfully.")
    )
    _write_oracle_auto_followup_status(
        source_launch_dir,
        status=final_status,
        status_reason=final_reason,
        extra={
            "bundle_dir": str(target.bundle_dir),
            "source_run": from_run,
            "source_session_id": source.source_session_id,
            "source_conversation_url": source.source_conversation_url,
            "followup_run_dir": str(workspace.launch_dir),
            "followup_status": result.status,
            "followup_status_reason": result.status_reason,
            "followup_session_id": result.session_id,
            "followup_conversation_url": result.conversation_url,
            "followup_request_json": str(workspace.request_json_path),
            "followup_packet_dir": str(workspace.followup_packet_dir),
            "followup_prompt_path": str(workspace.prompt_path),
        },
    )
    print(
        f"[{_oracle_upload_timestamp()}] Oracle turn 2 finished as {final_status} "
        f"({result.status_reason or 'no status reason'})."
    )
    return _read_json_file(status_path)
