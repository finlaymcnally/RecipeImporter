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
from pathlib import Path
from typing import Any, Callable, Protocol

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
        self.model = resolve_codex_model(model, cmd=self.cmd)
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "cookimport" / "prelabel"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._usage_lock = threading.Lock()
        self._calls_total = 0
        self._usage_totals = {
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "calls_with_usage": 0,
        }

    def complete(self, prompt: str) -> str:
        with self._usage_lock:
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

        turn_failed_message = self._extract_turn_failed_message(completed)
        if turn_failed_message:
            raise RuntimeError(f"Codex command failed: {turn_failed_message}")
        response, usage = self._response_and_usage(completed)
        if completed.returncode != 0:
            allow_nonzero_with_response = self.track_usage and bool(response)
            if not allow_nonzero_with_response:
                stderr = (completed.stderr or "").strip()
                stdout = (completed.stdout or "").strip()
                detail = _normalize_codex_error_detail(stderr or stdout or "unknown error")
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
            for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
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


_MODEL_CONFIG_LINE_RE = re.compile(r"^\s*model\s*=\s*['\"]([^'\"]+)['\"]\s*$")
_MODEL_REASONING_EFFORT_CONFIG_LINE_RE = re.compile(
    r"^\s*model_reasoning_effort\s*=\s*['\"]([^'\"]+)['\"]\s*$"
)
_CODEX_EXECUTABLES = {"codex", "codex.exe", "codex2", "codex2.exe"}
_CODEX_ALT_EXECUTABLE_RE = re.compile(r"^codex[0-9]+(?:\.exe)?$")
_ENV_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$")
_PROMPT_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "llm_pipelines" / "prompts"
_FULL_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-full.prompt.md"
_SPAN_PROMPT_TEMPLATE_PATH = _PROMPT_TEMPLATE_DIR / "freeform-prelabel-span.prompt.md"
_PROMPT_TEMPLATE_CACHE: dict[Path, tuple[int, str]] = {}

PRELABEL_GRANULARITY_BLOCK = "block"
PRELABEL_GRANULARITY_SPAN = "span"
_PRELABEL_GRANULARITY_ALIASES = {
    PRELABEL_GRANULARITY_BLOCK: PRELABEL_GRANULARITY_BLOCK,
    "legacy": PRELABEL_GRANULARITY_BLOCK,
    "legacy_block": PRELABEL_GRANULARITY_BLOCK,
    "legacy_block_based": PRELABEL_GRANULARITY_BLOCK,
    "legacy,_block_based": PRELABEL_GRANULARITY_BLOCK,
    "legacy,_block-based": PRELABEL_GRANULARITY_BLOCK,
    PRELABEL_GRANULARITY_SPAN: PRELABEL_GRANULARITY_SPAN,
    "actual_freeform": PRELABEL_GRANULARITY_SPAN,
    "actual_freeform_spans": PRELABEL_GRANULARITY_SPAN,
}

CODEX_REASONING_EFFORT_VALUES = (
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
)


def normalize_prelabel_granularity(value: str | None) -> str:
    normalized = (value or PRELABEL_GRANULARITY_BLOCK).strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    resolved = _PRELABEL_GRANULARITY_ALIASES.get(normalized)
    if resolved is None:
        raise ValueError(
            "prelabel_granularity must be one of: block, span "
            "(aliases: legacy, actual_freeform)."
        )
    return resolved


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


def _argv_with_json_events(argv: list[str], *, track_usage: bool) -> list[str]:
    if not track_usage:
        return list(argv)
    if "--json" in argv:
        return list(argv)
    if len(argv) >= 2 and argv[1].lower() in {"exec", "e"}:
        return [argv[0], argv[1], "--json", *argv[2:]]
    return [argv[0], "--json", *argv[1:]]

_FULL_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text BLOCKS for a "freeform spans" golden set.

