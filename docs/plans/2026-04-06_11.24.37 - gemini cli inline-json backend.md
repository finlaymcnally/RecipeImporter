---
summary: "ExecPlan for adding a Gemini CLI headless JSON backend to the existing inline-json worker path without introducing MCP or Gemini taskfile editing."
read_when:
  - When implementing Gemini CLI support for line-role or knowledge inline-json runs
  - When deciding how Gemini should fit into the existing direct-exec runner without a repo-wide Codex rename
  - When validating auth, billing, telemetry, and resume behavior for Gemini headless structured sessions
---

# Gemini CLI Inline-JSON Backend

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `docs/PLANS.md`.

## Purpose / Big Picture

After this change, the repo will be able to run the existing `inline-json-v1` packet workflows through Gemini CLI headless JSON instead of only through Codex. The user-visible win is simple: line-role and non-recipe finalize can keep the current deterministic packet-in, validated-JSON-out contract while using `gemini` as the subprocess, with the existing repair loop and artifact trail still intact.

This plan deliberately does not add MCP, does not ask Gemini to become a general repo editor, and does not move recipe correction off its current taskfile/Codex path. The scope is the already-thin structured path only. The proof after implementation is:

1. A run configured with Gemini for inline JSON produces valid line-role and knowledge outputs through the same deterministic validators used today.
2. The structured-session repair loop still works, now by resuming Gemini sessions in the same prepared execution workspace.
3. Missing Gemini binary, missing cached auth, or unsupported local setup fail early with a clear preflight error instead of surfacing later as malformed model output.

## Progress

- [x] (2026-04-06 11:24 America/Toronto) Read `docs/PLANS.md`, `docs/reports/geminiCLI-inline-json.md`, `docs/10-llm/10-llm_README.md`, `docs/01-architecture/01-architecture_README.md`, `docs/02-cli/02-cli_README.md`, and `docs/07-bench/07-bench_README.md`.
- [x] (2026-04-06 11:24 America/Toronto) Read the current direct-exec runtime seams in `cookimport/llm/codex_exec_runner.py`, `cookimport/llm/codex_exec_command_builder.py`, `cookimport/llm/codex_exec_telemetry.py`, `cookimport/llm/knowledge_stage/workspace_run.py`, and `cookimport/parsing/canonical_line_roles/runtime_workers.py`.
- [x] (2026-04-06 11:24 America/Toronto) Verified current Gemini CLI behavior against official docs for headless JSON output, session resume, auth, `GEMINI.md`, and billing settings.
- [x] (2026-04-06 11:24 America/Toronto) Wrote this first-pass ExecPlan.
- [ ] Add a provider selector for inline JSON runs, plus Gemini-specific command/model settings, without disturbing recipe taskfile settings.
- [ ] Refactor the current direct-exec subprocess seam so packet mode can be backed by either Codex CLI or Gemini CLI.
- [ ] Preserve the existing structured-session repair behavior for knowledge and line-role using Gemini session resume in the same prepared execution workspace.
- [ ] Keep prompt-budget and runtime telemetry useful when Gemini usage fields are partial or missing cached-token detail.
- [ ] Add tests, docs, and one optional live smoke path that verifies real Gemini headless JSON behavior without running a full benchmark.

## Surprises & Discoveries

- Observation: Gemini headless mode is not limited to one totally stateless call. The current CLI supports `--resume`, and session history is project-specific.
  Evidence: official CLI reference documents `gemini -r "latest"` and `gemini -r "<session-id>" "query"`; session-management docs say sessions are stored per project root.

- Observation: workspace `.gemini/settings.json` is not a reliable required-control surface when Gemini Trusted Folders is enabled.
  Evidence: official Trusted Folders docs say project settings are ignored for untrusted folders. That means this repo should not rely on ephemeral worker-local settings for essential behavior such as loading `AGENTS.md` aliases or enforcing billing guardrails.

