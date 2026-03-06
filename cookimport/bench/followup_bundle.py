from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHANGED_LINES_PAYLOAD_PATH = "_upload_bundle_derived/root/changed_lines.codex_vs_vanilla.jsonl"
TRIAGE_PACKET_PAYLOAD_PATH = "_upload_bundle_derived/root/01_recipe_triage.packet.jsonl"
PER_RECIPE_BREAKDOWN_PAYLOAD_PATH = "_upload_bundle_derived/root/per_recipe_or_per_span_breakdown.json"

SELECTOR_SCHEMA_VERSION = "cf.selector.v1"
CASE_EXPORT_INDEX_SCHEMA_VERSION = "cf.case_export_index.v1"
CASE_EXPORT_ROW_SCHEMA_VERSION = "cf.case_export.v1"
LINE_ROLE_AUDIT_SCHEMA_VERSION = "cf.line_role_audit.v1"
PROMPT_LINK_AUDIT_SCHEMA_VERSION = "cf.prompt_link_audit.v1"
PAGE_CONTEXT_SCHEMA_VERSION = "cf.page_context.v1"
UNCERTAINTY_SCHEMA_VERSION = "cf.uncertainty.v1"
PACK_SCHEMA_VERSION = "cf.followup_pack.v1"
ABLATION_SCHEMA_VERSION = "cf.ablation_matrix.v1"

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
    for file_name in ("upload_bundle_index.json", "upload_bundle_payload.jsonl"):
        path = bundle_dir / file_name
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


def _load_legacy_followup_cases(bundle_dir: Path) -> dict[str, dict[str, Any]]:
    followup_path = bundle_dir.parent / "followup_data" / "codexfarm_root_cause_packet.json"
    if not followup_path.is_file():
        return {}
    payload = _read_json(followup_path)
    if not isinstance(payload, list):
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id") or "").strip()
        if not case_id:
            continue
        rows[case_id] = item
    return rows


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
                self.run_dir / "prediction-run" / "line-role-pipeline" / "extracted_archive.json",
                self.run_dir / "prediction-run" / "extracted_archive.json",
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
            prompt_dir = self.run_dir / "prediction-run" / "line-role-pipeline" / "prompts"
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
            candidate_root = self.run_dir / "prediction-run" / "raw" / "llm"
            resolved: Path | None = None
            if candidate_root.is_dir():
                for child in sorted(candidate_root.iterdir()):
                    if child.is_dir():
                        resolved = child
                        break
            self._raw_llm_dir = resolved
        return self._raw_llm_dir

    def recipe_artifact_paths(self, recipe_id: str) -> dict[str, str]:
        suffix = _recipe_suffix(recipe_id)
        if not suffix or self.raw_llm_dir is None:
            return {}
        source_key = self.source_key
        pattern = f"*_{source_key}_{suffix}.json"
        resolved: dict[str, str] = {}
        for label, relative in (
            ("pass1_input", Path("pass1_chunking/in")),
            ("pass1_output", Path("pass1_chunking/out")),
            ("pass2_input", Path("pass2_schemaorg/in")),
            ("pass2_output", Path("pass2_schemaorg/out")),
            ("pass3_output", Path("pass3_final/out")),
            ("evidence_normalization", Path("evidence_normalization")),
            ("transport_audit", Path("transport_audit")),
        ):
            directory = self.raw_llm_dir / relative
            if not directory.is_dir():
                continue
            matches = sorted(path for path in directory.glob(pattern) if path.is_file())
            if matches:
                resolved[label] = str(matches[0])
        return resolved


