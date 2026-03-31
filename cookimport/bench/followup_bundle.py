from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cookimport.bench.oracle_upload import (
    BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
    BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
    ORACLE_REVIEW_PROFILE_QUALITY,
    oracle_benchmark_review_packet_file,
)
from cookimport.bench.structure_label_report import build_structure_label_report
from cookimport.llm.codex_farm_ids import sanitize_for_filename

CHANGED_LINES_PAYLOAD_PATH = "_upload_bundle_derived/root/changed_lines.codex_vs_vanilla.jsonl"
TRIAGE_PACKET_PAYLOAD_PATH = "_upload_bundle_derived/root/01_recipe_triage.packet.jsonl"
PER_RECIPE_BREAKDOWN_PAYLOAD_PATH = "_upload_bundle_derived/root/per_recipe_or_per_span_breakdown.json"

SELECTOR_SCHEMA_VERSION = "cf.selector.v1"
FOLLOWUP_REQUEST_SCHEMA_VERSION = "cf.followup_request.v1"
FOLLOWUP_PACKET_SCHEMA_VERSION = "cf.followup_packet.v1"
CASE_EXPORT_INDEX_SCHEMA_VERSION = "cf.case_export_index.v1"
CASE_EXPORT_ROW_SCHEMA_VERSION = "cf.case_export.v1"
LINE_ROLE_AUDIT_SCHEMA_VERSION = "cf.line_role_audit.v1"
PROMPT_LINK_AUDIT_SCHEMA_VERSION = "cf.prompt_link_audit.v1"
KNOWLEDGE_AUDIT_SCHEMA_VERSION = "cf.knowledge_audit.v1"
PAGE_CONTEXT_SCHEMA_VERSION = "cf.page_context.v1"
UNCERTAINTY_SCHEMA_VERSION = "cf.uncertainty.v1"
PACK_SCHEMA_VERSION = "cf.followup_pack.v1"
ABLATION_SCHEMA_VERSION = "cf.ablation_matrix.v1"
SUPPORTED_STAGE_FILTERS = {
    "line_role",
    "knowledge",
    "recipe",
    "recipe_refine",
    "recipe_build_final",
}

OUTSIDE_SPAN_CASE_ID_RE = re.compile(r"^outside_span_window_(?P<start>\d+)_(?P<end>\d+)$")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _bundle_generated_at(index_payload: dict[str, Any]) -> str:
    generated_at = str(index_payload.get("generated_at") or "").strip()
    return generated_at or "unknown"