- Observation: OAuth-style personal-account usage does not expose cached token counts, so Gemini prompt-budget telemetry must tolerate partial token detail.
  Evidence: official FAQ says cached token information is available for API-key and Vertex users, but not for OAuth users such as personal Google accounts.

- Observation: the repo’s current inline-json stages already package the entire assignment inside the prompt text and only depend on the runner for subprocess execution plus same-session resume.
  Evidence: `cookimport/llm/knowledge_stage/structured_session_contract.py` and `cookimport/parsing/canonical_line_roles/runtime_workers.py` both embed packet JSON directly in the rendered prompt. No stage-specific packet schema change is required to swap the subprocess backend.

## Decision Log

- Decision: Gemini support in this slice is limited to `inline-json-v1` packet workers.
  Rationale: the user explicitly wants inline JSON and explicitly does not want the MCP path. Recipe correction still depends on taskfile semantics, editable durable state, and Codex-specific runtime behavior. Mixing that into the Gemini slice would slow delivery and blur authority boundaries.
  Date/Author: 2026-04-06 / Codex

- Decision: keep the existing Codex-named module surface for now, and add provider-awareness inside it rather than renaming the whole runtime first.
  Rationale: the current code, tests, docs, and reports all route through `codex_exec_*` names. A repo-wide rename would be mostly churn and would not help the first working Gemini backend land sooner.
  Date/Author: 2026-04-06 / Codex

- Decision: generate a worker-local `GEMINI.md` file when Gemini is the selected backend instead of relying on `context.fileName` overrides or reusing only `AGENTS.md`.
  Rationale: `GEMINI.md` is the native auto-loaded context file. Using it avoids dependence on workspace settings that may be ignored by Trusted Folders, and it keeps the worker instruction story obvious in raw artifacts.
  Date/Author: 2026-04-06 / Codex

- Decision: preserve same-session structured repair by reusing Gemini’s session resume behavior in the same prepared execution workspace.
  Rationale: the current line-role and knowledge inline-json implementations already assume one happy-path session with bounded repair follow-ups. Gemini can preserve that shape, so there is no need to invent a second repair model just for this provider.
  Date/Author: 2026-04-06 / Codex

- Decision: do not have repo code mutate `~/.gemini/settings.json` automatically.
  Rationale: this project is not an installer, the path is user-global, and mutating it silently would be a trust violation. The runtime should document and optionally preflight-check operator prerequisites such as `billing.overageStrategy="never"` instead.
  Date/Author: 2026-04-06 / Codex

## Outcomes & Retrospective

This plan captures a narrow path to a real Gemini backend without turning the repo inside out. The key lesson from the current runtime is that the packet stages are already thin enough; the missing piece is a provider-aware subprocess adapter, not a new stage contract.

No implementation has landed yet. If later work discovers that Gemini headless JSON stats are too sparse for acceptable prompt-budget reporting, update this section and the telemetry sections below before broadening scope.

## Context and Orientation

The current repo has two distinct direct-LLM worker shapes:

1. `taskfile-v1`, which exposes a writable `task.json` workspace and is still the active recipe-correction contract.
2. `inline-json-v1`, which already behaves like a packet worker: deterministic code renders a full prompt, the model returns one JSON payload, deterministic code validates the payload, and bounded repair prompts resume the same session when validation fails.

The active inline-json owners are:

- `cookimport/parsing/canonical_line_roles/runtime_workers.py` for canonical line-role packet runs plus repair.
- `cookimport/llm/knowledge_stage/workspace_run.py` for knowledge classification and grouping structured sessions plus repair.

The shared subprocess and telemetry seam is currently Codex-specific:

- `cookimport/llm/codex_exec_runner.py`
- `cookimport/llm/codex_exec_command_builder.py`
- `cookimport/llm/codex_exec_telemetry.py`

The current run-setting surface is also Codex-shaped:

- `cookimport/config/run_settings_types.py`
- `cookimport/config/run_settings.py`
- `cookimport/cli_ui/run_settings_flow.py`

Important Gemini facts that this plan treats as hard constraints:

- Headless mode is the supported automation surface. `gemini -p ...` or non-TTY execution runs once and exits.
- `--output-format json` returns one envelope with `response`, `stats`, and optional `error`.
- `--resume` exists, and session history is project-specific. That means resume safety depends on reusing the same prepared execution workspace for the follow-up turn.
- `GEMINI.md` is the native worker-context file Gemini auto-loads from the working directory tree.
- Headless mode can reuse cached auth, but a machine that has never authenticated cannot bootstrap personal-account OAuth fully headlessly. The operator must either sign in once interactively or use API-key / Vertex auth.

This repo should not try to “understand” Gemini outputs semantically. As with Codex inline JSON today, deterministic code remains the authority for schema parsing, row coverage, enum checks, repair generation, output writing, and artifact publication.

## Plan of Work

Start by adding one provider selector for the already-thin packet path. In `cookimport/config/run_settings_types.py`, define a new public enum for the inline-json backend, with `codex-cli` as the default and `gemini-cli` as the new option. In `cookimport/config/run_settings.py`, add the corresponding `RunSettings` field plus Gemini-specific `cmd` and `model` settings. Do not reuse `codex_farm_cmd` or `codex_farm_model` for Gemini; those settings are still meaningfully Codex- and recipe-oriented. Keep the existing `line_role_codex_exec_style` and `knowledge_codex_exec_style` fields unchanged in this slice, even though the names are imperfect.

Next, make the subprocess seam provider-aware without changing the stage contracts. Keep `cookimport/llm/codex_exec_runner.py` as the owner for now, but introduce a small backend adapter layer inside it or immediately beside it. That adapter must answer four questions for packet mode:

1. How is the command line built for an initial call?
2. How is the command line built for a resumed call?
3. How is the prompt delivered to the subprocess?
4. How is stdout converted into `CodexExecRunResult`-style fields?

Codex can keep the current stdin-plus-JSON-event-stream path. Gemini should use headless JSON mode instead. The safest prompt-delivery shape is not a giant argv string containing the full packet. Instead, the runner should write the already-rendered prompt to `prompt.txt` inside the prepared execution workspace and invoke Gemini with a small prompt that references that file, for example `@prompt.txt`. This keeps shell argument size small, leaves obvious artifacts on disk, and aligns with Gemini’s documented file-reference syntax.

Add a Gemini-specific prompt-context layer for packet mode. When the selected backend is Gemini, the prepared execution workspace should contain both the existing `AGENTS.md` and a generated `GEMINI.md`. The `GEMINI.md` file should be a narrow mirror of the worker instructions that matter for packet mode: deterministic repo code owns validation, return raw JSON only, do not write files, do not use shell commands, and do not invent helper workflows. Keep it small. This file exists only in the sterile worker workspace; do not add a repo-root `GEMINI.md` in this slice.

Then wire provider selection into the two structured runtimes. In `cookimport/llm/knowledge_stage/workspace_run.py`, the initial classification turn and all resumed repair/grouping turns should route through the selected backend when `knowledge_codex_exec_style == inline-json-v1`. In `cookimport/parsing/canonical_line_roles/runtime_workers.py`, the structured prompt path should do the same when `line_role_codex_exec_style == inline-json-v1`. Both paths must continue to use the same packet schemas, the same validation functions, the same shard proposal files, and the same repair-count limits.

Telemetry needs one careful adjustment. Gemini JSON output is an envelope, not a Codex event stream. Add provider-aware parsing so `response_text`, exit status, and whatever token fields Gemini exposes in `stats` map into the existing telemetry surface. If Gemini omits cached-token detail for OAuth-backed personal accounts, preserve the current “partial/unavailable token usage” behavior rather than fabricating zeros. Visible prompt and visible output token counts should still be computed locally the same way they are today. The important rule is that prompt-budget summaries remain honest even when provider-specific billing detail differs.