IMPORTANT IMPLEMENTATION CONSTRAINT
- You must assign exactly ONE label to EACH block.
- Downstream will highlight the ENTIRE block for the label you choose.
  So do NOT try to label substrings. Choose the best single label for the whole block.

GOAL
For each block, choose the label that best describes what the block IS, using local context
(neighboring blocks) to determine whether we are inside a recipe or in general/narrative text.

FOCUS SCOPE
{{FOCUS_CONSTRAINTS}}
Focus blocks to label (context blocks may be broader):
{{FOCUS_BLOCK_JSON_LINES}}

RETURN FORMAT (STRICT)
Return STRICT JSON ONLY. No markdown, no commentary, no extra keys.
Output format exactly:
[{"block_index": <int>, "label": "<LABEL>"}]

HARD RULES
1) Return labels only for focus blocks.
2) Keep the SAME ORDER as the focus blocks listed above.
3) Include each focus block_index exactly once.
4) label must be exactly one of:
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

_SPAN_PROMPT_TEMPLATE_FALLBACK = """You are labeling cookbook text spans for a "freeform spans" golden set.

GOAL
- Return only the specific spans that should be labeled.
- You may return zero, one, or many spans per block.
- Use only these labels:
  {{ALLOWED_LABELS}}

FOCUS SCOPE
- The block list appears once at the end as a single blob.
- Label only spans from blocks between:
  <<<START_LABELING_BLOCKS_HERE>>>
  <<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>
- Blocks outside those markers are context only.

RETURN FORMAT (STRICT JSON ONLY)
Return ONLY a JSON array. No markdown. No commentary.
Each item must be one of:
1) quote-anchored span (preferred):
   {"block_index": <int>, "label": "<LABEL>", "quote": "<exact text from that block>", "occurrence": <int optional, 1-based>}
2) absolute offset span (advanced fallback):
   {"label": "<LABEL>", "start": <int>, "end": <int>}

RULES
- Return spans only for focus blocks. Non-focus blocks are context only.
- quote text must be copied exactly from block text (case and internal whitespace must match).
- You may omit leading/trailing spaces in quote.
- If the quote appears multiple times in the same block, include occurrence.
- Do not return labels outside the allowed list.

Segment id: {{SEGMENT_ID}}
Blocks:
{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}"""


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
    """Resolve default codex model from env then Codex config file."""
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
    """Resolve default codex reasoning effort from Codex config file."""
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


def list_codex_models(cmd: str | None = None) -> list[dict[str, str]]:
    """Read visible Codex model rows from local Codex model cache files."""
    models: list[dict[str, str]] = []
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
            models.append(
                {
                    "slug": slug,
                    "display_name": display_name,
                    "description": description,
                }
            )
            seen.add(slug)
    return models


def resolve_codex_model(value: str | None, *, cmd: str | None = None) -> str | None:
    normalized = (value or "").strip()
    if normalized:
        return normalized
    return default_codex_model(cmd=cmd)


def preflight_codex_model_access(*, cmd: str, timeout_s: int = 30) -> None:
    """Run one Codex probe call and fail fast for invalid model/account access."""
    normalized_cmd = cmd.strip()
    if not normalized_cmd:
        raise RuntimeError("codex command cannot be empty")
    try:
        argv = shlex.split(normalized_cmd)
    except ValueError as exc:
        raise RuntimeError(f"Unable to parse codex command: {normalized_cmd!r}") from exc
    if not argv:
        raise RuntimeError(f"Unable to parse codex command: {normalized_cmd!r}")

    def _run_probe(argv_probe: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            _argv_with_json_events(argv_probe, track_usage=True),
            input='Return EXACTLY this JSON array and nothing else: []',
            text=True,
            capture_output=True,
            timeout=max(1, int(timeout_s)),
            check=False,
        )

    completed = _run_probe(argv)
    if (
        completed.returncode != 0
        and CodexCliProvider._is_stdin_tty_error(completed)
        and CodexCliProvider._is_plain_codex_command(argv)
    ):
        completed = _run_probe([argv[0], "exec", "-"])

    turn_failed_message = CodexCliProvider._extract_turn_failed_message(completed)
    if turn_failed_message:
        raise RuntimeError(turn_failed_message)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = _normalize_codex_error_detail(stderr or stdout or "unknown error")
        raise RuntimeError(detail)


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


