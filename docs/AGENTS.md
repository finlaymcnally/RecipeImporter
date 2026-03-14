# Agent Guidelines — /docs

This folder contains project documentation. Check folder-specific AGENTS.md files elsewhere for domain-specific guidance.

## Docs workflow

- Run `npm run docs:list` or `./bin/docs-list` to see summaries and Read when hints. `docs:list` is an npm script name, not a shell command.
- Read any doc whose Read when matches your task before coding.
- Keep docs current with behavior/API changes; add read_when hints on cross-cutting docs.

## Docs front matter (required)

Each `docs/**/*.md` file must start with front matter:

```md
---
summary: "One-line summary"
read_when:
  - "When this doc should be read"
---
```

`read_when` is optional but recommended.