After the runner works, tighten the user-facing setup. In `cookimport/cli_ui/run_settings_flow.py`, only surface the Gemini backend chooser for stages that are actually on JSON mode. The planner should not imply that recipe taskfile mode can run on Gemini in this slice. A simple first implementation is enough: keep the existing JSON/taskfile mode picker, then let JSON mode additionally carry a backend label or follow-up choice between Codex and Gemini. If that UI slice becomes noisy, it is acceptable for the first implementation to expose the backend only through saved settings and config files, provided the docs are explicit.

Finally, update docs and tests. The docs must explain that Gemini support currently covers only inline JSON line-role and knowledge paths, that a one-time interactive `gemini` login is required for subscription-only personal-account usage unless the operator is using API-key or Vertex auth, and that `billing.overageStrategy="never"` should be set in user-level Gemini settings for strict fixed-price behavior. The tests must prove the provider switch, Gemini command building, Gemini response parsing, same-workspace resume behavior, and prompt-budget fallback behavior when some usage fields are missing.

## Milestone 1: Add Backend Settings Without Changing Runtime Behavior

In this milestone, the repo gains the configuration vocabulary needed for Gemini inline JSON, but all packet runs still execute through Codex until the backend adapter is wired.

Edit `cookimport/config/run_settings_types.py` and `cookimport/config/run_settings.py` to add:

- one inline-json backend enum, defaulting to Codex,
- one Gemini command setting, defaulting to `gemini`,
- one optional Gemini model override.

If interactive configuration is included in this milestone, update `cookimport/cli_ui/run_settings_flow.py` so JSON-mode surfaces can carry that backend choice without suggesting Gemini support for taskfile recipe work.

Acceptance for this milestone is simple: settings objects round-trip cleanly, saved config can carry the new keys, and existing tests still pass unchanged when the backend remains the default Codex value.

## Milestone 2: Introduce A Provider-Aware Packet Runner

In this milestone, packet mode becomes provider-aware while taskfile mode stays exactly as it is.

Refactor the shared runner so packet execution can be backed by either Codex or Gemini. Keep taskfile execution routed to the existing Codex path only. Add a Gemini command builder that:

- uses headless mode,
- requests JSON envelope output,
- uses the configured Gemini model when present,
- uses `--resume latest` for resumed turns in the same prepared execution workspace,
- does not depend on workspace `.gemini/settings.json` for essential behavior.

Add a Gemini response parser that reads the JSON envelope from stdout, extracts `.response` and `.error`, maps available usage fields from `.stats`, and returns a normal `CodexExecRunResult` object with a new provider/backend field attached.

Acceptance is a focused runner test suite that proves:

- initial Gemini packet command construction,
- resumed Gemini packet command construction,
- prompt delivery via `@prompt.txt`,
- JSON envelope success parsing,
- JSON envelope failure parsing,
- partial-usage handling.

## Milestone 3: Preserve Structured Session Repair On Gemini

In this milestone, the existing packet stages actually use Gemini when configured.

Wire `cookimport/llm/knowledge_stage/workspace_run.py` and `cookimport/parsing/canonical_line_roles/runtime_workers.py` to select the Gemini packet runner when the backend is Gemini and the transport style is `inline-json-v1`. Do not alter packet contents or validators. The whole point is to keep stage semantics stable while swapping only the subprocess contract.

The critical acceptance proof is that both stages still perform bounded repair in the same structured session. A Gemini initial turn must write a prepared execution workspace, and the following repair turn must reuse that same workspace when `resume_last=True`. For knowledge, the same workspace must also survive the classification-to-grouping handoff.

## Milestone 4: Add Worker Context, Preflight, And Failure Messages