def _parse_optional_occurrence(value: Any) -> int | None:
    if value is None:
        return None
    try:
        occurrence = int(value)
    except (TypeError, ValueError):
        return None
    if occurrence < 1:
        return None
    return occurrence


def parse_span_label_output(raw: str) -> list[dict[str, Any]]:
    """Parse model output into quote-anchored and absolute span selections."""
    payload = extract_first_json_value(raw)
    items = _coerce_selection_items(payload)
    parsed: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        label_raw = item.get("label") or item.get("tag") or item.get("category")
        if not label_raw:
            continue
        label = normalize_freeform_label(str(label_raw))
        start_raw = item.get("start")
        end_raw = item.get("end")
        if start_raw is not None and end_raw is not None:
            try:
                start = int(start_raw)
                end = int(end_raw)
            except (TypeError, ValueError):
                continue
            key = ("absolute", label, start, end)
            if key in seen:
                continue
            seen.add(key)
            parsed.append(
                {
                    "kind": "absolute",
                    "label": label,
                    "start": start,
                    "end": end,
                }
            )
            continue

        block_index_raw = item.get("block_index")
        quote_raw = item.get("quote")
        if quote_raw is None:
            quote_raw = item.get("text") or item.get("span")
        if block_index_raw is None or quote_raw is None:
            continue
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        quote = str(quote_raw)
        if not quote:
            continue
        occurrence = _parse_optional_occurrence(item.get("occurrence"))
        key = ("quote", block_index, label, quote, occurrence)
        if key in seen:
            continue
        seen.add(key)
        parsed.append(
            {
                "kind": "quote",
                "block_index": block_index,
                "label": label,
                "quote": quote,
                "occurrence": occurrence,
            }
        )
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


def _available_block_indices(source_blocks: list[dict[str, Any]]) -> list[int]:
    available: list[int] = []
    seen: set[int] = set()
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        try:
            block_index = int(block_index_raw)
        except (TypeError, ValueError):
            continue
        if block_index in seen:
            continue
        available.append(block_index)
        seen.add(block_index)
    return available


def _resolve_focus_block_indices(
    *,
    source_map: dict[str, Any],
    available_block_indices: list[int],
) -> list[int]:
    raw_focus_indices = source_map.get("focus_block_indices")
    if not isinstance(raw_focus_indices, list):
        return list(available_block_indices)
    available = set(available_block_indices)
    focus_indices: list[int] = []
    seen: set[int] = set()
    for value in raw_focus_indices:
        try:
            block_index = int(value)
        except (TypeError, ValueError):
            continue
        if block_index in seen or block_index not in available:
            continue
        focus_indices.append(block_index)
        seen.add(block_index)
    if focus_indices:
        return focus_indices
    return list(available_block_indices)


def _resolve_focus_block_index_set(
    *,
    source_map: dict[str, Any],
    source_blocks: list[dict[str, Any]],
) -> set[int]:
    available_indices = _available_block_indices(source_blocks)
    return set(
        _resolve_focus_block_indices(
            source_map=source_map,
            available_block_indices=available_indices,
        )
    )


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


def _find_substring_matches(text: str, needle: str) -> list[tuple[int, int]]:
    if not needle:
        return []
    matches: list[tuple[int, int]] = []
    cursor = 0
    while cursor <= len(text) - len(needle):
        found = text.find(needle, cursor)
        if found < 0:
            break
        matches.append((found, found + len(needle)))
        cursor = found + 1
    return matches