def _git_sha(repo_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def _bundle_sha256(bundle_dir: Path) -> str:
    digest = hashlib.sha256()
    for file_name in (
        BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
        BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
    ):
        path = oracle_benchmark_review_packet_file(
            bundle_dir,
            ORACLE_REVIEW_PROFILE_QUALITY,
            file_name,
        )
        digest.update(file_name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return str(path.resolve(strict=False))


def _recipe_suffix(recipe_id: str) -> str:
    text = str(recipe_id or "").strip()
    if not text:
        return ""
    return text.rsplit(":", 1)[-1]


def _recipe_artifact_filename(recipe_id: str) -> str:
    rendered = sanitize_for_filename(str(recipe_id).strip())
    if not rendered:
        rendered = "recipe"
    return f"{rendered}.json"


def _recipe_case_id(recipe_id: str, delta: float | None) -> str:
    suffix = _recipe_suffix(recipe_id)
    if not suffix:
        return "recipe_unknown"
    if delta is None:
        return f"recipe_{suffix}"
    if delta < 0:
        return f"regression_{suffix}"
    if delta > 0:
        return f"win_{suffix}"
    return f"recipe_{suffix}"


def _selector_id_for_recipe(source_key: str, recipe_id: str) -> str:
    return f"recipe:{source_key}:{recipe_id}"


def _selector_id_for_line_range(source_key: str, start: int, end: int) -> str:
    return f"line_range:{source_key}:{start}:{end}"


def _selector_id_for_knowledge_run(output_subdir: str) -> str:
    return f"knowledge_run:{output_subdir}"


def _slug_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return token.strip("_") or "unknown"


def _knowledge_case_id(source_key: str, output_subdir: str) -> str:
    variant = Path(output_subdir).name
    return f"knowledge_{_slug_token(source_key)}_{_slug_token(variant)}"


def _source_key_from_output_subdir(output_subdir: str) -> str:
    parts = Path(str(output_subdir or "")).parts
    return parts[0] if parts else ""


def _iter_prompt_category_manifest_paths(prompts_dir: Path) -> list[Path]:
    manifest_path = prompts_dir / "prompt_category_logs_manifest.txt"
    if not manifest_path.is_file():
        return []
    rows: list[Path] = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        text = raw_line.strip()
        if not text:
            continue
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = (prompts_dir / candidate).resolve()
        rows.append(candidate)
    return rows


def _resolve_knowledge_prompt_task_path(prompts_dir: Path) -> Path | None:
    candidates: list[Path] = [prompts_dir / "prompt_nonrecipe_finalize.txt"]
    for candidate in _iter_prompt_category_manifest_paths(prompts_dir):
        name = candidate.name.lower()
        if name.startswith("prompt_nonrecipe_finalize") and name.endswith(".txt"):
            candidates.append(candidate)
    candidates.extend(sorted(prompts_dir.glob("prompt_nonrecipe_finalize*.txt")))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        if candidate.is_file():
            return candidate
    return None


def _locator(
    *,
    path: str,
    payload_row: int | None,
    jsonl_index: int | None = None,
    json_index: list[int] | None = None,
    alias_path: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "payload_row": payload_row,
    }
    if jsonl_index is not None:
        payload["jsonl_index"] = jsonl_index
    if json_index:
        payload["json_index"] = list(json_index)
    if alias_path:
        payload["alias_path"] = alias_path
    return payload


def _matches_case_id(recipe_id: str, expected_case_id: str, delta: float | None) -> bool:
    return _recipe_case_id(recipe_id, delta) == expected_case_id


def _parse_line_range_selector(text: str) -> tuple[str, int, int]:
    raw = str(text or "").strip()
    if not raw:
        raise ValueError("Invalid --include-line-range value: <empty>")

    parts = raw.split(":")
    if len(parts) >= 3:
        source_key = ":".join(parts[:-2]).strip()
        start = _coerce_int(parts[-2])
        end = _coerce_int(parts[-1])
        if source_key and start is not None and end is not None:
            return source_key, start, end

    if len(parts) >= 2:
        source_key = ":".join(parts[:-1]).strip()
        start_end = parts[-1].strip()
        if source_key and "-" in start_end:
            start_text, end_text = start_end.split("-", 1)
            start = _coerce_int(start_text)
            end = _coerce_int(end_text)
            if start is not None and end is not None:
                return source_key, start, end

    raise ValueError(f"Invalid --include-line-range value: {raw}")


@dataclass(frozen=True)
class PayloadArtifact:
    path: str
    payload_row: int
    row: dict[str, Any]


@dataclass(frozen=True)
class PromptArtifactLink:
    atomic_index: int
    parsed_label: str | None
    prompt_file: Path | None
    response_file: Path | None
    parsed_file: Path | None


class RunContext:
    def __init__(
        self,
        *,
        repo_root: Path,
        source_root: Path,
        output_subdir: str,
        source_key: str,
        run_id: str,
        source_file: str | None,
    ) -> None:
        self.repo_root = repo_root
        self.source_root = source_root
        self.output_subdir = output_subdir
        self.source_key = source_key
        self.run_id = run_id
        self.source_file = source_file
        self.run_dir = (source_root / output_subdir).resolve()
        self._run_manifest: dict[str, Any] | None = None
        self._line_role_predictions_by_index: dict[int, dict[str, Any]] | None = None
        self._extracted_lines_by_index: dict[int, dict[str, Any]] | None = None
        self._prompt_links_by_atomic_index: dict[int, PromptArtifactLink] | None = None
        self._raw_llm_dir: Path | None | object = ...

    @property
    def codex_enabled(self) -> bool:
        pipeline = str(self.run_manifest.get("run_config", {}).get("llm_recipe_pipeline") or "").strip()
        return pipeline not in {"", "off", "none"}

    @property
    def run_manifest(self) -> dict[str, Any]:
        if self._run_manifest is None:
            path = self.run_dir / "run_manifest.json"
            self._run_manifest = _read_json(path) if path.is_file() else {}
        return self._run_manifest

    @property
    def line_role_predictions_by_index(self) -> dict[int, dict[str, Any]]:
        if self._line_role_predictions_by_index is None:
            rows: dict[int, dict[str, Any]] = {}
            path = self.run_dir / "line-role-pipeline" / "line_role_predictions.jsonl"
            for row in _read_jsonl(path):
                atomic_index = _coerce_int(row.get("atomic_index"))
                if atomic_index is None:
                    continue
                rows[atomic_index] = row
            self._line_role_predictions_by_index = rows
        return self._line_role_predictions_by_index

    @property
    def extracted_lines_by_index(self) -> dict[int, dict[str, Any]]:
        if self._extracted_lines_by_index is None:
            rows: dict[int, dict[str, Any]] = {}
            candidates = [
                self.run_dir / "line-role-pipeline" / "extracted_archive.json",
                self.run_dir / "extracted_archive.json",
            ]
            payload: Any = None
            for path in candidates:
                if path.is_file():
                    payload = _read_json(path)
                    break
            if isinstance(payload, list):
                for row in payload:
                    if not isinstance(row, dict):
                        continue
                    location = row.get("location")
                    line_index = _coerce_int(
                        location.get("line_index") if isinstance(location, dict) else None
                    )
                    if line_index is None:
                        line_index = _coerce_int(row.get("index"))
                    if line_index is None:
                        continue
                    rows[line_index] = row
            self._extracted_lines_by_index = rows
        return self._extracted_lines_by_index

    @property
    def prompt_links_by_atomic_index(self) -> dict[int, PromptArtifactLink]:
        if self._prompt_links_by_atomic_index is None:
            prompt_dir = self.run_dir / "line-role-pipeline" / "prompts"
            rows: dict[int, PromptArtifactLink] = {}
            if prompt_dir.is_dir():
                for parsed_path in sorted(prompt_dir.glob("parsed_*.json")):
                    match = re.search(r"parsed_(\d+)\.json$", parsed_path.name)
                    if not match:
                        continue
                    suffix = match.group(1)
                    prompt_path = prompt_dir / f"prompt_{suffix}.txt"
                    response_path = prompt_dir / f"response_{suffix}.txt"
                    payload = _read_json(parsed_path)
                    if not isinstance(payload, list):
                        continue
                    for item in payload:
                        if not isinstance(item, dict):
                            continue
                        atomic_index = _coerce_int(item.get("atomic_index"))
                        if atomic_index is None or atomic_index in rows:
                            continue
                        rows[atomic_index] = PromptArtifactLink(
                            atomic_index=atomic_index,
                            parsed_label=str(item.get("label") or "").strip() or None,
                            prompt_file=prompt_path if prompt_path.is_file() else None,
                            response_file=response_path if response_path.is_file() else None,
                            parsed_file=parsed_path,
                        )
            self._prompt_links_by_atomic_index = rows
        return self._prompt_links_by_atomic_index

    @property
    def raw_llm_dir(self) -> Path | None:
        if self._raw_llm_dir is ...:
            resolved: Path | None = None
            for candidate_root in (
                self.run_dir / "raw" / "llm",
                self.run_dir / "prediction-run" / "raw" / "llm",
            ):
                if not candidate_root.is_dir():
                    continue
                for child in sorted(candidate_root.iterdir()):
                    if child.is_dir():
                        resolved = child
                        break
                if resolved is not None:
                    break
            self._raw_llm_dir = resolved
        return self._raw_llm_dir

    def recipe_artifact_paths(self, recipe_id: str) -> dict[str, str]:
        suffix = _recipe_suffix(recipe_id)
        if not suffix or self.raw_llm_dir is None:
            return {}
        resolved: dict[str, str] = {}
        audit_path = self.raw_llm_dir / "recipe_correction_audit" / _recipe_artifact_filename(recipe_id)
        if audit_path.is_file():
            resolved["recipe_correction_audit"] = str(audit_path)
        return resolved

    def knowledge_artifact_paths(self) -> dict[str, str]:
        resolved: dict[str, str] = {}
        prompts_dir = self.run_dir / "prompts"
        knowledge_prompt_task = _resolve_knowledge_prompt_task_path(prompts_dir)
        prompt_budget_candidates = [
            self.run_dir / "prediction-run" / "prompt_budget_summary.json",
            self.run_dir / "prompt_budget_summary.json",
        ]
        for label, candidates in (
            ("prompt_samples_md", [prompts_dir / "prompt_type_samples_from_full_prompt_log.md"]),
            ("prompt_knowledge_txt", [knowledge_prompt_task] if isinstance(knowledge_prompt_task, Path) else []),
            ("prompt_budget_summary_json", prompt_budget_candidates),
        ):
            for path in candidates:
                if isinstance(path, Path) and path.is_file():
                    resolved[label] = str(path)
                    break
        if self.raw_llm_dir is not None:
            manifest_path = self.raw_llm_dir / "knowledge_manifest.json"
            if manifest_path.is_file():
                resolved["knowledge_manifest_json"] = str(manifest_path)
        return resolved


class FollowupBundleContext:
    def __init__(self, *, repo_root: Path, bundle_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.bundle_dir = bundle_dir.resolve()
        self.index = _read_json(
            oracle_benchmark_review_packet_file(
                self.bundle_dir,
                ORACLE_REVIEW_PROFILE_QUALITY,
                BENCHMARK_UPLOAD_BUNDLE_INDEX_FILE_NAME,
            )
        )
        self.source_root = Path(
            str(self.index.get("source_dir") or self.bundle_dir.parent)
        ).resolve()
        self.payload_artifacts: list[PayloadArtifact] = []
        self.payload_by_path: dict[str, PayloadArtifact] = {}
        payload_path = oracle_benchmark_review_packet_file(
            self.bundle_dir,
            ORACLE_REVIEW_PROFILE_QUALITY,
            BENCHMARK_UPLOAD_BUNDLE_PAYLOAD_FILE_NAME,
        )
        payload_packet = _read_json(payload_path)
        payload_rows = payload_packet.get("rows") if isinstance(payload_packet, dict) else []
        payload_rows = payload_rows if isinstance(payload_rows, list) else []
        for payload_row, payload in enumerate(payload_rows, start=1):
            if not isinstance(payload, dict):
                continue
            path = str(payload.get("path") or "").strip()
            if not path:
                continue
            artifact = PayloadArtifact(path=path, payload_row=payload_row, row=payload)
            self.payload_artifacts.append(artifact)
            self.payload_by_path[path] = artifact
        self.runs: list[RunContext] = []
        for row in self.index.get("run_diagnostics") or []:
            if not isinstance(row, dict):
                continue
            output_subdir = str(row.get("output_subdir") or "").strip()
            source_key = str(row.get("source_key") or "").strip()
            if not output_subdir or not source_key:
                continue
            self.runs.append(
                RunContext(
                    repo_root=self.repo_root,
                    source_root=self.source_root,
                    output_subdir=output_subdir,
                    source_key=source_key,
                    run_id=str(row.get("run_id") or "").strip() or Path(output_subdir).name,
                    source_file=str(row.get("source_file") or "").strip() or None,
                )
            )
        self.runs.sort(key=lambda row: (row.source_key, 0 if row.codex_enabled else 1, row.output_subdir))
        self._changed_lines = self._load_changed_lines()
        self._triage_rows = self._load_triage_rows()
        self._per_recipe_rows = self._load_per_recipe_rows()
        self._stage_rows = self._load_stage_rows()
        self._knowledge_rows = self._load_knowledge_rows()

    @property
    def generated_at(self) -> str:
        return _bundle_generated_at(self.index)

    @property
    def git_sha(self) -> str:
        return _git_sha(self.repo_root)

    @property
    def bundle_sha256(self) -> str:
        return _bundle_sha256(self.bundle_dir)

    def payload_locator_for_path(self, path: str) -> dict[str, Any] | None:
        artifact = self.payload_by_path.get(path)
        if artifact is None:
            return None
        return _locator(path=artifact.path, payload_row=artifact.payload_row)

    def payload_locator_for_file(self, path: Path) -> dict[str, Any] | None:
        relative = _relative_path(self.source_root, path)
        artifact = self.payload_by_path.get(relative)
        if artifact is None:
            return None
        return _locator(path=artifact.path, payload_row=artifact.payload_row)

    def codex_run_for_source(self, source_key: str) -> RunContext | None:
        for run in self.runs:
            if run.source_key == source_key and run.codex_enabled:
                return run
        return None

    def baseline_run_for_source(self, source_key: str) -> RunContext | None:
        for run in self.runs:
            if run.source_key == source_key and not run.codex_enabled:
                return run
        return None

    def per_recipe_row(self, source_key: str, recipe_id: str) -> dict[str, Any] | None:
        return self._per_recipe_rows.get((source_key, recipe_id))

    def triage_row(self, source_key: str, recipe_id: str) -> dict[str, Any] | None:
        return self._triage_rows.get((source_key, recipe_id))

    def stage_row(self, source_key: str, recipe_id: str) -> dict[str, Any] | None:
        return self._stage_rows.get((source_key, recipe_id))

    def changed_lines_for_recipe(self, source_key: str, recipe_id: str) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._changed_lines
            if str(row.get("source_key") or "") == source_key
            and str(row.get("recipe_id") or "") == recipe_id
        ]
        rows.sort(key=lambda row: int(row.get("line_index") or 0))
        return rows

    def changed_lines_for_range(self, source_key: str, start: int, end: int) -> list[dict[str, Any]]:
        rows = [
            row
            for row in self._changed_lines
            if str(row.get("source_key") or "") == source_key
            and start <= int(row.get("line_index") or -1) <= end
        ]
        rows.sort(key=lambda row: int(row.get("line_index") or 0))
        return rows

    def run_for_output_subdir(self, output_subdir: str) -> RunContext | None:
        for run in self.runs:
            if run.output_subdir == output_subdir:
                return run
        return None

    def knowledge_row_for_output_subdir(self, output_subdir: str) -> dict[str, Any] | None:
        return self._knowledge_rows.get(output_subdir)

    def knowledge_row_for_source(self, source_key: str) -> dict[str, Any] | None:
        run = self.codex_run_for_source(source_key)
        if run is None:
            return None
        return self.knowledge_row_for_output_subdir(run.output_subdir)

    def knowledge_locators_for_run(self, run: RunContext) -> dict[str, dict[str, Any]]:
        locators: dict[str, dict[str, Any]] = {}
        knowledge_rows = (
            ((self.index.get("navigation") or {}).get("row_locators") or {}).get("knowledge_by_run")
        )
        if isinstance(knowledge_rows, list):
            for row in knowledge_rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("output_subdir") or "").strip() != run.output_subdir:
                    continue
                for label in (
                    "prompt_samples_md",
                    "prompt_knowledge_txt",
                    "knowledge_manifest_json",
                    "prompt_budget_summary_json",
                ):
                    locator = row.get(label)
                    if isinstance(locator, dict):
                        locators[label] = locator
                break
        for label, raw_path in run.knowledge_artifact_paths().items():
            locator = self.payload_locator_for_file(Path(raw_path))
            if locator is not None:
                locators[label] = locator
        return locators

    def _load_changed_lines(self) -> list[dict[str, Any]]:
        artifact = self.payload_by_path.get(CHANGED_LINES_PAYLOAD_PATH)
        if artifact is None:
            return []
        rows = artifact.row.get("content_jsonl_rows")
        if not isinstance(rows, list):
            return []
        normalized: list[dict[str, Any]] = []
        for jsonl_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            normalized.append(
                {
                    **row,
                    "_payload_locator": _locator(
                        path=artifact.path,
                        payload_row=artifact.payload_row,
                        jsonl_index=jsonl_index,
                    ),
                }
            )
        return normalized

    def _load_triage_rows(self) -> dict[tuple[str, str], dict[str, Any]]:
        artifact = self.payload_by_path.get(TRIAGE_PACKET_PAYLOAD_PATH)
        if artifact is None:
            return {}
        rows = artifact.row.get("content_jsonl_rows")
        if not isinstance(rows, list):
            return {}
        normalized: dict[tuple[str, str], dict[str, Any]] = {}
        for jsonl_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            source_key = str(row.get("source_key") or "").strip()
            recipe_id = str(row.get("recipe_id") or "").strip()
            if not source_key or not recipe_id:
                continue
            normalized[(source_key, recipe_id)] = {
                **row,
                "_payload_locator": _locator(
                    path=artifact.path,
                    payload_row=artifact.payload_row,
                    jsonl_index=jsonl_index,
                ),
            }
        return normalized

    def _load_per_recipe_rows(self) -> dict[tuple[str, str], dict[str, Any]]:
        artifact = self.payload_by_path.get(PER_RECIPE_BREAKDOWN_PAYLOAD_PATH)
        if artifact is None:
            return {}
        payload = artifact.row.get("content_json")
        if not isinstance(payload, dict):
            return {}
        pairs = payload.get("pairs")
        if not isinstance(pairs, list):
            return {}
        normalized: dict[tuple[str, str], dict[str, Any]] = {}
        for pair_index, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                continue
            source_key = str(pair.get("source_key") or "").strip()
            rows = pair.get("per_recipe_breakdown")
            if not source_key or not isinstance(rows, list):
                continue
            for recipe_index, recipe_row in enumerate(rows):
                if not isinstance(recipe_row, dict):
                    continue
                recipe_id = str(recipe_row.get("recipe_id") or "").strip()
                if not recipe_id:
                    continue
                normalized[(source_key, recipe_id)] = {
                    **recipe_row,
                    "source_key": source_key,
                    "source_file": pair.get("source_file"),
                    "codex_run_id": pair.get("codex_run_id"),
                    "baseline_run_id": pair.get("baseline_run_id"),
                    "region_breakdown": pair.get("region_breakdown"),
                    "_payload_locator": _locator(
                        path=artifact.path,
                        payload_row=artifact.payload_row,
                        json_index=[pair_index, recipe_index],
                    ),
                }
        return normalized

    def _load_stage_rows(self) -> dict[tuple[str, str], dict[str, Any]]:
        analysis = self.index.get("analysis")
        if not isinstance(analysis, dict):
            return {}
        payload = analysis.get("stage_separated_comparison")
        if not isinstance(payload, dict):
            return {}
        rows = payload.get("per_recipe")
        if not isinstance(rows, list):
            return {}
        normalized: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            source_key = str(row.get("source_key") or "").strip()
            recipe_id = str(row.get("recipe_id") or "").strip()
            if not source_key or not recipe_id:
                continue
            normalized[(source_key, recipe_id)] = row
        return normalized

    def _load_knowledge_rows(self) -> dict[str, dict[str, Any]]:
        analysis = self.index.get("analysis")
        if not isinstance(analysis, dict):
            return {}
        payload = analysis.get("knowledge")
        if not isinstance(payload, dict):
            return {}
        rows = payload.get("rows")
        if not isinstance(rows, list):
            return {}
        normalized: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            output_subdir = str(row.get("output_subdir") or "").strip()
            if not output_subdir:
                continue
            normalized[output_subdir] = {
                **row,
                "source_key": str(row.get("source_key") or "").strip(),
                "book_slug": _source_key_from_output_subdir(output_subdir),
            }
        return normalized


def load_followup_bundle_context(bundle_dir: Path) -> FollowupBundleContext:
    repo_root = bundle_dir.resolve()
    while repo_root != repo_root.parent:
        if (repo_root / "pyproject.toml").is_file():
            break
        repo_root = repo_root.parent
    return FollowupBundleContext(repo_root=repo_root, bundle_dir=bundle_dir)


def _structure_report_pair_rows(context: FollowupBundleContext) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_keys = sorted({run.source_key for run in context.runs if run.source_key})
    for source_key in source_keys:
        codex_run = context.codex_run_for_source(source_key)
        baseline_run = context.baseline_run_for_source(source_key)
        if codex_run is None or baseline_run is None:
            continue
        rows.append(
            {
                "source_key": source_key,
                "codex_run_id": codex_run.run_id,
                "baseline_run_id": baseline_run.run_id,
            }
        )
    return rows


def write_structure_report(
    *,
    bundle_dir: Path,
    out_path: Path,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    analysis = context.index.get("analysis")
    analysis = analysis if isinstance(analysis, dict) else {}
    existing = analysis.get("structure_label_report")
    if isinstance(existing, dict):
        payload = existing
    else:
        per_label_metrics = analysis.get("per_label_metrics")
        per_label_metrics = per_label_metrics if isinstance(per_label_metrics, list) else []
        payload = build_structure_label_report(
            per_label_metrics=[row for row in per_label_metrics if isinstance(row, dict)],
            pair_rows=_structure_report_pair_rows(context),
            run_dir_by_id={run.run_id: run.run_dir for run in context.runs},
        )
    _write_json(out_path, payload)
    return payload


def _build_outside_span_candidates(
    context: FollowupBundleContext,
) -> dict[str, dict[str, Any]]:
    by_source: dict[str, list[int]] = {}
    for row in context._changed_lines:
        if str(row.get("span_region") or "") != "outside_active_recipe_span":
            continue
        source_key = str(row.get("source_key") or "").strip()
        line_index = _coerce_int(row.get("line_index"))
        if not source_key or line_index is None:
            continue
        by_source.setdefault(source_key, []).append(line_index)

    candidates: dict[str, dict[str, Any]] = {}
    for source_key, indices in sorted(by_source.items()):
        current: list[int] = []
        for line_index in sorted(set(indices)):
            if not current or line_index == current[-1] + 1:
                current.append(line_index)
            else:
                start = current[0]
                end = current[-1]
                case_id = f"outside_span_window_{start}_{end}"
                selected_rows = context.changed_lines_for_range(source_key, start, end)
                candidates[case_id] = {
                    "case_id": case_id,
                    "source_key": source_key,
                    "start": start,
                    "end": end,
                    "changed_line_count": len(selected_rows),
                    "payload_locators": [row["_payload_locator"] for row in selected_rows],
                    "reason": "derived_outside_span_group",
                }
                current = [line_index]
        if current:
            start = current[0]
            end = current[-1]
            case_id = f"outside_span_window_{start}_{end}"
            selected_rows = context.changed_lines_for_range(source_key, start, end)
            candidates[case_id] = {
                "case_id": case_id,
                "source_key": source_key,
                "start": start,
                "end": end,
                "changed_line_count": len(selected_rows),
                "payload_locators": [row["_payload_locator"] for row in selected_rows],
                "reason": "derived_outside_span_group",
            }
    return candidates


def _selector_payload_locators(
    *,
    per_recipe_row: dict[str, Any] | None,
    triage_row: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    locators: list[dict[str, Any]] = []
    for row in (per_recipe_row, triage_row):
        if isinstance(row, dict):
            locator = row.get("_payload_locator")
            if isinstance(locator, dict):
                locators.append(locator)
    return locators


def _sorted_recipe_delta_rows(context: FollowupBundleContext) -> list[dict[str, Any]]:
    return sorted(
        (
            row
            for row in context._per_recipe_rows.values()
            if _coerce_float(row.get("delta_codex_minus_baseline")) is not None
        ),
        key=lambda row: (
            _coerce_float(row.get("delta_codex_minus_baseline")) or 0.0,
            str(row.get("recipe_id") or ""),
        ),
    )


def _sorted_recipe_signal_rows(context: FollowupBundleContext) -> list[dict[str, Any]]:
    return sorted(
        context._per_recipe_rows.values(),
        key=lambda row: (
            -int(_coerce_int(row.get("outside_span_wrong_line_count")) or 0),
            -int(_coerce_int(row.get("changed_lines_codex_vs_baseline")) or 0),
            -int(_coerce_int(row.get("recipe_error_count")) or 0),
            -int(_coerce_int(row.get("recipe_warning_count")) or 0),
            str(row.get("recipe_id") or ""),
        ),
    )


def _sorted_outside_span_candidates(
    context: FollowupBundleContext,
) -> list[dict[str, Any]]:
    return sorted(
        _build_outside_span_candidates(context).values(),
        key=lambda row: (
            -(int(row.get("changed_line_count") or 0)),
            str(row.get("source_key") or ""),
            int(row.get("start") or 0),
            int(row.get("end") or 0),
        ),
    )


def _default_line_role_followup_ask(
    context: FollowupBundleContext,
) -> dict[str, Any]:
    selectors: dict[str, Any] = {
        "top_neg": 0,
        "top_pos": 0,
        "outside_span": 0,
        "stage_filters": ["line_role"],
        "include_case_ids": [],
        "include_recipe_ids": [],
        "include_line_ranges": [],
        "include_knowledge_source_keys": [],
        "include_knowledge_output_subdirs": [],
    }
    question = "Show provenance and nearby context for the most relevant line-role issue."

    recipe_rows = _sorted_recipe_delta_rows(context)
    negative_recipe_rows = [
        row for row in recipe_rows if (_coerce_float(row.get("delta_codex_minus_baseline")) or 0.0) < 0.0
    ]
    if negative_recipe_rows:
        row = negative_recipe_rows[0]
        case_id = _recipe_case_id(
            str(row.get("recipe_id") or ""),
            _coerce_float(row.get("delta_codex_minus_baseline")),
        )
        selectors["include_case_ids"] = [case_id]
        question = f"Why does {case_id} look wrong? Show provenance and nearby context."
    else:
        outside_candidates = _sorted_outside_span_candidates(context)
        if outside_candidates:
            case_id = str(outside_candidates[0].get("case_id") or "").strip()
            if case_id:
                selectors["include_case_ids"] = [case_id]
                question = (
                    f"Why does {case_id} look wrong? Show provenance and nearby context."
                )
            else:
                question = (
                    "Show provenance and nearby context for the most relevant "
                    "outside-span issue."
                )
        else:
            signal_rows = _sorted_recipe_signal_rows(context)
            if signal_rows:
                row = signal_rows[0]
                case_id = _recipe_case_id(
                    str(row.get("recipe_id") or ""),
                    _coerce_float(row.get("delta_codex_minus_baseline")),
                )
                selectors["include_case_ids"] = [case_id]
                question = (
                    f"Why does {case_id} look like the highest-signal line-role issue? "
                    "Show provenance and nearby context."
                )
            else:
                question = (
                    "This bundle has no precomputed recipe or outside-span cases. "
                    "Fill in selectors for the follow-up you want."
                )

    return {
        "ask_id": "ask_001",
        "question": question,
        "outputs": [
            "case_export",
            "line_role_audit",
            "prompt_link_audit",
            "page_context",
            "uncertainty",
        ],
        "selectors": selectors,
        "notes": (
            "Use case IDs, recipe IDs, or explicit line ranges that the requester "
            "can trace back to upload_bundle_v1."
        ),
    }


def build_selector_manifest(
    *,
    context: FollowupBundleContext,
    command: str,
    stage_filters: list[str] | None,
    top_neg: int,
    top_pos: int,
    outside_span: int,
    include_case_ids: list[str],
    include_recipe_ids: list[str],
    include_line_ranges: list[str],
    include_knowledge_source_keys: list[str],
    include_knowledge_output_subdirs: list[str],
) -> dict[str, Any]:
    stages = [stage.strip().lower() for stage in stage_filters or [] if stage.strip()]
    unsupported = [stage for stage in stages if stage not in SUPPORTED_STAGE_FILTERS]
    if unsupported:
        raise ValueError(
            f"Unsupported stage filter(s): {', '.join(sorted(set(unsupported)))}"
        )

    selectors: dict[str, dict[str, Any]] = {}

    recipe_rows = list(context._per_recipe_rows.values())
    negatives = _sorted_recipe_delta_rows(context)
    positives = sorted(
        (row for row in recipe_rows if _coerce_float(row.get("delta_codex_minus_baseline")) is not None),
        key=lambda row: (
            -(_coerce_float(row.get("delta_codex_minus_baseline")) or 0.0),
            str(row.get("recipe_id") or ""),
        ),
    )

    def add_recipe_selector(row: dict[str, Any], *, reason: str, reason_rank: int) -> None:
        source_key = str(row.get("source_key") or "").strip()
        recipe_id = str(row.get("recipe_id") or "").strip()
        if not source_key or not recipe_id:
            return
        triage_row = context.triage_row(source_key, recipe_id)
        stage_row = context.stage_row(source_key, recipe_id)
        delta = _coerce_float(row.get("delta_codex_minus_baseline"))
        selector = {
            "selector_id": _selector_id_for_recipe(source_key, recipe_id),
            "case_id": _recipe_case_id(recipe_id, delta),
            "kind": "recipe",
            "source_key": source_key,
            "recipe_id": recipe_id,
            "short_title": (
                str(stage_row.get("short_title") or "").strip()
                if isinstance(stage_row, dict)
                else ""
            ),
            "reason": reason,
            "reason_rank": reason_rank,
            "payload_locators": _selector_payload_locators(
                per_recipe_row=row,
                triage_row=triage_row,
            ),
        }
        selectors[selector["selector_id"]] = selector

    def add_knowledge_selector(
        run: RunContext,
        knowledge_row: dict[str, Any] | None,
        *,
        reason: str,
        reason_rank: int,
    ) -> None:
        summary = dict(knowledge_row or {})
        book_slug = _source_key_from_output_subdir(run.output_subdir)
        selector = {
            "selector_id": _selector_id_for_knowledge_run(run.output_subdir),
            "case_id": _knowledge_case_id(book_slug, run.output_subdir),
            "kind": "knowledge_run",
            "source_key": run.source_key,
            "book_slug": book_slug,
            "book": run.source_file,
            "output_subdir": run.output_subdir,
            "run_id": run.run_id,
            "reason": reason,
            "reason_rank": reason_rank,
            "enabled": bool(summary.get("enabled")),
            "payload_locators": list(context.knowledge_locators_for_run(run).values()),
        }
        selectors[selector["selector_id"]] = selector

    for rank, row in enumerate(negatives[: max(0, top_neg)], start=1):
        add_recipe_selector(row, reason="top_negative_delta", reason_rank=rank)

    for rank, row in enumerate(positives[: max(0, top_pos)], start=1):
        add_recipe_selector(row, reason="top_positive_delta", reason_rank=rank)

    outside_candidates = _build_outside_span_candidates(context)
    selected_outside = _sorted_outside_span_candidates(context)
    for rank, row in enumerate(selected_outside[: max(0, outside_span)], start=1):
        selector = {
            "selector_id": _selector_id_for_line_range(
                str(row.get("source_key") or ""),
                int(row.get("start") or 0),
                int(row.get("end") or 0),
            ),
            "case_id": str(row.get("case_id") or ""),
            "kind": "line_range",
            "source_key": str(row.get("source_key") or ""),
            "start": int(row.get("start") or 0),
            "end": int(row.get("end") or 0),
            "reason": "outside_span_window",
            "reason_rank": rank,
            "payload_locators": list(row.get("payload_locators") or []),
        }
        selectors[selector["selector_id"]] = selector

    for recipe_id in include_recipe_ids:
        recipe_text = recipe_id.strip()
        if not recipe_text:
            continue
        matching = [row for row in recipe_rows if str(row.get("recipe_id") or "") == recipe_text]
        if not matching:
            raise ValueError(f"Could not resolve recipe_id: {recipe_text}")
        add_recipe_selector(matching[0], reason="explicit_recipe_id", reason_rank=0)

    for raw_value in include_line_ranges:
        text = raw_value.strip()
        if not text:
            continue
        source_key, start, end = _parse_line_range_selector(text)
        if start > end:
            start, end = end, start
        selected_rows = context.changed_lines_for_range(source_key, start, end)
        selector = {
            "selector_id": _selector_id_for_line_range(source_key, start, end),
            "case_id": f"line_range_{start}_{end}",
            "kind": "line_range",
            "source_key": source_key,
            "start": start,
            "end": end,
            "reason": "explicit_line_range",
            "reason_rank": 0,
            "payload_locators": [row["_payload_locator"] for row in selected_rows],
        }
        selectors[selector["selector_id"]] = selector

    for source_key in include_knowledge_source_keys:
        source_text = source_key.strip()
        if not source_text:
            continue
        run = context.codex_run_for_source(source_text)
        if run is None:
            matching_runs = [
                candidate
                for candidate in context.runs
                if candidate.codex_enabled
                and _source_key_from_output_subdir(candidate.output_subdir) == source_text
            ]
            if len(matching_runs) == 1:
                run = matching_runs[0]
        if run is None:
            matching_runs = [
                candidate
                for candidate in context.runs
                if context.knowledge_row_for_output_subdir(candidate.output_subdir) is not None
                and (
                    candidate.source_key == source_text
                    or _source_key_from_output_subdir(candidate.output_subdir) == source_text
                )
            ]
            if len(matching_runs) == 1:
                run = matching_runs[0]
        if run is None:
            raise ValueError(f"Could not resolve knowledge source_key: {source_text}")
        add_knowledge_selector(
            run,
            context.knowledge_row_for_output_subdir(run.output_subdir),
            reason="explicit_knowledge_source_key",
            reason_rank=0,
        )

    for output_subdir in include_knowledge_output_subdirs:
        output_text = output_subdir.strip()
        if not output_text:
            continue
        run = context.run_for_output_subdir(output_text)
        if run is None:
            raise ValueError(f"Could not resolve knowledge output_subdir: {output_text}")
        add_knowledge_selector(
            run,
            context.knowledge_row_for_output_subdir(run.output_subdir),
            reason="explicit_knowledge_output_subdir",
            reason_rank=0,
        )

    for case_id in include_case_ids:
        case_text = case_id.strip()
        if not case_text:
            continue
        matched = False
        for row in recipe_rows:
            if _matches_case_id(
                str(row.get("recipe_id") or ""),
                case_text,
                _coerce_float(row.get("delta_codex_minus_baseline")),
            ):
                add_recipe_selector(row, reason="explicit_case_id", reason_rank=0)
                matched = True
                break
        if matched:
            continue
        outside_row = outside_candidates.get(case_text)
        if outside_row is not None:
            selector = {
                "selector_id": _selector_id_for_line_range(
                    str(outside_row.get("source_key") or ""),
                    int(outside_row.get("start") or 0),
                    int(outside_row.get("end") or 0),
                ),
                "case_id": case_text,
                "kind": "line_range",
                "source_key": str(outside_row.get("source_key") or ""),
                "start": int(outside_row.get("start") or 0),
                "end": int(outside_row.get("end") or 0),
                "reason": "explicit_case_id",
                "reason_rank": 0,
                "payload_locators": list(outside_row.get("payload_locators") or []),
            }
            selectors[selector["selector_id"]] = selector
            continue
        if not matched:
            for run in context.runs:
                if _knowledge_case_id(
                    _source_key_from_output_subdir(run.output_subdir),
                    run.output_subdir,
                ) != case_text:
                    continue
                add_knowledge_selector(
                    run,
                    context.knowledge_row_for_output_subdir(run.output_subdir),
                    reason="explicit_case_id",
                    reason_rank=0,
                )
                matched = True
                break
        if not matched:
            raise ValueError(f"Could not resolve case_id: {case_text}")

    ordered_selectors = sorted(
        selectors.values(),
        key=lambda row: (
            int(row.get("reason_rank") or 0),
            str(row.get("case_id") or ""),
            str(row.get("selector_id") or ""),
        ),
    )

    return {
        "schema_version": SELECTOR_SCHEMA_VERSION,
        "generated_at": context.generated_at,
        "command": command,
        "git_sha": context.git_sha,
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "stage_filters": stages,
        "selectors": ordered_selectors,
    }


def write_selector_manifest(
    *,
    bundle_dir: Path,
    out_path: Path,
    command: str,
    stage_filters: list[str] | None,
    top_neg: int,
    top_pos: int,
    outside_span: int,
    include_case_ids: list[str],
    include_recipe_ids: list[str],
    include_line_ranges: list[str],
    include_knowledge_source_keys: list[str],
    include_knowledge_output_subdirs: list[str],
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    manifest = build_selector_manifest(
        context=context,
        command=command,
        stage_filters=stage_filters,
        top_neg=top_neg,
        top_pos=top_pos,
        outside_span=outside_span,
        include_case_ids=include_case_ids,
        include_recipe_ids=include_recipe_ids,
        include_line_ranges=include_line_ranges,
        include_knowledge_source_keys=include_knowledge_source_keys,
        include_knowledge_output_subdirs=include_knowledge_output_subdirs,
    )
    _write_json(out_path, manifest)
    return manifest


def write_followup_request_template(
    *,
    bundle_dir: Path,
    out_path: Path,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    asks: list[dict[str, Any]] = [_default_line_role_followup_ask(context)]
    first_knowledge_row = next(
        (
            row
            for row in context._knowledge_rows.values()
            if bool(row.get("enabled")) and str(row.get("output_subdir") or "").strip()
        ),
        None,
    )
    if first_knowledge_row is not None:
        asks.append(
            {
                "ask_id": "ask_002_knowledge",
                "question": "Show the knowledge-stage evidence for this run.",
                "outputs": ["case_export", "knowledge_audit"],
                "selectors": {
                    "top_neg": 0,
                    "top_pos": 0,
                    "outside_span": 0,
                    "stage_filters": ["knowledge"],
                    "include_case_ids": [],
                    "include_recipe_ids": [],
                    "include_line_ranges": [],
                    "include_knowledge_source_keys": [],
                    "include_knowledge_output_subdirs": [
                        str(first_knowledge_row.get("output_subdir") or "").strip()
                    ],
                },
                "notes": (
                    "Use this when the requester wants knowledge-stage prompts/manifests and "
                    "run-level knowledge status instead of line-role evidence."
                ),
            }
        )
    template = {
        "schema_version": FOLLOWUP_REQUEST_SCHEMA_VERSION,
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "request_id": "followup_request_01",
        "request_summary": (
            "Fill in the web AI's follow-up asks. Assume the requester already has "
            "upload_bundle_v1 and only needs new evidence or row-locator references."
        ),
        "requester_context": {
            "already_has_upload_bundle_v1": True,
            "prefer_new_local_artifacts_over_bundle_repeats": True,
            "duplicate_bundle_payloads_only_when_needed_for_context": True,
        },
        "default_stage_filters": ["line_role"],
        "asks": asks,
    }
    _write_json(out_path, template)
    return template


def _load_selectors(selector_path: Path) -> list[dict[str, Any]]:
    payload = _read_json(selector_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected selector manifest object in {selector_path}")
    selectors = payload.get("selectors")
    if not isinstance(selectors, list):
        raise ValueError(f"Expected selectors array in {selector_path}")
    rows = [row for row in selectors if isinstance(row, dict)]
    rows.sort(key=lambda row: str(row.get("selector_id") or ""))
    return rows


def _load_followup_request(request_path: Path) -> dict[str, Any]:
    payload = _read_json(request_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected follow-up request object in {request_path}")
    schema_version = str(payload.get("schema_version") or "").strip()
    if schema_version != FOLLOWUP_REQUEST_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported follow-up request schema_version: {schema_version or '<missing>'}"
        )
    asks = payload.get("asks")
    if not isinstance(asks, list) or not asks:
        raise ValueError("Follow-up request must contain at least one ask.")
    return payload


def _normalize_requested_outputs(value: Any) -> list[str]:
    rows = _coerce_str_list(value)
    if not rows:
        raise ValueError("Each ask must request at least one output.")
    expanded: list[str] = []
    for row in rows:
        normalized = row.strip().lower()
        if normalized == "all":
            expanded.extend(
                [
                    "structure_report",
                    "case_export",
                    "line_role_audit",
                    "prompt_link_audit",
                    "knowledge_audit",
                    "page_context",
                    "uncertainty",
                ]
            )
            continue
        expanded.append(normalized)
    allowed = {
        "structure_report",
        "case_export",
        "line_role_audit",
        "prompt_link_audit",
        "knowledge_audit",
        "page_context",
        "uncertainty",
    }
    invalid = sorted({row for row in expanded if row not in allowed})
    if invalid:
        raise ValueError(f"Unsupported ask output(s): {', '.join(invalid)}")
    deduped: list[str] = []
    seen: set[str] = set()
    for row in expanded:
        if row in seen:
            continue
        seen.add(row)
        deduped.append(row)
    return deduped


def _normalize_followup_selector_config(
    *,
    ask: dict[str, Any],
    default_stage_filters: list[str],
) -> dict[str, Any]:
    selectors = ask.get("selectors")
    selectors = selectors if isinstance(selectors, dict) else {}
    return {
        "top_neg": int(_coerce_int(selectors.get("top_neg")) or 0),
        "top_pos": int(_coerce_int(selectors.get("top_pos")) or 0),
        "outside_span": int(_coerce_int(selectors.get("outside_span")) or 0),
        "stage_filters": (
            _coerce_str_list(selectors.get("stage_filters")) or list(default_stage_filters)
        ),
        "include_case_ids": _coerce_str_list(selectors.get("include_case_ids")),
        "include_recipe_ids": _coerce_str_list(selectors.get("include_recipe_ids")),
        "include_line_ranges": _coerce_str_list(selectors.get("include_line_ranges")),
        "include_knowledge_source_keys": _coerce_str_list(selectors.get("include_knowledge_source_keys")),
        "include_knowledge_output_subdirs": _coerce_str_list(
            selectors.get("include_knowledge_output_subdirs")
        ),
    }


def _write_followup_readme(
    *,
    out_dir: Path,
    request_payload: dict[str, Any],
    ask_summaries: list[dict[str, Any]],
) -> None:
    lines = [
        "# Follow-Up Data Packet",
        "",
        "This folder is a follow-up packet for a requester that already has `upload_bundle_v1`.",
        "Use the request manifest and row locators here together with the original bundle.",
        "",
        f"- request_id: `{request_payload.get('request_id')}`",
        f"- ask_count: `{len(ask_summaries)}`",
        "",
        "## Ask Folders",
        "",
    ]
    for ask in ask_summaries:
        lines.append(
            f"- `{ask['ask_id']}`: {ask['question']} (`{', '.join(ask['requested_outputs'])}`)"
        )
    (out_dir / "README.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_followup_request_packet(
    *,
    bundle_dir: Path,
    request_path: Path,
    out_dir: Path,
    include_readme: bool = True,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    request_payload = _load_followup_request(request_path)
    manifest_bundle_sha = str(request_payload.get("bundle_sha256") or "").strip()
    if manifest_bundle_sha and manifest_bundle_sha != context.bundle_sha256:
        raise ValueError(
            "Follow-up request bundle_sha256 does not match the provided upload bundle."
        )

    default_stage_filters = _coerce_str_list(request_payload.get("default_stage_filters"))
    asks = [ask for ask in request_payload.get("asks", []) if isinstance(ask, dict)]
    if not asks:
        raise ValueError("Follow-up request must contain object asks.")

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "request_manifest.json", request_payload)

    ask_summaries: list[dict[str, Any]] = []
    for ask_index, ask in enumerate(asks, start=1):
        ask_id = str(ask.get("ask_id") or f"ask_{ask_index:03d}").strip() or f"ask_{ask_index:03d}"
        question = str(ask.get("question") or "").strip()
        if not question:
            raise ValueError(f"Ask {ask_id} is missing `question`.")
        requested_outputs = _normalize_requested_outputs(ask.get("outputs"))
        selector_config = _normalize_followup_selector_config(
            ask=ask,
            default_stage_filters=default_stage_filters,
        )
        selectors_payload = build_selector_manifest(
            context=context,
            command=f"cf-debug build-followup --request {request_path} --ask-id {ask_id}",
            stage_filters=selector_config["stage_filters"],
            top_neg=selector_config["top_neg"],
            top_pos=selector_config["top_pos"],
            outside_span=selector_config["outside_span"],
            include_case_ids=selector_config["include_case_ids"],
            include_recipe_ids=selector_config["include_recipe_ids"],
            include_line_ranges=selector_config["include_line_ranges"],
            include_knowledge_source_keys=selector_config["include_knowledge_source_keys"],
            include_knowledge_output_subdirs=selector_config["include_knowledge_output_subdirs"],
        )

        ask_dir = out_dir / "asks" / ask_id
        ask_dir.mkdir(parents=True, exist_ok=True)
        selectors_path = ask_dir / "selectors.json"
        _write_json(selectors_path, selectors_payload)

        files: dict[str, str] = {"selectors_json": "selectors.json"}
        if "structure_report" in requested_outputs:
            write_structure_report(
                bundle_dir=bundle_dir,
                out_path=ask_dir / "structure_report.json",
            )
            files["structure_report_json"] = "structure_report.json"
        if "case_export" in requested_outputs:
            write_case_export(bundle_dir=bundle_dir, selectors_path=selectors_path, out_dir=ask_dir / "case_export")
            files["case_export_dir"] = "case_export"
        if "line_role_audit" in requested_outputs:
            write_line_role_audit(
                bundle_dir=bundle_dir,
                selectors_path=selectors_path,
                out_path=ask_dir / "line_role_audit.jsonl",
            )
            files["line_role_audit_jsonl"] = "line_role_audit.jsonl"
        if "prompt_link_audit" in requested_outputs:
            write_prompt_link_audit(
                bundle_dir=bundle_dir,
                selectors_path=selectors_path,
                out_path=ask_dir / "prompt_link_audit.jsonl",
            )
            files["prompt_link_audit_jsonl"] = "prompt_link_audit.jsonl"
        if "knowledge_audit" in requested_outputs:
            write_knowledge_audit(
                bundle_dir=bundle_dir,
                selectors_path=selectors_path,
                out_path=ask_dir / "knowledge_audit.jsonl",
            )
            files["knowledge_audit_jsonl"] = "knowledge_audit.jsonl"
        if "page_context" in requested_outputs:
            write_page_context(
                bundle_dir=bundle_dir,
                selectors_path=selectors_path,
                out_path=ask_dir / "page_context.jsonl",
            )
            files["page_context_jsonl"] = "page_context.jsonl"
        if "uncertainty" in requested_outputs:
            write_uncertainty_export(
                bundle_dir=bundle_dir,
                selectors_path=selectors_path,
                out_path=ask_dir / "uncertainty.jsonl",
            )
            files["uncertainty_jsonl"] = "uncertainty.jsonl"

        ask_index_payload = {
            "schema_version": FOLLOWUP_PACKET_SCHEMA_VERSION,
            "ask_id": ask_id,
            "question": question,
            "requested_outputs": requested_outputs,
            "delta_contract": {
                "requester_already_has_upload_bundle_v1": True,
                "base_bundle_dir": str(context.bundle_dir),
                "base_bundle_sha256": context.bundle_sha256,
                "prefer_new_local_artifacts": True,
            },
            "selector_count": len(selectors_payload.get("selectors") or []),
            "files": files,
            "notes": str(ask.get("notes") or "").strip(),
        }
        _write_json(ask_dir / "index.json", ask_index_payload)
        ask_summaries.append(
            {
                "ask_id": ask_id,
                "question": question,
                "requested_outputs": requested_outputs,
                "selector_count": len(selectors_payload.get("selectors") or []),
                "files": files,
            }
        )

    packet_index = {
        "schema_version": FOLLOWUP_PACKET_SCHEMA_VERSION,
        "request_id": str(request_payload.get("request_id") or "").strip() or "followup_request",
        "request_summary": str(request_payload.get("request_summary") or "").strip(),
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "request_manifest_file": "request_manifest.json",
        "ask_count": len(ask_summaries),
        "requester_context": request_payload.get("requester_context"),
        "asks": ask_summaries,
    }
    _write_json(out_dir / "index.json", packet_index)
    if include_readme:
        _write_followup_readme(
            out_dir=out_dir,
            request_payload=request_payload,
            ask_summaries=ask_summaries,
        )
    return packet_index


def _file_manifest_row(repo_root: Path, path: Path, *, kind: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": _relative_path(repo_root, path),
        "source_path": str(path),
        "kind": kind,
        "bytes": len(data),
        "sha256": _sha256_bytes(data),
    }


def _context_window(
    extracted_lines_by_index: dict[int, dict[str, Any]],
    *,
    line_indices: list[int],
    radius: int = 2,
) -> dict[str, Any]:
    if not line_indices:
        return {"before": [], "focus": [], "after": []}
    start = min(line_indices)
    end = max(line_indices)
    before: list[dict[str, Any]] = []
    focus: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    for line_index in range(start - radius, end + radius + 1):
        row = extracted_lines_by_index.get(line_index)
        if row is None:
            continue
        payload = {
            "line_index": line_index,
            "text": str(row.get("text") or ""),
            "location": row.get("location"),
        }
        if line_index < start:
            before.append(payload)
        elif line_index > end:
            after.append(payload)
        else:
            focus.append(payload)
    return {"before": before, "focus": focus, "after": after}


def _referenced_file_rows(
    *,
    repo_root: Path,
    file_paths: dict[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifest_rows: list[dict[str, Any]] = []
    compact_rows: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for kind, raw_path in sorted(file_paths.items()):
        path = Path(raw_path)
        if not path.is_file():
            continue
        if path not in seen:
            manifest_rows.append(_file_manifest_row(repo_root, path, kind=kind))
            seen.add(path)
        compact_rows.append(
            {
                "kind": kind,
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
        )
    return manifest_rows, compact_rows


def _line_role_rows_for_selector(
    context: FollowupBundleContext,
    selector: dict[str, Any],
) -> list[dict[str, Any]]:
    kind = str(selector.get("kind") or "")
    source_key = str(selector.get("source_key") or "")
    if kind == "knowledge_run":
        return []
    if kind == "recipe":
        recipe_id = str(selector.get("recipe_id") or "")
        return context.changed_lines_for_recipe(source_key, recipe_id)
    start = int(selector.get("start") or 0)
    end = int(selector.get("end") or 0)
    return context.changed_lines_for_range(source_key, start, end)


def _classify_line_role_authority_gap(
    *,
    parsed_label: str | None,
    final_label: str | None,
    codex_pred: str | None,
    gold_label: str | None,
) -> tuple[str | None, str | None]:
    parsed = str(parsed_label or "").strip().upper()
    final = str(final_label or "").strip().upper()
    codex = str(codex_pred or "").strip().upper()
    gold = str(gold_label or "").strip().upper()
    if parsed and final and parsed != final:
        return (
            "post_route_label_change",
            "The parsed line-role label changed before the final line-role output was saved.",
        )
    if final == "NONRECIPE_EXCLUDE" and codex == "KNOWLEDGE":
        return (
            "exclusion_leak_into_final_knowledge",
            "Line-role excluded this row, but final authority still surfaced KNOWLEDGE.",
        )
    if final == "NONRECIPE_CANDIDATE" and codex == "KNOWLEDGE" and gold == "OTHER":
        return (
            "route_broadness_other_promoted_to_knowledge",
            "Line-role routed this row into knowledge review and final authority kept KNOWLEDGE against OTHER gold.",
        )
    return None, None


def _build_line_role_audit_rows(
    *,
    context: FollowupBundleContext,
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selector in selectors:
        source_key = str(selector.get("source_key") or "")
        codex_run = context.codex_run_for_source(source_key)
        if codex_run is None:
            continue
        selected_lines = _line_role_rows_for_selector(context, selector)
        for changed_row in selected_lines:
            line_index = int(changed_row.get("line_index") or 0)
            line_role_row = codex_run.line_role_predictions_by_index.get(line_index, {})
            prompt_link = codex_run.prompt_links_by_atomic_index.get(line_index)
            final_label = str(line_role_row.get("label") or "").strip() or None
            parsed_label = prompt_link.parsed_label if prompt_link is not None else None
            raw_model_label = parsed_label
            codex_pred = str(changed_row.get("codex_pred") or "").strip() or None
            baseline_pred = str(changed_row.get("vanilla_pred") or "").strip() or None
            gold_label = str(changed_row.get("gold_label") or "").strip() or None
            escalation_reasons = _coerce_str_list(
                line_role_row.get("escalation_reasons")
            )
            decided_by = str(line_role_row.get("decided_by") or "").strip().lower()
            violations: list[str] = []
            if decided_by == "codex" and parsed_label is None:
                violations.append("parsed_label_missing")
            if decided_by == "codex" and prompt_link is None:
                violations.append("prompt_artifact_missing")
            if parsed_label and final_label and parsed_label != final_label:
                violations.append("postprocess_changed_label")
            authority_gap_kind, authority_gap_note = _classify_line_role_authority_gap(
                parsed_label=parsed_label,
                final_label=final_label,
                codex_pred=codex_pred,
                gold_label=gold_label,
            )
            if authority_gap_kind == "exclusion_leak_into_final_knowledge":
                violations.append("excluded_row_became_final_knowledge")
            if baseline_pred is None:
                violations.append("baseline_join_missing")
            rows.append(
                {
                    "schema_version": LINE_ROLE_AUDIT_SCHEMA_VERSION,
                    "selector_id": str(selector.get("selector_id") or ""),
                    "case_id": str(selector.get("case_id") or ""),
                    "source_key": source_key,
                    "book": codex_run.source_file,
                    "recipe_id": changed_row.get("recipe_id"),
                    "line_index": line_index,
                    "raw_text": changed_row.get("current_line"),
                    "gold_label": gold_label,
                    "baseline_pred": baseline_pred,
                    "codex_pred": codex_pred,
                    "raw_model_label": raw_model_label,
                    "parsed_label": parsed_label,
                    "final_label_after_postprocess": final_label,
                    "authority_gap_kind": authority_gap_kind,
                    "authority_gap_note": authority_gap_note,
                    "escalation_reasons": escalation_reasons,
                    "decided_by": line_role_row.get("decided_by"),
                    "prompt_file": str(prompt_link.prompt_file) if prompt_link and prompt_link.prompt_file else None,
                    "response_file": str(prompt_link.response_file) if prompt_link and prompt_link.response_file else None,
                    "parsed_file": str(prompt_link.parsed_file) if prompt_link and prompt_link.parsed_file else None,
                    "payload_locator": changed_row.get("_payload_locator"),
                    "violations": sorted(set(violations)),
                }
            )
    rows.sort(key=lambda row: (str(row.get("selector_id") or ""), int(row.get("line_index") or 0)))
    return rows


def write_line_role_audit(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_path: Path,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_line_role_audit_rows(context=context, selectors=selectors)
    _write_jsonl(out_path, rows)
    return rows


def _build_prompt_link_audit_rows(
    *,
    context: FollowupBundleContext,
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    line_role_rows = _build_line_role_audit_rows(context=context, selectors=selectors)
    rows: list[dict[str, Any]] = []
    for row in line_role_rows:
        issues: list[str] = []
        prompt_file = Path(row["prompt_file"]) if row.get("prompt_file") else None
        response_file = Path(row["response_file"]) if row.get("response_file") else None
        parsed_file = Path(row["parsed_file"]) if row.get("parsed_file") else None
        line_index = int(row.get("line_index") or 0)
        decided_by = str(row.get("decided_by") or "").strip().lower()
        prompt_mentions_line = False
        response_mentions_line = False
        parsed_mentions_line = False
        if decided_by != "codex":
            rows.append(
                {
                    "schema_version": PROMPT_LINK_AUDIT_SCHEMA_VERSION,
                    "selector_id": row.get("selector_id"),
                    "case_id": row.get("case_id"),
                    "source_key": row.get("source_key"),
                    "recipe_id": row.get("recipe_id"),
                    "line_index": line_index,
                    "prompt_file": row.get("prompt_file"),
                    "response_file": row.get("response_file"),
                    "parsed_file": row.get("parsed_file"),
                    "prompt_mentions_atomic_index": False,
                    "response_mentions_atomic_index": False,
                    "parsed_mentions_atomic_index": False,
                    "status": "not_applicable",
                    "issues": [],
                }
            )
            continue
        if prompt_file and prompt_file.is_file():
            prompt_text = prompt_file.read_text(encoding="utf-8")
            prompt_mentions_line = f"\"atomic_index\": {line_index}" in prompt_text or f"\"atomic_index\":{line_index}" in prompt_text
            if not prompt_mentions_line:
                issues.append("prompt_missing_atomic_index")
        else:
            issues.append("prompt_file_missing")
        if response_file and response_file.is_file():
            response_text = response_file.read_text(encoding="utf-8")
            response_mentions_line = f"\"atomic_index\": {line_index}" in response_text or f"\"atomic_index\":{line_index}" in response_text
            if not response_mentions_line:
                issues.append("response_missing_atomic_index")
        else:
            issues.append("response_file_missing")
        if parsed_file and parsed_file.is_file():
            payload = _read_json(parsed_file)
            if isinstance(payload, list):
                parsed_mentions_line = any(
                    _coerce_int(item.get("atomic_index")) == line_index
                    for item in payload
                    if isinstance(item, dict)
                )
            if not parsed_mentions_line:
                issues.append("parsed_file_missing_atomic_index")
        else:
            issues.append("parsed_file_missing")
        rows.append(
            {
                "schema_version": PROMPT_LINK_AUDIT_SCHEMA_VERSION,
                "selector_id": row.get("selector_id"),
                "case_id": row.get("case_id"),
                "source_key": row.get("source_key"),
                "recipe_id": row.get("recipe_id"),
                "line_index": line_index,
                "prompt_file": row.get("prompt_file"),
                "response_file": row.get("response_file"),
                "parsed_file": row.get("parsed_file"),
                "prompt_mentions_atomic_index": prompt_mentions_line,
                "response_mentions_atomic_index": response_mentions_line,
                "parsed_mentions_atomic_index": parsed_mentions_line,
                "status": "ok" if not issues else "broken",
                "issues": sorted(set(issues)),
            }
        )
    rows.sort(key=lambda row: (str(row.get("selector_id") or ""), int(row.get("line_index") or 0)))
    return rows


def write_prompt_link_audit(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_path: Path,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_prompt_link_audit_rows(context=context, selectors=selectors)
    _write_jsonl(out_path, rows)
    return rows


def _knowledge_audit_row(
    *,
    context: FollowupBundleContext,
    selector: dict[str, Any],
) -> dict[str, Any] | None:
    output_subdir = str(selector.get("output_subdir") or "").strip()
    run = context.run_for_output_subdir(output_subdir)
    if run is None:
        return None
    summary = dict(context.knowledge_row_for_output_subdir(output_subdir) or {})
    local_files: dict[str, dict[str, Any]] = {}
    payload_locators = context.knowledge_locators_for_run(run)
    issues: list[str] = []
    status = "not_applicable"
    enabled = bool(summary.get("enabled"))
    if enabled:
        status = "ok"
    for kind, raw_path in sorted(run.knowledge_artifact_paths().items()):
        path = Path(raw_path)
        if not path.is_file():
            continue
        local_files[kind] = _file_manifest_row(context.repo_root, path, kind=kind)
    expected_status_by_kind = {
        "prompt_samples_md": str(summary.get("prompt_samples_status") or "").strip().lower(),
        "prompt_knowledge_txt": str(summary.get("prompt_knowledge_status") or "").strip().lower(),
        "prompt_budget_summary_json": str(summary.get("prompt_budget_summary_status") or "").strip().lower(),
        "knowledge_manifest_json": str(summary.get("knowledge_manifest_status") or "").strip().lower(),
    }
    for kind, expected_status in expected_status_by_kind.items():
        if (
            expected_status == "written"
            and kind not in local_files
            and kind not in payload_locators
        ):
            issues.append(f"{kind}_missing_locally")
    if enabled and not payload_locators:
        issues.append("no_knowledge_bundle_locators")
    if enabled and issues:
        status = "incomplete"
    return {
        "schema_version": KNOWLEDGE_AUDIT_SCHEMA_VERSION,
        "selector_id": str(selector.get("selector_id") or ""),
        "case_id": str(selector.get("case_id") or ""),
        "kind": "knowledge_run",
        "source_key": run.source_key,
        "book_slug": _source_key_from_output_subdir(run.output_subdir),
        "book": run.source_file,
        "output_subdir": run.output_subdir,
        "run_id": run.run_id,
        "enabled": enabled,
        "pipeline": summary.get("pipeline"),
        "pipeline_id": summary.get("pipeline_id"),
        "llm_knowledge_pipeline": summary.get("llm_knowledge_pipeline"),
        "shards_written": summary.get("shards_written"),
        "outputs_parsed": summary.get("outputs_parsed"),
        "snippets_written": summary.get("snippets_written"),
        "knowledge_call_count": summary.get("knowledge_call_count"),
        "knowledge_token_total": summary.get("knowledge_token_total"),
        "prompt_samples_status": summary.get("prompt_samples_status"),
        "prompt_knowledge_status": summary.get("prompt_knowledge_status"),
        "prompt_budget_summary_status": summary.get("prompt_budget_summary_status"),
        "knowledge_manifest_status": summary.get("knowledge_manifest_status"),
        "payload_locators": payload_locators,
        "local_artifacts": local_files,
        "issues": sorted(set(issues)),
        "status": status,
    }


def _build_knowledge_audit_rows(
    *,
    context: FollowupBundleContext,
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selector in selectors:
        if str(selector.get("kind") or "") != "knowledge_run":
            continue
        row = _knowledge_audit_row(context=context, selector=selector)
        if row is not None:
            rows.append(row)
    rows.sort(key=lambda row: (str(row.get("selector_id") or ""), str(row.get("output_subdir") or "")))
    return rows


def write_knowledge_audit(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_path: Path,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_knowledge_audit_rows(context=context, selectors=selectors)
    _write_jsonl(out_path, rows)
    return rows


def _build_page_context_rows(
    *,
    context: FollowupBundleContext,
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for selector in selectors:
        source_key = str(selector.get("source_key") or "")
        codex_run = context.codex_run_for_source(source_key) or context.baseline_run_for_source(source_key)
        if codex_run is None:
            continue
        selected_lines = _line_role_rows_for_selector(context, selector)
        for changed_row in selected_lines:
            line_index = int(changed_row.get("line_index") or 0)
            window = _context_window(
                codex_run.extracted_lines_by_index,
                line_indices=[line_index],
                radius=2,
            )
            extracted_row = codex_run.extracted_lines_by_index.get(line_index, {})
            rows.append(
                {
                    "schema_version": PAGE_CONTEXT_SCHEMA_VERSION,
                    "selector_id": str(selector.get("selector_id") or ""),
                    "case_id": str(selector.get("case_id") or ""),
                    "source_key": source_key,
                    "recipe_id": changed_row.get("recipe_id"),
                    "line_index": line_index,
                    "line_text": changed_row.get("current_line"),
                    "location": extracted_row.get("location"),
                    "context_before": window.get("before"),
                    "focus_rows": window.get("focus"),
                    "context_after": window.get("after"),
                    "payload_locator": changed_row.get("_payload_locator"),
                }
            )
    rows.sort(key=lambda row: (str(row.get("selector_id") or ""), int(row.get("line_index") or 0)))
    return rows


def write_page_context(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_path: Path,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_page_context_rows(context=context, selectors=selectors)
    _write_jsonl(out_path, rows)
    return rows


def _build_uncertainty_rows(
    *,
    context: FollowupBundleContext,
    selectors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    line_role_rows = _build_line_role_audit_rows(context=context, selectors=selectors)
    rows: list[dict[str, Any]] = []
    for row in line_role_rows:
        escalation_reasons = _coerce_str_list(row.get("escalation_reasons"))
        reasons: list[str] = []
        if escalation_reasons:
            reasons.append("explicit_escalation_reasons")
        if row.get("violations"):
            reasons.append("audit_violations")
        if not reasons:
            continue
        rows.append(
            {
                "schema_version": UNCERTAINTY_SCHEMA_VERSION,
                "selector_id": row.get("selector_id"),
                "case_id": row.get("case_id"),
                "source_key": row.get("source_key"),
                "recipe_id": row.get("recipe_id"),
                "line_index": row.get("line_index"),
                "raw_text": row.get("raw_text"),
                "decided_by": row.get("decided_by"),
                "reasons": sorted(set(reasons)),
                "escalation_reasons": escalation_reasons,
                "violations": row.get("violations"),
            }
        )
    rows.sort(key=lambda row: (str(row.get("selector_id") or ""), int(row.get("line_index") or 0)))
    return rows


def write_uncertainty_export(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_path: Path,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_uncertainty_rows(
        context=context,
        selectors=selectors,
    )
    _write_jsonl(out_path, rows)
    return rows


def write_case_export(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    case_rows: list[dict[str, Any]] = []
    file_manifest_rows: list[dict[str, Any]] = []
    seen_manifest_keys: set[tuple[str, str]] = set()

    for selector in selectors:
        source_key = str(selector.get("source_key") or "")
        codex_run = context.codex_run_for_source(source_key)
        baseline_run = context.baseline_run_for_source(source_key)
        selector_kind = str(selector.get("kind") or "")
        if selector_kind == "knowledge_run":
            output_subdir = str(selector.get("output_subdir") or "").strip()
            codex_run = context.run_for_output_subdir(output_subdir)
        selected_rows = _line_role_rows_for_selector(context, selector)
        line_indices = [int(row.get("line_index") or 0) for row in selected_rows]
        recipe_id = str(selector.get("recipe_id") or "")
        per_recipe_row = context.per_recipe_row(source_key, recipe_id) if recipe_id else None
        triage_row = context.triage_row(source_key, recipe_id) if recipe_id else None
        stage_row = context.stage_row(source_key, recipe_id) if recipe_id else None
        recipe_artifacts = codex_run.recipe_artifact_paths(recipe_id) if codex_run and recipe_id else {}
        knowledge_row = (
            context.knowledge_row_for_output_subdir(str(selector.get("output_subdir") or ""))
            if selector_kind == "knowledge_run"
            else None
        )
        knowledge_artifacts = codex_run.knowledge_artifact_paths() if codex_run and selector_kind == "knowledge_run" else {}
        manifest_rows, compact_file_rows = _referenced_file_rows(
            repo_root=context.repo_root,
            file_paths=recipe_artifacts if selector_kind != "knowledge_run" else knowledge_artifacts,
        )
        for row in manifest_rows:
            key = (str(row.get("path") or ""), str(row.get("kind") or ""))
            if key in seen_manifest_keys:
                continue
            seen_manifest_keys.add(key)
            file_manifest_rows.append(row)
        if codex_run is not None:
            for kind, path in (
                ("codex_run_manifest", codex_run.run_dir / "run_manifest.json"),
                ("codex_eval_report", codex_run.run_dir / "eval_report.json"),
            ):
                if path.is_file():
                    row = _file_manifest_row(context.repo_root, path, kind=kind)
                    key = (str(row.get("path") or ""), str(row.get("kind") or ""))
                    if key not in seen_manifest_keys:
                        seen_manifest_keys.add(key)
                        file_manifest_rows.append(row)
            line_role_prompt_dir = codex_run.run_dir / "line-role-pipeline" / "prompts"
            if line_role_prompt_dir.is_dir():
                for path in sorted(line_role_prompt_dir.glob("parsed_*.json")):
                    row = _file_manifest_row(context.repo_root, path, kind="line_role_parsed_prompt")
                    key = (str(row.get("path") or ""), str(row.get("kind") or ""))
                    if key not in seen_manifest_keys:
                        seen_manifest_keys.add(key)
                        file_manifest_rows.append(row)
        if baseline_run is not None:
            path = baseline_run.run_dir / "run_manifest.json"
            if path.is_file():
                row = _file_manifest_row(context.repo_root, path, kind="baseline_run_manifest")
                key = (str(row.get("path") or ""), str(row.get("kind") or ""))
                if key not in seen_manifest_keys:
                    seen_manifest_keys.add(key)
                    file_manifest_rows.append(row)

        window = _context_window(
            codex_run.extracted_lines_by_index if codex_run else {},
            line_indices=line_indices,
            radius=2,
        )

        case_rows.append(
            {
                "schema_version": CASE_EXPORT_ROW_SCHEMA_VERSION,
                "selector_id": str(selector.get("selector_id") or ""),
                "case_id": str(selector.get("case_id") or ""),
                "kind": str(selector.get("kind") or ""),
                "source_key": source_key,
                "book_slug": str(selector.get("book_slug") or ""),
                "book": codex_run.source_file if codex_run else None,
                "recipe_id": recipe_id or None,
                "metrics": {
                    "line_total": per_recipe_row.get("line_total") if per_recipe_row else len(selected_rows),
                    "codex_accuracy": per_recipe_row.get("codex_accuracy") if per_recipe_row else None,
                    "baseline_accuracy": per_recipe_row.get("baseline_accuracy") if per_recipe_row else None,
                    "delta_codex_minus_baseline": (
                        per_recipe_row.get("delta_codex_minus_baseline") if per_recipe_row else None
                    ),
                    "changed_lines_codex_vs_vanilla": (
                        per_recipe_row.get("changed_lines_codex_vs_vanilla")
                        if per_recipe_row
                        else len(selected_rows)
                    ),
                },
                "triage": triage_row,
                "stage_comparison": stage_row,
                "line_level_changed_rows": selected_rows,
                "raw_block_window": (
                    (
                        _read_json(Path(recipe_artifacts["recipe_correction_audit"])).get("input")
                        or {}
                    ).get("payload", {})
                ).get("evidence_rows", [])
                if (
                    selector_kind != "knowledge_run"
                    and "recipe_correction_audit" in recipe_artifacts
                )
                else [],
                "pass_summaries": {
                    key: _read_json(Path(path)) if Path(path).is_file() else None
                    for key, path in sorted(recipe_artifacts.items())
                }
                if selector_kind != "knowledge_run"
                else {},
                "knowledge_summary": knowledge_row,
                "knowledge_artifacts": compact_file_rows if selector_kind == "knowledge_run" else [],
                "context_window": window,
                "referenced_files": compact_file_rows,
                "row_locators": list(selector.get("payload_locators") or [])
                + [row.get("_payload_locator") for row in selected_rows if row.get("_payload_locator")],
            }
        )

    case_rows.sort(key=lambda row: str(row.get("selector_id") or ""))
    file_manifest_rows.sort(key=lambda row: (str(row.get("kind") or ""), str(row.get("path") or "")))

    index_payload = {
        "schema_version": CASE_EXPORT_INDEX_SCHEMA_VERSION,
        "generated_at": context.generated_at,
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "selector_count": len(selectors),
        "case_count": len(case_rows),
        "selectors_file": str(selectors_path),
        "files": {
            "case_export_jsonl": "case_export.jsonl",
            "file_manifest_jsonl": "file_manifest.jsonl",
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "index.json", index_payload)
    _write_jsonl(out_dir / "case_export.jsonl", case_rows)
    _write_jsonl(out_dir / "file_manifest.jsonl", file_manifest_rows)
    return index_payload


def write_followup_pack(
    *,
    bundle_dir: Path,
    selectors_path: Path,
    out_dir: Path,
    include_readme: bool = True,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    case_export_dir = out_dir / "case_export"
    write_structure_report(
        bundle_dir=bundle_dir,
        out_path=out_dir / "structure_report.json",
    )
    write_case_export(bundle_dir=bundle_dir, selectors_path=selectors_path, out_dir=case_export_dir)
    line_role_rows = write_line_role_audit(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "line_role_audit.jsonl",
    )
    prompt_rows = write_prompt_link_audit(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "prompt_link_audit.jsonl",
    )
    knowledge_rows = write_knowledge_audit(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "knowledge_audit.jsonl",
    )
    page_rows = write_page_context(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "page_context.jsonl",
    )
    uncertainty_rows = write_uncertainty_export(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "uncertainty.jsonl",
    )
    selectors_payload = _read_json(selectors_path)
    _write_json(out_dir / "selectors.json", selectors_payload)

    manifest = {
        "schema_version": PACK_SCHEMA_VERSION,
        "generated_at": context.generated_at,
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "git_sha": context.git_sha,
        "selector_count": len(selectors),
        "line_role_audit_rows": len(line_role_rows),
        "prompt_link_audit_rows": len(prompt_rows),
        "knowledge_audit_rows": len(knowledge_rows),
        "page_context_rows": len(page_rows),
        "uncertainty_rows": len(uncertainty_rows),
        "files": {
            "selectors_json": "selectors.json",
            "structure_report_json": "structure_report.json",
            "case_export_dir": "case_export",
            "line_role_audit_jsonl": "line_role_audit.jsonl",
            "prompt_link_audit_jsonl": "prompt_link_audit.jsonl",
            "knowledge_audit_jsonl": "knowledge_audit.jsonl",
            "page_context_jsonl": "page_context.jsonl",
            "uncertainty_jsonl": "uncertainty.jsonl",
        },
    }
    _write_json(out_dir / "index.json", manifest)
    if include_readme:
        readme_lines = [
            "# Deterministic Follow-Up Pack",
            "",
            f"- bundle: `{context.bundle_dir}`",
            f"- bundle_sha256: `{context.bundle_sha256}`",
            f"- selector_count: `{len(selectors)}`",
            "- structure_report_json: `structure_report.json`",
            f"- line_role_audit_rows: `{len(line_role_rows)}`",
            f"- prompt_link_audit_rows: `{len(prompt_rows)}`",
            f"- knowledge_audit_rows: `{len(knowledge_rows)}`",
            f"- uncertainty_rows: `{len(uncertainty_rows)}`",
            "",
            "Files are JSON/JSONL-first so the pack can be regenerated without hand-written prose.",
        ]
        (out_dir / "README.md").write_text("\n".join(readme_lines).rstrip() + "\n", encoding="utf-8")
    return manifest


def write_ablation_matrix(
    *,
    bundle_dir: Path,
    out_path: Path,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    sources = sorted(
        {
            run.source_key: {
                "source_key": run.source_key,
                "source_file": run.source_file,
                "run_dir": str(run.run_dir),
            }
            for run in context.runs
        }.values(),
        key=lambda row: str(row["source_key"]),
    )
    matrix = [
        {
            "variant_id": "baseline_control",
            "atomic_block_splitter": "off",
            "line_role_pipeline": "off",
            "llm_recipe_pipeline": "off",
        },
        {
            "variant_id": "line_role_only",
            "atomic_block_splitter": "atomic-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_recipe_pipeline": "off",
        },
        {
            "variant_id": "recipe_only",
            "atomic_block_splitter": "off",
            "line_role_pipeline": "off",
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
        },
        {
            "variant_id": "full_stack",
            "atomic_block_splitter": "atomic-v1",
            "line_role_pipeline": "codex-line-role-route-v2",
            "llm_recipe_pipeline": "codex-recipe-shard-v1",
        },
    ]
    payload = {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "generated_at": context.generated_at,
        "bundle_dir": str(context.bundle_dir),
        "bundle_sha256": context.bundle_sha256,
        "sources": sources,
        "matrix": matrix,
    }
    _write_json(out_path, payload)
    return payload
