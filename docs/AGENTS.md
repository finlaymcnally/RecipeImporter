---
summary: "Docs workflow reminder and required front matter format for docs files."
read_when:
  - When updating docs workflow expectations
  - When fixing docs front matter drift
---

## Docs workflow

- Run `npm run docs:list` or `./bin/docs-list` to see summaries and Read when hints. `docs:list` is an npm script name, not a shell command.
- Read any doc whose Read when matches your task before coding.
- Keep docs current with behavior/API changes; add read_when hints on cross-cutting docs.

Do not read the "_log.md" files in docs/ unless we are circling a problem, the "_log.md" files only exist as anti-loop memory in case we run into a hard to solve issue.

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