def _resolve_quote_offsets(
    *,
    block_text: str,
    quote: str,
    occurrence: int | None,
) -> tuple[int, int] | None:
    candidates = [quote]
    stripped = quote.strip()
    if stripped and stripped != quote:
        candidates.append(stripped)

    for needle in candidates:
        matches = _find_substring_matches(block_text, needle)
        if not matches:
            continue
        if len(matches) == 1:
            return matches[0]
        if occurrence is None:
            return None
        if 1 <= occurrence <= len(matches):
            return matches[occurrence - 1]
        return None
    return None


def _touched_block_indices_for_span(
    *,
    source_blocks: list[dict[str, Any]],
    start: int,
    end: int,
) -> set[int]:
    touched: set[int] = set()
    for item in source_blocks:
        block_index_raw = item.get("block_index")
        block_start_raw = item.get("segment_start")
        block_end_raw = item.get("segment_end")
        try:
            block_index = int(block_index_raw)
            block_start = int(block_start_raw)
            block_end = int(block_end_raw)
        except (TypeError, ValueError):
            continue
        if end <= block_start or start >= block_end:
            continue
        touched.add(block_index)
    return touched


def _build_results_for_block_mode(
    *,
    selections: list[dict[str, Any]],
    segment_id: str,
    segment_text: str,
    block_map: dict[int, tuple[int, int]],
    focus_block_indices: set[int],
    allowed_labels: set[str],
) -> list[dict[str, Any]]:
    seen_keys: set[tuple[str, int, int]] = set()
    generated: list[dict[str, Any]] = []
    for selection in selections:
        block_index = int(selection["block_index"])
        if block_index not in focus_block_indices:
            continue
        label = normalize_freeform_label(str(selection["label"]))
        if label not in allowed_labels:
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
        if result_key in seen_keys:
            continue
        generated.append(result_item)
        seen_keys.add(result_key)
    return generated


def _build_results_for_span_mode(
    *,
    selections: list[dict[str, Any]],
    segment_id: str,
    segment_text: str,
    block_map: dict[int, tuple[int, int]],
    source_blocks: list[dict[str, Any]],
    focus_block_indices: set[int],
    allowed_labels: set[str],
) -> list[dict[str, Any]]:
    seen_keys: set[tuple[str, int, int]] = set()
    generated: list[dict[str, Any]] = []
    for selection in selections:
        label = normalize_freeform_label(str(selection.get("label") or ""))
        if label not in allowed_labels:
            continue
        kind = str(selection.get("kind") or "")
        block_index = -1
        start = -1
        end = -1
        if kind == "absolute":
            try:
                start = int(selection.get("start"))
                end = int(selection.get("end"))
            except (TypeError, ValueError):
                continue
            if start < 0 or end <= start or end > len(segment_text):
                continue
            touched_block_indices = _touched_block_indices_for_span(
                source_blocks=source_blocks,
                start=start,
                end=end,
            )
            if (
                not touched_block_indices
                or not touched_block_indices.issubset(focus_block_indices)
            ):
                continue
        elif kind == "quote":
            try:
                block_index = int(selection.get("block_index"))
            except (TypeError, ValueError):
                continue
            if block_index not in focus_block_indices:
                continue
            block_offsets = block_map.get(block_index)
            if block_offsets is None:
                continue
            block_start, block_end = block_offsets
            block_text = segment_text[block_start:block_end]
            quote = str(selection.get("quote") or "")
            if not quote:
                continue
            occurrence = _parse_optional_occurrence(selection.get("occurrence"))
            resolved = _resolve_quote_offsets(
                block_text=block_text,
                quote=quote,
                occurrence=occurrence,
            )
            if resolved is None:
                continue
            start = block_start + resolved[0]
            end = block_start + resolved[1]
        else:
            continue
        if start < 0 or end <= start or end > len(segment_text):
            continue
        result_item = _build_annotation_result_item(
            segment_id=segment_id,
            segment_text=segment_text,
            block_index=block_index,
            start=start,
            end=end,
            label=label,
        )
        result_key = _result_key(result_item)
        if result_key in seen_keys:
            continue
        generated.append(result_item)
        seen_keys.add(result_key)
    return generated


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