In this milestone, Gemini runs become operationally sane instead of merely possible.

Teach workspace preparation to write a Gemini-native `GEMINI.md` beside `AGENTS.md` for Gemini packet runs. Add preflight checks that fail clearly when:

- the `gemini` binary is missing,
- the configured Gemini model string is empty but required by the call path,
- headless auth is unavailable for the selected local setup.

The error messages must point the operator toward the real fix: install Gemini CLI, run one interactive `gemini` login with the subscribed Google account, or provide API-key / Vertex environment auth if they truly need headless-only bootstrapping.

Acceptance is that a missing or misconfigured Gemini setup fails before stage execution starts, with no misleading “model returned invalid JSON” noise.

## Milestone 5: Keep Prompt-Budget And Artifacts Honest

In this milestone, downstream reports remain useful when Gemini is the backend.

Update runtime payloads, prompt-budget summaries, and any benchmark-facing artifacts that currently assume Codex-only packet telemetry. Do not rename the entire historical artifact vocabulary in this slice. Instead, add explicit provider fields and keep older labels only where they are treated as opaque values today.

The important behavior is:

- visible prompt/output token counts still show up,
- billed token totals use Gemini stats when available,
- missing cached-token fields do not get rewritten as zero,
- artifacts clearly indicate whether the packet call came from Codex or Gemini.

Acceptance is targeted artifact tests plus one line-role and one knowledge runtime test proving that provider metadata survives into the summary rows.

## Milestone 6: Document And Validate The Finished Path

In this milestone, the code is already working and the repo documentation catches up.

Update the owning docs at minimum in `docs/10-llm/10-llm_README.md`, and update `docs/02-cli/02-cli_README.md` if interactive configuration changed. Keep the docs short and operational. Explain:

- Gemini currently supports inline JSON only,
- recipe taskfile remains Codex-only,
- one-time interactive login may be required for subscription-backed personal-account usage,
- user-level Gemini settings should set `billing.overageStrategy` to `never` for strict fixed-price usage,
- prompt-budget token details may be partial under OAuth auth.

Acceptance is the full validation loop below plus a short operator note in the docs tree that a later agent can follow without reopening this plan.

## Concrete Steps

All commands below are run from `/home/mcnal/projects/recipeimport`.

Prepare the project-local virtual environment:

    test -x .venv/bin/python || python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install -e .[dev]

During implementation, keep the test loop narrow and intentional:

    . .venv/bin/activate
    pytest tests/llm/test_codex_exec_runner.py -q
    pytest tests/llm/test_knowledge_orchestrator_runtime_leasing.py -q
    pytest tests/parsing/test_canonical_line_roles_runtime.py -q

Once the Gemini adapter is wired, add or update focused tests for command building and parsing, then re-run the fast suite:

    . .venv/bin/activate
    ./scripts/test-suite.sh fast

Optional live smoke test after implementation. This spends real Gemini quota, so do it only when the operator explicitly wants a real-provider verification run:

    . .venv/bin/activate
    tmp_root="$(mktemp -d)"
    cd "$tmp_root"
    cat > prompt.txt <<'EOF'
    Return ONLY this JSON object and nothing else:
    {"ok":true,"backend":"gemini"}
    EOF
    gemini --approval-mode plan --output-format json -p "@prompt.txt"

Success for the smoke test is a JSON envelope on stdout whose `.response` is the raw JSON object string. If the command reports an auth problem, that is an environment/setup issue, not an inline-json contract failure.

Do not run a full live LLM benchmark as part of routine validation without explicit user approval. The benchmark path is quota-spending integration verification, not a default test loop.

## Validation and Acceptance

The finished feature is acceptable only if all of the following are true:

- A line-role run configured with `line_role_codex_exec_style=inline-json-v1` and the Gemini backend executes the structured packet path and not the taskfile path.
- A knowledge run configured with `knowledge_codex_exec_style=inline-json-v1` and the Gemini backend executes classification, repair, and grouping through the Gemini packet path.
- Gemini resumed turns reuse the same prepared execution workspace for structured-session repair.
- Deterministic validators remain the authority for malformed or incomplete output. Gemini is not granted any deterministic “smart correction” privilege.
- Prompt-budget summaries remain populated with visible token counts and truthfully marked usage availability.
- Missing Gemini setup fails in preflight with a clear remediation message.
- Recipe taskfile runs remain unchanged and continue to use the existing Codex taskfile runtime.

## Idempotence and Recovery

The code changes in this plan are additive and should be safe to rerun. The main recovery rules are:

- If Gemini setup is missing, fix the environment and rerun; do not patch around it by silently falling back to Codex.
- If a Gemini inline-json call returns invalid JSON, let the existing deterministic repair loop handle it; do not introduce provider-specific semantic heuristics.
- If the optional live smoke test fails because no cached auth exists, run one interactive `gemini` login or configure API-key / Vertex auth, then rerun the smoke test.
- Do not write to or rewrite the operator’s global `~/.gemini/settings.json` automatically. Document the needed settings instead.

## Artifacts and Notes

Important artifact expectations after implementation:

- Gemini-backed structured packet runs should still write the same prompt, response, usage, last-message, and workspace-manifest sidecars already used by the structured session paths.
- Gemini packet workspaces should include a generated `GEMINI.md` beside the existing repo instruction file so raw artifacts make the worker contract obvious.
- Runtime summaries should carry an explicit backend/provider field so later benchmark cutdowns and diagnostics can distinguish Codex packet runs from Gemini packet runs.

Example worker-local Gemini settings guidance for the human operator, not for repo code to auto-write:

    {
      "billing": {
        "overageStrategy": "never"
      }
    }

Example Gemini packet command shape the runner should approximate:

    gemini --approval-mode plan --output-format json --model gemini-2.5-pro -p "@prompt.txt"

Example resumed Gemini packet command shape:

    gemini --approval-mode plan --output-format json --resume latest -p "@prompt.txt"

## Interfaces and Dependencies

Be prescriptive about the interfaces that must exist after implementation.

In `cookimport/config/run_settings_types.py`, define a new enum for packet backends with at least:

    codex-cli
    gemini-cli

In `cookimport/config/run_settings.py`, add fields equivalent to:

    inline_json_backend: InlineJsonBackend = "codex-cli"
    gemini_cli_cmd: str = "gemini"
    gemini_cli_model: str | None = None

In the shared runner layer, define one provider-aware packet execution seam. The exact type name may vary, but the interface must be able to answer:

    run_packet_worker(
        prompt_text: str,
        input_payload: Mapping[str, Any] | None,
        working_dir: Path,
        env: Mapping[str, str],
        output_schema_path: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        timeout_seconds: int | None = None,
        completed_termination_grace_seconds: float | None = None,
        workspace_task_label: str | None = None,
        supervision_callback: Callable[[CodexExecLiveSnapshot], CodexExecSupervisionDecision | None] | None = None,
        resume_last: bool = False,
        persist_session: bool = False,
        prepared_execution_working_dir: Path | None = None,
    ) -> CodexExecRunResult

`CodexExecRunResult` should gain a provider/backend field or equivalent metadata so telemetry and summaries can distinguish packet providers without inventing a second result type.

The current stage-call sites in `cookimport/llm/knowledge_stage/workspace_run.py` and `cookimport/parsing/canonical_line_roles/runtime_workers.py` must continue to call one shared packet runner interface. The stage code must not fork into large provider-specific implementations.

Revision note (2026-04-06 / Codex): Initial ExecPlan created from current repo docs and code plus official Gemini CLI docs. Scope was intentionally limited to the existing inline-json worker path and explicitly excludes MCP and Gemini taskfile editing because the goal is the fastest honest path to a working structured-output backend.
