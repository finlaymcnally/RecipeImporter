from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any, Protocol

from cookimport.labelstudio.freeform_tasks import map_span_offsets_to_blocks
from cookimport.labelstudio.label_config_freeform import (
    FREEFORM_ALLOWED_LABELS,
    FREEFORM_LABELS,
    FREEFORM_LABEL_CONTROL_NAME,
    FREEFORM_LABEL_RESULT_TYPE,
    FREEFORM_TEXT_NAME,
    normalize_freeform_label,
)


class LlmProvider(Protocol):
    """Small interface for LLM completion providers."""

    def complete(self, prompt: str) -> str:
        """Return raw model output."""


class CodexCliProvider:
    """Run a local Codex-style CLI command and cache prompt/response pairs."""

    def __init__(
        self,
        *,
        cmd: str,
        timeout_s: int,
        cache_dir: Path | None = None,
        track_usage: bool = False,
        model: str | None = None,
    ) -> None:
        normalized_cmd = cmd.strip()
        if not normalized_cmd:
            raise ValueError("codex command cannot be empty")
        self.cmd = normalized_cmd
        self.timeout_s = max(1, int(timeout_s))
        self.track_usage = bool(track_usage)
        self.model = resolve_codex_model(model)
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "cookimport" / "prelabel"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._calls_total = 0
        self._usage_totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "calls_with_usage": 0,
        }

    def complete(self, prompt: str) -> str:
        self._calls_total += 1
        cache_key = hashlib.sha256(
            f"{self.cmd}\ntrack_usage={self.track_usage}\n{prompt}".encode("utf-8")
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

        argv = shlex.split(self.cmd)
        if not argv:
            raise RuntimeError(f"Unable to parse codex command: {self.cmd!r}")

        run_argv = self._argv_with_json_events(argv)
        completed = self._run(run_argv, prompt)
        if (
            completed.returncode != 0
            and self._is_stdin_tty_error(completed)
            and self._is_plain_codex_command(argv)
        ):
            completed = self._run(
                self._argv_with_json_events([argv[0], "exec", "-"]),
                prompt,
            )

        response, usage = self._response_and_usage(completed)
        if completed.returncode != 0:
            allow_nonzero_with_response = self.track_usage and bool(response)
            if not allow_nonzero_with_response:
                stderr = (completed.stderr or "").strip()
                stdout = (completed.stdout or "").strip()
                detail = stderr or stdout or "unknown error"
                raise RuntimeError(
                    f"Codex command failed (exit={completed.returncode}): {detail}"
                )

        if not response:
            raise RuntimeError("Codex command returned empty stdout")

        self._record_usage(usage)
        try:
            cache_path.write_text(
                json.dumps(
                    {
                        "cmd": self.cmd,
                        "track_usage": self.track_usage,
                        "model": self.model,
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
        executable = Path(argv[0]).name.lower()
        return executable in {"codex", "codex.exe"}

    def _argv_with_json_events(self, argv: list[str]) -> list[str]:
        if not self.track_usage:
            return list(argv)
        if "--json" in argv:
            return list(argv)
        if len(argv) >= 2 and argv[1].lower() in {"exec", "e"}:
            return [argv[0], argv[1], "--json", *argv[2:]]
        return [argv[0], "--json", *argv[1:]]

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
                    usage = CodexCliProvider._normalize_usage(payload.get("usage"))
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
        return usage

    def _record_usage(self, usage: Any) -> None:
        normalized = self._normalize_usage(usage)
        if normalized is None:
            return
        for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
            self._usage_totals[key] += normalized.get(key, 0)
        self._usage_totals["calls_with_usage"] += 1

    def usage_summary(self) -> dict[str, int]:
        return {
            **self._usage_totals,
            "calls_total": self._calls_total,
        }

    @staticmethod
    def _is_stdin_tty_error(completed: subprocess.CompletedProcess[str]) -> bool:
        detail = f"{completed.stderr or ''}\n{completed.stdout or ''}".lower()
        return "stdin is not a terminal" in detail


_MODEL_CONFIG_LINE_RE = re.compile(r"^\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$")
_CODEX_EXECUTABLES = {"codex", "codex.exe"}
_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_FULL_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-full.prompt.md"
_AUGMENT_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-augment.prompt.md"
_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}

_FULL_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text BLOCKS for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You must assign exactly ONE label to EACH block.
- Downstream will highlight the ENTIRE block for the label you choose.
  So do NOT try to label substrings. Choose the best single label for the whole block.

GOAL
For each block, choose the label that best describes what the block IS, using local context
(neighboring blocks) to determine whether we are inside a recipe or in general/narrative text.

RETURN FORMAT (STRICT)
Return STRICT JSON ONLY. No markdown, no commentary, no extra keys.
Output format exactly:
[{"block_index": <int>, "label": "<LABEL>"}]

HARD RULES
1) Include EVERY input block_index exactly once.
2) Keep the SAME ORDER as the blocks are listed.
3) label must be exactly one of:
   {{ALLOWED_LABELS}}
{{UNCERTAINTY_HINT}}