def _collapse_block_index_ranges(indices: list[int]) -> str:
    if not indices:
        return ""
    ordered = sorted(set(indices))
    ranges: list[str] = []
    start = ordered[0]
    end = ordered[0]
    for value in ordered[1:]:
        if value == end + 1:
            end = value
            continue
        if start == end:
            ranges.append(str(start))
        else:
            ranges.append(f"{start}-{end}")
        start = value
        end = value
    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")
    return ", ".join(ranges)


def _build_focus_marked_block_lines(
    *,
    valid_blocks: list[tuple[int, str]],
    focus_block_indices: set[int],
) -> list[str]:
    marked: list[str] = []
    in_focus_run = False
    for block_index, block_text in valid_blocks:
        is_focus = block_index in focus_block_indices
        if is_focus and not in_focus_run:
            marked.append("<<<START_LABELING_BLOCKS_HERE>>>")
            in_focus_run = True
        elif in_focus_run and not is_focus:
            marked.append("<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>")
            in_focus_run = False
        marked.append(
            json.dumps(
                {"block_index": block_index, "text": block_text},
                ensure_ascii=False,
            )
        )
    if in_focus_run:
        marked.append("<<<STOP_LABELING_BLOCKS_HERE_CONTEXT_ONLY>>>")
    return marked


