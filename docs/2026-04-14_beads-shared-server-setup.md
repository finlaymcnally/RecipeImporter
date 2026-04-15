---
summary: "Short operating note for Beads shared-server setup, remote policy, and divergence recovery."
read_when:
  - When enabling bd on a repo for the first time
  - When moving a repo from embedded Beads mode to shared-server mode
  - When bd reports `no common ancestor` or agents are hitting embedded lock errors
---

# Beads Shared-Server Setup

Default policy for this machine:

- If a repo has a normal git remote, Beads should use that repo's remote as its Dolt remote.
- If a repo has no git remote, use a local filesystem Beads remote instead, for example under `~/.local/share/beads-remotes/<repo>`.
- Prefer `bd init --server --shared-server` for new repos so all repos share one local Dolt server.

Why this exists:

- Embedded mode (`bd context` shows `dolt_mode: "embedded"`) is prone to exclusive-lock errors when multiple `bd` commands overlap.
- Shared-server mode (`dolt_mode: "server"`) removes that lock bottleneck and is the default target on this machine.

## New repo setup

When the repo already has a git remote and no existing Beads history:

```bash
bd init --server --shared-server --non-interactive
bd context --json
bd dolt remote list --json
bd dolt push
```

When the repo has no git remote:

```bash
bd init --server --shared-server --non-interactive
bd dolt remote add origin file://$HOME/.local/share/beads-remotes/<repo>
bd dolt push
```

## Existing repo with Beads history

If the repo already has Beads history on its remote, do not run a fresh `bd init` in a new clone/worktree.
Use:

```bash
bd bootstrap
```

That clones the existing Beads database and avoids divergent Dolt histories.

## Embedded to server migration

Safe pattern used in `recipeimport`:

1. Make a filesystem copy of `.beads`.
2. `bd export --all -o <backup.jsonl>`
3. Move the old `.beads` aside.
4. `bd init --server --shared-server --non-interactive -p <repo>`
5. `bd import <backup.jsonl>`
6. Verify counts and spot-check with `bd context --json`, `bd count --json`, and `bd show <id> --json`.

## Divergent history recovery

If `bd dolt push` fails with `no common ancestor`, local and remote Beads histories diverged.

Use one of these paths deliberately:

- Remote is authoritative: `bd bootstrap`
- Local is authoritative: `bd dolt push --force`

Do not re-run `bd init` repeatedly against the same remote. That is how the divergence usually starts.