HOW TO DECIDE (STEP-BY-STEP)
A) First, detect whether a recipe is present nearby:
   - Strong recipe signals: RECIPE_TITLE, a run of INGREDIENT_LINE blocks, numbered steps,
     imperative cooking verbs ("mix", "bake", "stir"), "Serves/Makes", "Prep/Cook/Total".
   - If those signals are present, treat contiguous nearby blocks as part of that recipe
     unless they are clearly unrelated noise (page number, copyright, photo credit, etc).

B) Then label each block using the definitions + tie-break rules below.

LABEL DEFINITIONS (WITH HEURISTICS)

RECIPE_TITLE
- The NAME of a specific dish/recipe (usually short).
- Often Title Case or ALL CAPS; may include descriptors like "Classic...", "Quick...".
- NOT this: chapter/section headers ("Sauces", "Breakfast"), running headers/footers,
  "Ingredients", "Directions", "Method", "Notes" by themselves.

INGREDIENT_LINE
- A line (or block mostly composed of lines) listing ingredients, typically with:
  - a quantity and/or unit (1, 1/2, 200 g, tbsp, cup, oz, ml),
  - an ingredient noun (flour, butter, garlic),
  - optional prep descriptors (chopped, minced, room temperature).
- Also includes ingredient sub-lists that are still ingredients (e.g., "For the sauce: ...").
- If the block is a MIX of ingredients and instructions, label OTHER (see "Mixed blocks").

INSTRUCTION_LINE
- A preparation step: actions to perform, often imperative verbs and sentences:
  "Preheat...", "Whisk...", "Bake...", "Stir...", "Serve..."
- Numbered steps ("1.", "Step 2") are instructions.
- Also includes short imperative fragments ("Let rest 10 minutes.").

YIELD_LINE
- Statements about servings or yield / amount produced:
  "Serves 4", "Makes 24 cookies", "Yield: 2 loaves", "Feeds a crowd", "About 1 quart".
- If yield is embedded with time in the SAME block, use the tie-break rule under TIME_LINE.

TIME_LINE
- Statements about time durations, prep/cook/total/chill/rest times:
  "Prep: 10 min", "Cook time 1 hour", "Total: 1:15", "Chill overnight".
- If a single block contains BOTH time and yield:
  - Choose TIME_LINE if any explicit time durations or "prep/cook/total" appear.
  - Otherwise choose YIELD_LINE.

RECIPE_NOTES
- Extra notes specific to the CURRENT recipe (not a distinct alternate version):
- tips, storage, make-ahead, serving suggestions, substitutions that do not define a new variant,
  warnings ("do not overmix"), sourcing for an ingredient used above, etc.
- Often introduced by: "Note:", "Notes:", "Tip:", "Chef's note:", "Serving suggestion:".
- IMPORTANT: If we are clearly inside a recipe, prefer RECIPE_NOTES instead of KNOWLEDGE.

