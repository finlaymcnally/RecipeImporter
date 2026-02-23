Interactive run-settings UI helpers.

- `run_settings_flow.py` provides the global/last/edit chooser used by interactive Import and Benchmark flows.
- `toggle_editor.py` is the prompt_toolkit full-screen row editor (arrow keys change values, `s` saves, `q`/`Esc` cancels).
- Enum/bool rows show all options inline; the current selection is boxed (`[selected]`) and highlighted.
- The editor viewport follows the selected row so long menus stay scrollable as you move through settings.