class FollowupBundleContext:
    def __init__(self, *, repo_root: Path, bundle_dir: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.bundle_dir = bundle_dir.resolve()
        self.index = _read_json(self.bundle_dir / "upload_bundle_index.json")
        self.source_root = Path(
            str(self.index.get("source_dir") or self.bundle_dir.parent)
        ).resolve()
        self.payload_artifacts: list[PayloadArtifact] = []
        self.payload_by_path: dict[str, PayloadArtifact] = {}
        payload_path = self.bundle_dir / "upload_bundle_payload.jsonl"
        for payload_row, raw_line in enumerate(
            payload_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            text = raw_line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if not isinstance(payload, dict):
                continue
            path = str(payload.get("path") or "").strip()
            if not path:
                continue
            artifact = PayloadArtifact(path=path, payload_row=payload_row, row=payload)
            self.payload_artifacts.append(artifact)
            self.payload_by_path[path] = artifact
        self.legacy_followup_cases = _load_legacy_followup_cases(self.bundle_dir)
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

    def legacy_case(self, case_id: str) -> dict[str, Any] | None:
        return self.legacy_followup_cases.get(case_id)

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


def load_followup_bundle_context(bundle_dir: Path) -> FollowupBundleContext:
    repo_root = bundle_dir.resolve()
    while repo_root != repo_root.parent:
        if (repo_root / "pyproject.toml").is_file():
            break
        repo_root = repo_root.parent
    return FollowupBundleContext(repo_root=repo_root, bundle_dir=bundle_dir)


def _build_outside_span_candidates(
    context: FollowupBundleContext,
) -> dict[str, dict[str, Any]]:
    legacy_rows: dict[str, dict[str, Any]] = {}
    for case_id, row in context.legacy_followup_cases.items():
        match = OUTSIDE_SPAN_CASE_ID_RE.match(case_id)
        if not match:
            continue
        source_key = str(row.get("source_key") or "").strip()
        start = _coerce_int(match.group("start"))
        end = _coerce_int(match.group("end"))
        if not source_key or start is None or end is None:
            continue
        selected_rows = context.changed_lines_for_range(source_key, start, end)
        legacy_rows[case_id] = {
            "case_id": case_id,
            "source_key": source_key,
            "start": start,
            "end": end,
            "changed_line_count": len(selected_rows),
            "payload_locators": [row["_payload_locator"] for row in selected_rows],
            "reason": "legacy_followup_outside_span_case",
        }
    if legacy_rows:
        return legacy_rows

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
) -> dict[str, Any]:
    stages = [stage.strip().lower() for stage in stage_filters or [] if stage.strip()]
    unsupported = [stage for stage in stages if stage not in {"line_role"}]
    if unsupported:
        raise ValueError(
            f"Unsupported stage filter(s): {', '.join(sorted(set(unsupported)))}"
        )

    selectors: dict[str, dict[str, Any]] = {}

    recipe_rows = list(context._per_recipe_rows.values())
    negatives = sorted(
        (row for row in recipe_rows if _coerce_float(row.get("delta_codex_minus_baseline")) is not None),
        key=lambda row: (
            _coerce_float(row.get("delta_codex_minus_baseline")) or 0.0,
            str(row.get("recipe_id") or ""),
        ),
    )
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

    for rank, row in enumerate(negatives[: max(0, top_neg)], start=1):
        add_recipe_selector(row, reason="top_negative_delta", reason_rank=rank)

    for rank, row in enumerate(positives[: max(0, top_pos)], start=1):
        add_recipe_selector(row, reason="top_positive_delta", reason_rank=rank)

    outside_candidates = _build_outside_span_candidates(context)
    selected_outside = sorted(
        outside_candidates.values(),
        key=lambda row: (
            -(int(row.get("changed_line_count") or 0)),
            str(row.get("source_key") or ""),
            int(row.get("start") or 0),
            int(row.get("end") or 0),
        ),
    )
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
        parts = text.split(":")
        if len(parts) < 3:
            raise ValueError(f"Invalid --include-line-range value: {text}")
        source_key = ":".join(parts[:-2]).strip()
        start = _coerce_int(parts[-2])
        end = _coerce_int(parts[-1])
        if not source_key or start is None or end is None:
            raise ValueError(f"Invalid --include-line-range value: {text}")
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
        legacy_row = context.legacy_case(case_text)
        if legacy_row is not None:
            source_key = str(legacy_row.get("source_key") or "").strip()
            recipe_id = str(legacy_row.get("recipe_id") or "").strip()
            if recipe_id:
                per_recipe_row = context.per_recipe_row(source_key, recipe_id)
                if per_recipe_row is not None:
                    add_recipe_selector(per_recipe_row, reason="explicit_legacy_case_id", reason_rank=0)
                    matched = True
            else:
                match = OUTSIDE_SPAN_CASE_ID_RE.match(case_text)
                if match and source_key:
                    start = int(match.group("start"))
                    end = int(match.group("end"))
                    selected_rows = context.changed_lines_for_range(source_key, start, end)
                    selector = {
                        "selector_id": _selector_id_for_line_range(source_key, start, end),
                        "case_id": case_text,
                        "kind": "line_range",
                        "source_key": source_key,
                        "start": start,
                        "end": end,
                        "reason": "explicit_legacy_case_id",
                        "reason_rank": 0,
                        "payload_locators": [row["_payload_locator"] for row in selected_rows],
                    }
                    selectors[selector["selector_id"]] = selector
                    matched = True
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
    )
    _write_json(out_path, manifest)
    return manifest


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
    if kind == "recipe":
        recipe_id = str(selector.get("recipe_id") or "")
        return context.changed_lines_for_recipe(source_key, recipe_id)
    start = int(selector.get("start") or 0)
    end = int(selector.get("end") or 0)
    return context.changed_lines_for_range(source_key, start, end)


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
            candidate_labels = _coerce_str_list(line_role_row.get("candidate_labels"))
            final_label = str(line_role_row.get("label") or "").strip() or None
            parsed_label = prompt_link.parsed_label if prompt_link is not None else None
            raw_model_label = parsed_label
            codex_pred = str(changed_row.get("codex_pred") or "").strip() or None
            baseline_pred = str(changed_row.get("vanilla_pred") or "").strip() or None
            gold_label = str(changed_row.get("gold_label") or "").strip() or None
            confidence = _coerce_float(line_role_row.get("confidence"))
            decided_by = str(line_role_row.get("decided_by") or "").strip().lower()
            violations: list[str] = []
            if not candidate_labels:
                violations.append("candidate_labels_missing")
            if final_label and candidate_labels and final_label not in candidate_labels:
                violations.append("pred_not_in_candidate_labels")
            if raw_model_label and candidate_labels and raw_model_label not in candidate_labels:
                violations.append("raw_not_in_candidate_labels")
            if decided_by == "codex" and parsed_label is None:
                violations.append("parsed_label_missing")
            elif candidate_labels and parsed_label not in candidate_labels:
                violations.append("parsed_not_in_candidate_labels")
            if decided_by == "codex" and prompt_link is None:
                violations.append("prompt_artifact_missing")
            if parsed_label and final_label and parsed_label != final_label:
                violations.append("postprocess_changed_label")
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
                    "candidate_labels": candidate_labels,
                    "raw_model_label": raw_model_label,
                    "parsed_label": parsed_label,
                    "final_label_after_postprocess": final_label,
                    "confidence": confidence,
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
    confidence_threshold: float,
) -> list[dict[str, Any]]:
    line_role_rows = _build_line_role_audit_rows(context=context, selectors=selectors)
    rows: list[dict[str, Any]] = []
    for row in line_role_rows:
        candidate_labels = _coerce_str_list(row.get("candidate_labels"))
        confidence = _coerce_float(row.get("confidence"))
        reasons: list[str] = []
        if confidence is not None and confidence < confidence_threshold:
            reasons.append("low_confidence")
        if len(candidate_labels) > 1:
            reasons.append("multiple_candidate_labels")
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
                "confidence": confidence,
                "candidate_labels": candidate_labels,
                "candidate_label_count": len(candidate_labels),
                "decided_by": row.get("decided_by"),
                "reasons": sorted(set(reasons)),
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
    confidence_threshold: float = 0.9,
) -> list[dict[str, Any]]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    rows = _build_uncertainty_rows(
        context=context,
        selectors=selectors,
        confidence_threshold=confidence_threshold,
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
        selected_rows = _line_role_rows_for_selector(context, selector)
        line_indices = [int(row.get("line_index") or 0) for row in selected_rows]
        recipe_id = str(selector.get("recipe_id") or "")
        per_recipe_row = context.per_recipe_row(source_key, recipe_id) if recipe_id else None
        triage_row = context.triage_row(source_key, recipe_id) if recipe_id else None
        stage_row = context.stage_row(source_key, recipe_id) if recipe_id else None
        recipe_artifacts = codex_run.recipe_artifact_paths(recipe_id) if codex_run and recipe_id else {}
        manifest_rows, compact_file_rows = _referenced_file_rows(
            repo_root=context.repo_root,
            file_paths=recipe_artifacts,
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
            line_role_prompt_dir = codex_run.run_dir / "prediction-run" / "line-role-pipeline" / "prompts"
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
                "raw_block_window": _read_json(Path(recipe_artifacts["pass1_input"])).get("blocks_candidate")
                if "pass1_input" in recipe_artifacts
                else [],
                "pass_summaries": {
                    key: _read_json(Path(path)) if Path(path).is_file() else None
                    for key, path in sorted(recipe_artifacts.items())
                },
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
    confidence_threshold: float = 0.9,
) -> dict[str, Any]:
    context = load_followup_bundle_context(bundle_dir)
    selectors = _load_selectors(selectors_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    case_export_dir = out_dir / "case_export"
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
    page_rows = write_page_context(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "page_context.jsonl",
    )
    uncertainty_rows = write_uncertainty_export(
        bundle_dir=bundle_dir,
        selectors_path=selectors_path,
        out_path=out_dir / "uncertainty.jsonl",
        confidence_threshold=confidence_threshold,
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
        "page_context_rows": len(page_rows),
        "uncertainty_rows": len(uncertainty_rows),
        "files": {
            "selectors_json": "selectors.json",
            "case_export_dir": "case_export",
            "line_role_audit_jsonl": "line_role_audit.jsonl",
            "prompt_link_audit_jsonl": "prompt_link_audit.jsonl",
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
            f"- line_role_audit_rows: `{len(line_role_rows)}`",
            f"- prompt_link_audit_rows: `{len(prompt_rows)}`",
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
            "line_role_pipeline": "codex-line-role-v1",
            "llm_recipe_pipeline": "off",
        },
        {
            "variant_id": "recipe_only",
            "atomic_block_splitter": "off",
            "line_role_pipeline": "off",
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
        },
        {
            "variant_id": "full_stack",
            "atomic_block_splitter": "atomic-v1",
            "line_role_pipeline": "codex-line-role-v1",
            "llm_recipe_pipeline": "codex-farm-3pass-v1",
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