RECIPE_VARIANT
- An alternate version of the recipe that changes ingredients/method in a defined way:
  "Variation: ...", "Variations: ...", "For a vegan version...", "To make it spicy...", "Option B..."
- If it is a small tip and not a distinct version, use RECIPE_NOTES instead.

KNOWLEDGE
- General cooking knowledge NOT tied to a specific recipe instance:
  technique explanations, ingredient/tool background, how-to guidance, rules of thumb.
  Example: "Searing builds flavor by...", "How to choose ripe avocados..."
- Use KNOWLEDGE mainly when the surrounding text is NOT a recipe (chapter intro, technique section).
- If it appears inside a recipe section, only use KNOWLEDGE if it is clearly a standalone
  general sidebar; otherwise use RECIPE_NOTES.

OTHER
- Anything that does not fit the above labels, including:
- chapter titles/section headers, narrative fluff unrelated to cooking knowledge,
- page numbers, headers/footers, copyright, photo credits,
- indexes, tables of contents, references,
- "Ingredients"/"Directions"/"Method" headers by themselves,
- mixed-content blocks where no single recipe label dominates.

MIXED BLOCKS (IMPORTANT)
Because you can only choose ONE label per block:
- If the block is mostly ingredient lines -> INGREDIENT_LINE.
- If the block is mostly instruction steps -> INSTRUCTION_LINE.
- If it is truly mixed (e.g., ingredients + instructions interleaved, or recipe + narrative) -> OTHER.

FINAL CHECK BEFORE YOU ANSWER
- Did you label every provided block_index exactly once?
- Are labels exactly from the allowed set?
- Is the output STRICT JSON only (no trailing commas, no comments)?

Segment id: {{SEGMENT_ID}}
Blocks:
{{BLOCKS_JSON_LINES}}"""

_AUGMENT_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text BLOCKS for an additive annotation pass.
Return STRICT JSON only.
Output format exactly:
[{"block_index": <int>, "label": "<LABEL>"}]
Mode: augment existing annotations.
Only return blocks that should receive a NEW additional label.
Do not return labels that already exist on a block.
Allowed labels: {{ALLOWED_LABELS}}.
Only add labels from: {{ADD_LABELS}}.
Segment id: {{SEGMENT_ID}}
Existing labels per block:
{{EXISTING_LABELS_PER_BLOCK}}
Blocks:
{{BLOCKS_JSON_LINES}}"""


def _is_codex_executable(executable: str) -> bool:
    return Path(executable).name.lower() in _CODEX_EXECUTABLES


def _extract_model_from_config_override(value: str) -> str | None:
    stripped = value.strip()
    if not stripped.startswith("model="):
        return None
    parsed = stripped.split("=", 1)[1].strip()
    if len(parsed) >= 2 and parsed[0] == parsed[-1] and parsed[0] in {"'", '"'}:
        parsed = parsed[1:-1]
    normalized = parsed.strip()
    return normalized or None


def _argv_has_model_setting(argv: list[str]) -> bool:
    index = 1
    while index < len(argv):
        token = argv[index]
        if token in {"-m", "--model"}:
            return True
        if token.startswith("--model="):
            return True
        if token == "-c" and index + 1 < len(argv):
            if _extract_model_from_config_override(argv[index + 1]):
                return True
            index += 2
            continue
        if token.startswith("-c"):
            candidate = token[2:]
            if _extract_model_from_config_override(candidate):
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


def default_codex_model() -> str | None:
    """Resolve default codex model from env then Codex config file."""
    env_model = os.environ.get("COOKIMPORT_CODEX_MODEL")
    if env_model and env_model.strip():
        return env_model.strip()

    config_paths = [
        Path.home() / ".codex-alt" / "config.toml",
        Path.home() / ".codex" / "config.toml",
    ]
    for path in config_paths:
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