def _build_prompt(
    *,
    task: dict[str, Any],
    allowed_labels: set[str],
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
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

    valid_blocks: list[tuple[int, str]] = []
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
        valid_blocks.append((block_index, block_text))
        lines.append(
            json.dumps(
                {"block_index": block_index, "text": block_text},
                ensure_ascii=False,
            )
        )

    available_block_indices = [block_index for block_index, _text in valid_blocks]
    focus_block_indices = _resolve_focus_block_indices(
        source_map=source_map,
        available_block_indices=available_block_indices,
    )
    focus_block_index_set = set(focus_block_indices)
    focus_lines = [
        json.dumps({"block_index": block_index, "text": block_text}, ensure_ascii=False)
        for block_index, block_text in valid_blocks
        if block_index in focus_block_index_set
    ]
    if not focus_lines:
        focus_lines = list(lines)
        focus_block_index_set = {block_index for block_index, _text in valid_blocks}
        focus_block_indices = sorted(focus_block_index_set)

    ordered_allowed_labels = [
        label for label in FREEFORM_LABELS if label in set(allowed_labels)
    ]
    allowed_labels_text = ", ".join(ordered_allowed_labels)
    blocks_json_lines = "\n".join(lines)
    focus_blocks_json_lines = "\n".join(focus_lines)
    blocks_with_focus_markers_json_lines = "\n".join(
        _build_focus_marked_block_lines(
            valid_blocks=valid_blocks,
            focus_block_indices=focus_block_index_set,
        )
    )
    focus_block_indices_text = _collapse_block_index_ranges(focus_block_indices) or "none"
    if len(focus_lines) == len(lines):
        focus_constraints = (
            "- Focus equals context for this task: label all listed blocks.\n"
            "- Keep the same order as listed."
        )
        focus_marker_rules = "- START/STOP markers wrap the full block list for this task."
    else:
        focus_constraints = (
            "- Label only focus blocks for this task.\n"
            "- Do not label non-focus blocks; they are context only."
        )
        focus_marker_rules = (
            "- Label only spans from blocks between START/STOP markers.\n"
            "- Blocks outside markers are context only."
        )

    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
        return _render_prompt_template(
            path=_SPAN_PROMPT_TEMPLATE_PATH,
            fallback=_SPAN_PROMPT_TEMPLATE_FALLBACK,
            replacements={
                "{{ALLOWED_LABELS}}": allowed_labels_text,
                "{{FOCUS_CONSTRAINTS}}": focus_constraints,
                "{{FOCUS_BLOCK_JSON_LINES}}": focus_blocks_json_lines,
                "{{FOCUS_BLOCK_INDICES}}": focus_block_indices_text,
                "{{FOCUS_MARKER_RULES}}": focus_marker_rules,
                "{{SEGMENT_ID}}": segment_id,
                "{{BLOCKS_JSON_LINES}}": blocks_json_lines,
                "{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}": blocks_with_focus_markers_json_lines,
            },
        )

    if "OTHER" in ordered_allowed_labels and "RECIPE_NOTES" in ordered_allowed_labels:
        uncertainty_hint = (
            "5) If uncertain, prefer OTHER (or RECIPE_NOTES if clearly inside a recipe)."
        )
    elif "OTHER" in ordered_allowed_labels:
        uncertainty_hint = "5) If uncertain, prefer OTHER."
    else:
        uncertainty_hint = "5) If uncertain, choose the closest allowed label."

    return _render_prompt_template(
        path=_FULL_PROMPT_TEMPLATE_PATH,
        fallback=_FULL_PROMPT_TEMPLATE_FALLBACK,
        replacements={
            "{{ALLOWED_LABELS}}": allowed_labels_text,
            "{{UNCERTAINTY_HINT}}": uncertainty_hint,
            "{{FOCUS_CONSTRAINTS}}": focus_constraints,
            "{{FOCUS_BLOCK_JSON_LINES}}": focus_blocks_json_lines,
            "{{FOCUS_BLOCK_INDICES}}": focus_block_indices_text,
            "{{FOCUS_MARKER_RULES}}": focus_marker_rules,
            "{{SEGMENT_ID}}": segment_id,
            "{{BLOCKS_JSON_LINES}}": blocks_json_lines,
            "{{BLOCKS_WITH_FOCUS_MARKERS_JSON_LINES}}": blocks_with_focus_markers_json_lines,
        },
    )


def _build_prompt_log_entry(
    *,
    task: dict[str, Any],
    prompt: str,
    prompt_hash: str,
    allowed_labels: set[str],
    prelabel_granularity: str,
    focus_block_indices: set[int],
    provider: LlmProvider,
) -> dict[str, Any]:
    data = task.get("data") if isinstance(task, dict) else {}
    if not isinstance(data, dict):
        data = {}
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        source_map = {}
    source_blocks = source_map.get("blocks")
    if not isinstance(source_blocks, list):
        source_blocks = []
    block_indices: list[int] = []
    for block in source_blocks:
        if not isinstance(block, dict):
            continue
        try:
            block_indices.append(int(block.get("block_index")))
        except (TypeError, ValueError):
            continue
    ordered_allowed_labels = [
        label for label in FREEFORM_LABELS if label in set(allowed_labels)
    ]
    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)
    template_name = (
        _SPAN_PROMPT_TEMPLATE_PATH.name
        if normalized_granularity == PRELABEL_GRANULARITY_SPAN
        else _FULL_PROMPT_TEMPLATE_PATH.name
    )
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
        prompt_payload_description = (
            "Prompt includes allowed labels, focus constraints, focus marker rules, "
            "focus index summary, and one markerized context block JSON stream "
            "for quote/offset span resolution."
        )
    else:
        prompt_payload_description = (
            "Prompt includes allowed labels, uncertainty guidance, focus constraints, "
            "focus block JSON lines, and full context block JSON lines for block labels."
        )
    return {
        "task_scope": "freeform-spans",
        "segment_id": str(data.get("segment_id") or ""),
        "source_file": data.get("source_file"),
        "source_hash": data.get("source_hash"),
        "book_id": data.get("book_id"),
        "granularity": normalized_granularity,
        "prompt_template": template_name,
        "prompt_hash": prompt_hash,
        "prompt": prompt,
        "included_with_prompt": {
            "segment_text_char_count": len(str(data.get("segment_text") or "")),
            "segment_block_count": len(block_indices),
            "segment_block_indices": block_indices,
            "focus_block_count": len(focus_block_indices),
            "focus_block_indices": sorted(focus_block_indices),
            "allowed_labels": ordered_allowed_labels,
            "provider_class": provider.__class__.__name__,
            "provider_cmd": getattr(provider, "cmd", None),
            "provider_model": getattr(provider, "model", None),
        },
        "included_with_prompt_description": prompt_payload_description,
    }


