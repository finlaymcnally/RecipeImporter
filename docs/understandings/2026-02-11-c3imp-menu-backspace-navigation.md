---
summary: "How interactive C3imp menu back-navigation is implemented with Backspace."
read_when:
  - Extending C3imp/cookimport interactive menu navigation
  - Debugging interactive questionary select prompt behavior
---

# C3imp Menu Backspace Navigation

- `cookimport/cli.py` now routes interactive select prompts through `_menu_select(...)`.
- `_menu_select` attaches a prompt-toolkit Backspace key binding to `questionary.select` and returns `BACK_ACTION` (`"__back__"`).
- `_menu_select` also supports `menu_help=...`, which prints a short purpose blurb before each menu so options are self-explanatory.
- Parent flows interpret `BACK_ACTION` as "go up one level" (for example, return from file/chunk-level pickers to the previous menu) instead of treating it as a normal choice.