def resolve_codex_model(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if normalized:
        return normalized
    return default_codex_model()


def extract_first_json_value(raw: str) -> Any:
    """Extract the first JSON array/object embedded in model output."""
    decoder = json.JSONDecoder()
    for index, ch in enumerate(raw):
        if ch not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(raw[index:])
        except json.JSONDecodeError:
            continue
        return value
    raise ValueError("No JSON object/array found in model output")


def _coerce_selection_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("selections", "labels", "items", "blocks"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def parse_block_label_output(raw: str) -> list[dict[str, Any]]:
    """Parse model output into `{block_index, label}` records."""
    payload = extract_first_json_value(raw)
    items = _coerce_selection_items(payload)
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for item in items:
        block_index_raw = item.get("block_index")
        label_raw = item.get("label") or item.get("tag") or item.get("category")
        if block_index_raw is None or not label_raw:
            continue
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        label = normalize_freeform_label(str(label_raw))
        key = (block_index, label)
        if key in seen:
            continue
        seen.add(key)
        parsed.append({"block_index": block_index, "label": label})
    return parsed


def _extract_task_data(task: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    segment_id = str(data.get("segment_id") or "")
    if not segment_id:
        raise ValueError("task missing data.segment_id")
    segment_text = str(data.get("segment_text") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise ValueError("task source_map.blocks missing/empty")
    source_blocks = [item for item in blocks if isinstance(item, dict)]
    if not source_blocks:
        raise ValueError("task source_map.blocks has no valid entries")
    return segment_id, segment_text, source_blocks


def _build_block_map(task: dict[str, Any]) -> dict[int, tuple[int, int]]:
    _segment_id, segment_text, source_blocks = _extract_task_data(task)
    block_map: dict[int, tuple[int, int]] = {}
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        start_raw = item.get("segment_start")
        end_raw = item.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_map[block_index] = (start, end)
    return block_map


def _result_key(result_item: dict[str, Any]) -> tuple[str, int, int]:
    value = result_item.get("value")
    if not isinstance(value, dict):
        return ("", -1, -1)
    labels = value.get("labels")
    if not isinstance(labels, list) or not labels:
        return ("", -1, -1)
    label = normalize_freeform_label(str(labels[0]))
    try:
        start = int(value.get("start"))
        end = int(value.get("end"))
    except (TypeError, ValueError):
        return ("", -1, -1)
    return (label, start, end)


def merge_annotation_results(
    base_results: list[dict[str, Any]],
    new_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge base + new span results, deduping exact label/range duplicates."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in [*base_results, *new_results]:
        if not isinstance(item, dict):
            continue
        key = _result_key(item)
        if key in seen or key[1] < 0:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def select_latest_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the latest annotation attached to a Label Studio task."""
    annotations = task.get("annotations") or task.get("completions") or []
    if not isinstance(annotations, list):
        return None
    candidates = [item for item in annotations if isinstance(item, dict)]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("id") or 0)
    return candidates[-1]


def annotation_labels(annotation: dict[str, Any] | None) -> set[str]:
    """Return canonical label names used in an annotation."""
    if not isinstance(annotation, dict):
        return set()
    labels: set[str] = set()
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        for label in value.get("labels") or []:
            labels.add(normalize_freeform_label(str(label)))
    return labels


def _build_annotation_result_item(
    *,
    segment_id: str,
    segment_text: str,
    block_index: int,
    start: int,
    end: int,
    label: str,
) -> dict[str, Any]:
    text = segment_text[start:end]
    digest = hashlib.sha256(
        f"{segment_id}|{block_index}|{start}|{end}|{label}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "id": f"cookimport-prelabel-{digest}",
        "from_name": FREEFORM_LABEL_CONTROL_NAME,
        "to_name": FREEFORM_TEXT_NAME,
        "type": FREEFORM_LABEL_RESULT_TYPE,
        "value": {
            "start": start,
            "end": end,
            "text": text,
            "labels": [label],
        },
    }


def _annotation_to_block_labels(
    *,
    annotation: dict[str, Any] | None,
    source_map: dict[str, Any],
) -> dict[int, set[str]]:
    block_labels: dict[int, set[str]] = {}
    if not isinstance(annotation, dict):
        return block_labels
    for item in annotation.get("result") or []:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if not isinstance(value, dict):
            continue
        labels = value.get("labels")
        if not isinstance(labels, list) or not labels:
            continue
        label = normalize_freeform_label(str(labels[0]))
        try:
            start = int(value.get("start"))
            end = int(value.get("end"))
        except (TypeError, ValueError):
            continue
        for touched in map_span_offsets_to_blocks(source_map, start, end):
            if not isinstance(touched, dict):
                continue
            block_index_raw = touched.get("block_index")
            try:
                block_index = int(block_index_raw)
            except (TypeError, ValueError):
                continue
            block_labels.setdefault(block_index, set()).add(label)
    return block_labels


def _load_prompt_template(path: Path, *, fallback: str) -> str:
    cached = _PROMPT_TEMPLATE_CACHE.get(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        text = path.read_text(encoding="utf-8").strip()
        if text:
            _PROMPT_TEMPLATE_CACHE[path] = (mtime_ns, text)
            return text
    except OSError:
        pass
    return fallback


def _render_prompt_template(
    *,
    path: Path,
    fallback: str,
    replacements: dict[str, str],
) -> str:
    rendered = _load_prompt_template(path, fallback=fallback)
    for token, value in replacements.items():
        rendered = rendered.replace(token, value)
    return rendered


def _build_prompt(
    *,
    task: dict[str, Any],
    allowed_labels: set[str],
    mode: str,
    augment_only_labels: set[str] | None,
    base_annotation: dict[str, Any] | None,
) -> str:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("task missing data")
    segment_text = str(data.get("segment_text") or "")
    segment_id = str(data.get("segment_id") or "")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing source_map")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list):
        raise ValueError("task source_map.blocks missing")

    lines: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_index_raw = block.get("block_index")
        start_raw = block.get("segment_start")
        end_raw = block.get("segment_end")
        try:
            block_index = int(block_index_raw)
            start = int(start_raw)
            end = int(end_raw)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        block_text = segment_text[start:end]
        lines.append(
            json.dumps(
                {"block_index": block_index, "text": block_text},
                ensure_ascii=False,
            )
        )

    ordered_allowed_labels = [
        label for label in FREEFORM_LABELS if label in set(allowed_labels)
    ]
    allowed_labels_text = ", ".join(ordered_allowed_labels)
    blocks_json_lines = "\n".join(lines)
    if mode == "augment":
        augment_set = set(augment_only_labels or [])
        add_labels = [label for label in FREEFORM_LABELS if label in augment_set]
        existing = _annotation_to_block_labels(
            annotation=base_annotation,
            source_map=source_map,
        )
        existing_rows = (
            "\n".join(
                f"- block_index={block_index}: {sorted(labels)}"
                for block_index, labels in sorted(existing.items())
            )
            if existing
            else "(none)"
        )
        return _render_prompt_template(
            path=_AUGMENT_PROMPT_TEMPLATE_PATH,
            fallback=_AUGMENT_PROMPT_TEMPLATE_FALLBACK,
            replacements={
                "{{ALLOWED_LABELS}}": allowed_labels_text,
                "{{ADD_LABELS}}": ", ".join(add_labels) if add_labels else "(none)",
                "{{SEGMENT_ID}}": segment_id,
                "{{EXISTING_LABELS_PER_BLOCK}}": existing_rows,
                "{{BLOCKS_JSON_LINES}}": blocks_json_lines,
            },
        )

    if "OTHER" in ordered_allowed_labels and "RECIPE_NOTES" in ordered_allowed_labels:
        uncertainty_hint = (
            "4) If uncertain, prefer OTHER (or RECIPE_NOTES if clearly inside a recipe)."
        )
    elif "OTHER" in ordered_allowed_labels:
        uncertainty_hint = "4) If uncertain, prefer OTHER."
    else:
        uncertainty_hint = "4) If uncertain, choose the closest allowed label."

    return _render_prompt_template(
        path=_FULL_PROMPT_TEMPLATE_PATH,
        fallback=_FULL_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{ALLOWED_LABELS}}": allowed_labels_text,
            "{{UNCERTAINTY_HINT}}": uncertainty_hint,
            "{{SEGMENT_ID}}": segment_id,
            "{{BLOCKS_JSON_LINES}}": blocks_json_lines,
        },
    )


def prelabel_freeform_task(
    task: dict[str, Any],
    *,
    provider: LlmProvider,
    allowed_labels: set[str] | None = None,
    mode: str = "full",
    augment_only_labels: set[str] | None = None,
    base_annotation: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Generate one Label Studio annotation from LLM block-label suggestions."""
    if mode not in {"full", "augment"}:
        raise ValueError("mode must be 'full' or 'augment'")

    normalized_allowed = {
        normalize_freeform_label(label)
        for label in (allowed_labels or set(FREEFORM_ALLOWED_LABELS))
    }
    normalized_allowed = {
        label for label in normalized_allowed if label in FREEFORM_ALLOWED_LABELS
    }
    if not normalized_allowed:
        raise ValueError("allowed_labels cannot be empty")

    normalized_augment_only: set[str] | None = None
    if augment_only_labels is not None:
        normalized_augment_only = {
            normalize_freeform_label(label) for label in augment_only_labels
        }
        normalized_augment_only &= normalized_allowed
        if not normalized_augment_only:
            return None

    segment_id, segment_text, _source_blocks = _extract_task_data(task)
    block_map = _build_block_map(task)
    if not block_map:
        raise ValueError("task source_map has no valid block offsets")

    prompt = _build_prompt(
        task=task,
        allowed_labels=normalized_allowed,
        mode=mode,
        augment_only_labels=normalized_augment_only,
        base_annotation=base_annotation,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

    raw = provider.complete(prompt)
    selections = parse_block_label_output(raw)
    if not selections:
        return None

    existing_results = (
        list(base_annotation.get("result") or [])
        if isinstance(base_annotation, dict)
        else []
    )
    existing_keys = {_result_key(item) for item in existing_results if isinstance(item, dict)}
    generated: list[dict[str, Any]] = []
    for selection in selections:
        block_index = int(selection["block_index"])
        label = normalize_freeform_label(str(selection["label"]))
        if label not in normalized_allowed:
            continue
        if mode == "augment" and normalized_augment_only is not None:
            if label not in normalized_augment_only:
                continue
        block_offsets = block_map.get(block_index)
        if block_offsets is None:
            continue
        start, end = block_offsets
        result_item = _build_annotation_result_item(
            segment_id=segment_id,
            segment_text=segment_text,
            block_index=block_index,
            start=start,
            end=end,
            label=label,
        )
        result_key = _result_key(result_item)
        if result_key in existing_keys:
            continue
        generated.append(result_item)
        existing_keys.add(result_key)

    if not generated:
        return None

    meta: dict[str, Any] = {
        "cookimport_prelabel": True,
        "mode": mode,
        "provider": provider.__class__.__name__,
        "prompt_hash": prompt_hash,
    }
    if normalized_augment_only:
        meta["added_labels"] = sorted(normalized_augment_only)
    return {
        "result": generated,
        "meta": meta,
    }


def annotation_is_cookimport_augment(
    annotation: dict[str, Any] | None,
    *,
    requested_labels: set[str],
) -> bool:
    """Return True when annotation metadata indicates this exact augment pass ran."""
    if not isinstance(annotation, dict):
        return False
    meta = annotation.get("meta")
    if not isinstance(meta, dict):
        return False
    if not meta.get("cookimport_prelabel"):
        return False
    if str(meta.get("mode") or "") != "augment":
        return False
    labels = meta.get("added_labels")
    if not isinstance(labels, list):
        return False
    normalized = {normalize_freeform_label(str(item)) for item in labels}
    wanted = {normalize_freeform_label(item) for item in requested_labels}
    return wanted.issubset(normalized)


def default_codex_cmd() -> str:
    """Resolve default codex command used by prelabel/decorate flows."""
    return os.environ.get("COOKIMPORT_CODEX_CMD", "codex exec -")
