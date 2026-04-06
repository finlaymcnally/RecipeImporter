Yes. The official Gemini CLI equivalent to a one-shot `codex exec` run is **headless mode**, not a separate `exec` subcommand. In practice that means `gemini -p "..."` or `gemini --prompt "..."`, usually paired with `--output-format json` or `--output-format stream-json`. The JSON mode returns one envelope with `response`, `stats`, and optional `error`; the streaming mode emits JSONL events such as `tool_use` and `tool_result`, which is useful if you want worker telemetry. ([Gemini CLI][1])

Your subscription-only constraint is compatible with Gemini CLI. For an individual Google account, Google’s recommended auth path is **Sign in with Google**, and if you have Google AI Pro or Ultra you should use that same subscribed account. Most individual paid accounts do **not** need a Google Cloud project. Headless mode can reuse cached credentials, but a machine or user profile that has never signed in cannot bootstrap that auth purely headlessly; the documented headless-first auth methods are API key or Vertex AI. So for a subscription-only setup, each worker machine/user needs one initial browser-based `gemini` login before scripted runs. ([GitHub][2])

For fixed-price usage, Google’s current quota docs say Google AI Pro gets **1,500 requests per user per day** and Ultra gets **2,000**, and those limits are shared across Gemini CLI and Gemini Code Assist agent mode. Google also notes that one prompt can fan out into multiple model requests, so agentic runs burn quota faster than a simple “one prompt = one request” assumption. If you want this to stay strictly subscription-only, set `billing.overageStrategy` to `"never"`; the documented default is `"ask"` when AI credits are available. ([Google for Developers][3])

Given your current `cookimport` setup—sterile mirrored workspaces, repo-authored task files, validated `workers/*/out/*.json` as authority, and prose as telemetry—the safest Gemini integration is to preserve that same boundary instead of letting Gemini become a general repo editor. 

## What I would do in your pipeline

### 1) Best near-term fit: add a `gemini-inline-json` backend

This is the cleanest match for passes that already resemble your `inline-json-v1` contract. Put only the worker inputs into the mirrored workspace, generate a `GEMINI.md` for the worker instructions, and run Gemini in read-only mode so the repo stays the truth owner. Gemini auto-loads `GEMINI.md`, and if you keep an `AGENTS.md`, you can still force it in with `@AGENTS.md` because `@path` inclusion is built-in. The official automation docs show the model returning raw JSON inside the outer `.response` field, so your wrapper should keep doing strict parse/validate/write on the deterministic side. ([Gemini CLI][4]) 

```bash
gemini \
  --model gemini-2.5-pro \
  --approval-mode=plan \
  --output-format json \
  -p $'Read @task.json and @AGENTS.md.\nReturn ONLY a raw JSON object matching the worker output schema.\nDo not write files. Do not run shell commands.'
```

That gives you a close functional analogue to `codex exec` for structured passes, while keeping promotion and validation entirely in your existing deterministic runtime. Plan Mode is the documented read-only mode, and headless JSON output is stable enough to wrap. ([Gemini CLI][5])

### 2) If you need taskfile-style editing: use headless Gemini with per-job policies

Gemini can do file and shell tool use, but there is an important automation constraint: in non-interactive mode, any policy result of `ask_user` is treated as `deny`. So if you want file writes in a scripted run, you must pre-authorize the exact tool calls you want. The good news is Gemini CLI supports policy files, and you can inject a per-run admin policy with `--admin-policy`. You can also run with `--sandbox` for tool isolation. ([Gemini CLI][6])

A minimal shape is:

```bash
gemini \
  --model gemini-2.5-pro \
  --sandbox \
  --admin-policy /tmp/cookimport-worker.toml \
  --output-format stream-json \
  -p "Complete the task in @task.json and write the result to workers/out/result.json"
```

And the policy file would look roughly like this:

```toml
[[rule]]
toolName = "run_shell_command"
decision = "deny"
priority = 900
interactive = false

[[rule]]
toolName = ["read_file", "read_many_files", "glob", "list_directory", "grep_search"]
decision = "allow"
priority = 800
interactive = false

[[rule]]
toolName = ["write_file", "replace"]
# Tighten this against the actual tool_input shape from one traced run first.
argsPattern = "\"(path|filePath)\":\"(./)?workers/[^\\\"]+/out/[^\\\"]+\\.json\""
decision = "allow"
priority = 850
interactive = false
```

I would keep this mode narrow: deny shell, allow only the read tools you need, and allow writes only to the output path. `stream-json` is useful here because it gives you tool traces and final stats for your raw artifacts. ([Gemini CLI][6])

### 3) Best long-term fit: expose your worker contract as an MCP server

Architecturally, this is the closest match to your current design. Gemini CLI has first-class MCP support, including stdio servers, per-server allowlists, `includeTools` / `excludeTools`, and a `trust` setting. Instead of granting Gemini generic filesystem mutation, you expose only your real contract: `read_task`, `read_block_range`, `write_result`, `mark_status`, maybe `read_manifest`. That keeps stage-owned truth and validation where they already live. ([Gemini CLI][7]) 

A project-local `.gemini/settings.json` can define it like this:

```json
{
  "billing": { "overageStrategy": "never" },
  "mcp": { "allowed": ["cookimport-worker"] },
  "mcpServers": {
    "cookimport-worker": {
      "command": "python",
      "args": ["-m", "cookimport.worker_mcp"],
      "trust": true,
      "includeTools": ["read_task", "read_block_range", "write_result", "mark_status"]
    }
  }
}
```

Gemini CLI reads settings from both `~/.gemini/settings.json` and `./.gemini/settings.json`, so this works well with your mirrored worker directories: cached Google-account auth can stay with the user profile, while worker behavior lives in the per-job project config. ([Gemini CLI][8])

## The main caveats

Use the **Gemini CLI binary itself** as the subprocess. Google explicitly says piggybacking on Gemini CLI OAuth from third-party software is not allowed. So the supported subscription-only pattern is “my pipeline launches `gemini`,” not “my pipeline steals Gemini CLI auth and talks to Google with another client.” ([Gemini CLI][8])

For benchmarked or scored passes, I would **pin the model** instead of relying on Auto. Gemini CLI’s model selection docs recommend Auto for general developer use, but Auto routes between Pro and Flash, and Gemini 3.1 preview availability is still rolling out and has its own fallback behavior. If you want more reproducible semantic passes, `gemini-2.5-pro` is the safer baseline to start with. ([Gemini CLI][9])

Also, the official docs I found document **JSON envelopes** and **streamed JSON events**, and the automation tutorial shows prompting the model to emit raw JSON inside `.response`. I did **not** find official docs for a user-supplied response-schema flag on the CLI, so keep your existing deterministic validator and do not treat raw model output as authoritative by itself. ([Gemini CLI][10])

If I were implementing this tomorrow, I would start with a **`gemini-inline-json` runner** for the passes that already support inline structured outputs, and only move to **MCP-backed Gemini workers** if you decide you truly need tool use rather than plain structured responses. The next useful step would be a concrete adapter shape: runner interface, temp workspace layout, `GEMINI.md` template, and one policy/MCP config per pass.