def prelabel_freeform_task(
    task: dict[str, Any],
    *,
    provider: LlmProvider,
    allowed_labels: set[str] | None = None,
    prelabel_granularity: str = PRELABEL_GRANULARITY_BLOCK,
    prompt_log_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Generate one Label Studio annotation from LLM prelabel suggestions."""
    normalized_allowed = {
        normalize_freeform_label(label)
        for label in (allowed_labels or set(FREEFORM_ALLOWED_LABELS))
    }
    normalized_allowed = {
        label for label in normalized_allowed if label in FREEFORM_ALLOWED_LABELS
    }
    if not normalized_allowed:
        raise ValueError("allowed_labels cannot be empty")
    normalized_granularity = normalize_prelabel_granularity(prelabel_granularity)

    segment_id, segment_text, source_blocks = _extract_task_data(task)
    data = task.get("data")
    if not isinstance(data, dict):
        raise ValueError("task missing data object")
    source_map = data.get("source_map")
    if not isinstance(source_map, dict):
        raise ValueError("task missing data.source_map")
    focus_block_indices = _resolve_focus_block_index_set(
        source_map=source_map,
        source_blocks=source_blocks,
    )
    if not focus_block_indices:
        raise ValueError("task source_map has no valid focus block indices")

    block_map = _build_block_map(task)
    if not block_map:
        raise ValueError("task source_map has no valid block offsets")

    prompt = _build_prompt(
        task=task,
        allowed_labels=normalized_allowed,
        prelabel_granularity=normalized_granularity,
    )
    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    if prompt_log_callback is not None:
        prompt_log_callback(
            _build_prompt_log_entry(
                task=task,
                prompt=prompt,
                prompt_hash=prompt_hash,
                allowed_labels=normalized_allowed,
                prelabel_granularity=normalized_granularity,
                focus_block_indices=focus_block_indices,
                provider=provider,
            )
        )

    raw = provider.complete(prompt)
    if normalized_granularity == PRELABEL_GRANULARITY_SPAN:
        selections = parse_span_label_output(raw)
        generated = _build_results_for_span_mode(
            selections=selections,
            segment_id=segment_id,
            segment_text=segment_text,
            block_map=block_map,
            source_blocks=source_blocks,
            focus_block_indices=focus_block_indices,
            allowed_labels=normalized_allowed,
        )
    else:
        selections = parse_block_label_output(raw)
        generated = _build_results_for_block_mode(
            selections=selections,
            segment_id=segment_id,
            segment_text=segment_text,
            block_map=block_map,
            focus_block_indices=focus_block_indices,
            allowed_labels=normalized_allowed,
        )

    if not generated:
        return None

    return {
        "result": generated,
        "meta": {
            "cookimport_prelabel": True,
            "mode": "full",
            "provider": provider.__class__.__name__,
            "prompt_hash": prompt_hash,
            "granularity": normalized_granularity,
        },
    }


def default_codex_cmd() -> str:
    """Resolve default codex command used by prelabel flows."""
    explicit = (os.environ.get("COOKIMPORT_CODEX_CMD") or "").strip()
    if explicit:
        return explicit
    return "codex exec -"
