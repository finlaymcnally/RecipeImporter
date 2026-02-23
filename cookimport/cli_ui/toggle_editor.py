from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.shortcuts import prompt

from cookimport.config.run_settings import RunSettingUiSpec, RunSettings, run_settings_ui_specs


@dataclass(frozen=True)
class _EditorRow:
    kind: str
    group: str
    spec: RunSettingUiSpec | None = None


class _EditorState:
    def __init__(self, initial: RunSettings) -> None:
        self.initial = initial
        self.specs = run_settings_ui_specs()
        self.rows = self._build_rows(self.specs)
        self.field_indices = [
            index for index, row in enumerate(self.rows) if row.kind == "field"
        ]
        if not self.field_indices:
            raise ValueError("Run settings editor has no editable fields.")
        self.selected_row_index = self.field_indices[0]
        self.values = initial.to_run_config_dict()
        self.error_message = ""

    @staticmethod
    def _build_rows(specs: list[RunSettingUiSpec]) -> list[_EditorRow]:
        rows: list[_EditorRow] = []
        group_name = ""
        for spec in specs:
            if spec.group != group_name:
                group_name = spec.group
                rows.append(_EditorRow(kind="group", group=group_name))
            rows.append(_EditorRow(kind="field", group=group_name, spec=spec))
        return rows

    def selected_spec(self) -> RunSettingUiSpec:
        row = self.rows[self.selected_row_index]
        if row.spec is None:
            raise RuntimeError("Selected row is not editable.")
        return row.spec

    def selected_value(self) -> Any:
        spec = self.selected_spec()
        return self.values.get(spec.name)

    def set_selected_value(self, value: Any) -> None:
        spec = self.selected_spec()
        self.values[spec.name] = value
        self.error_message = ""

    def move_selection(self, delta: int) -> None:
        current = self.field_indices.index(self.selected_row_index)
        next_index = max(0, min(len(self.field_indices) - 1, current + delta))
        self.selected_row_index = self.field_indices[next_index]
        self.error_message = ""

    def change_selected(self, delta: int) -> None:
        spec = self.selected_spec()
        current = self.selected_value()
        if spec.value_kind == "enum":
            if not spec.choices:
                return
            choices = list(spec.choices)
            try:
                position = choices.index(str(current))
            except ValueError:
                position = 0
            next_position = (position + delta) % len(choices)
            self.set_selected_value(choices[next_position])
            return
        if spec.value_kind == "bool":
            self.set_selected_value(not bool(current))
            return
        if spec.value_kind == "int":
            step = max(1, spec.step)
            value = int(current if current is not None else 0) + (step * delta)
            if spec.minimum is not None:
                value = max(spec.minimum, value)
            if spec.maximum is not None:
                value = min(spec.maximum, value)
            self.set_selected_value(value)

    def prompt_exact_value(self) -> None:
        spec = self.selected_spec()
        current = self.selected_value()
        value = prompt(f"{spec.label}: ", default="" if current is None else str(current))
        if value is None:
            return
        text = value.strip()
        if spec.value_kind == "int":
            try:
                parsed = int(text)
            except ValueError:
                self.error_message = f"{spec.label}: expected integer value."
                return
            if spec.minimum is not None and parsed < spec.minimum:
                self.error_message = f"{spec.label}: minimum is {spec.minimum}."
                return
            if spec.maximum is not None and parsed > spec.maximum:
                self.error_message = f"{spec.label}: maximum is {spec.maximum}."
                return
            self.set_selected_value(parsed)
            return
        if spec.value_kind == "string":
            self.set_selected_value(text)

    def build_result(self) -> RunSettings:
        merged = self.initial.to_run_config_dict()
        merged.update(self.values)
        return RunSettings.from_dict(merged, warn_context="run settings editor")

    def selected_line_index(self) -> int:
        line_index = 0
        for index, row in enumerate(self.rows):
            if row.kind == "group":
                # Group rows render as a leading spacer line plus the heading line.
                line_index += 2
                continue
            if index == self.selected_row_index:
                return line_index
            line_index += 1
        return 0


def _build_header(title: str) -> FormattedText:
    return FormattedText(
        [
            ("bold", f"{title}\n"),
            (
                "",
                "Up/Down: move  Left/Right: change  Shift/Ctrl+Left/Right: bigger step  "
                "Enter: exact value  S: save  Q/Esc: cancel",
            ),
        ]
    )


def _render_value_text(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _render_value_fragments(
    spec: RunSettingUiSpec,
    value: Any,
    *,
    row_selected: bool,
) -> list[tuple[str, str]]:
    current = _render_value_text(value)
    if spec.value_kind == "enum":
        options = list(spec.choices)
    elif spec.value_kind == "bool":
        options = ["true", "false"]
    else:
        return [("reverse" if row_selected else "", current)]

    fragments: list[tuple[str, str]] = []
    for index, option in enumerate(options):
        is_selected_option = option == current
        if is_selected_option:
            style = "reverse bold" if row_selected else "bold"
            text = f"[{option}]"
        else:
            style = "reverse" if row_selected else ""
            text = option
        fragments.append((style, text))
        if index < len(options) - 1:
            fragments.append(("reverse" if row_selected else "", " | "))
    return fragments


def _build_body(state: _EditorState) -> FormattedText:
    fragments: list[tuple[str, str]] = []
    for index, row in enumerate(state.rows):
        if row.kind == "group":
            fragments.append(("bold", f"\n[{row.group}]\n"))
            continue
        if row.spec is None:
            continue
        value = state.values.get(row.spec.name)
        row_selected = index == state.selected_row_index
        base_style = "reverse" if row_selected else ""
        marker = ">" if row_selected else " "
        fragments.append((base_style, f"{marker} {row.spec.label:<28} "))
        fragments.extend(
            _render_value_fragments(row.spec, value, row_selected=row_selected)
        )
        fragments.append(("", "\n"))
    return FormattedText(fragments)


def _build_footer(state: _EditorState) -> FormattedText:
    spec = state.selected_spec()
    value = state.selected_value()
    value_text = _render_value_text(value)
    lines = [
        f"{spec.label}: {value_text}",
        spec.description or "",
    ]
    if state.error_message:
        lines.append(f"Error: {state.error_message}")
    return FormattedText([("", "\n".join(lines))])


def _body_cursor_position(state: _EditorState) -> Point:
    return Point(x=0, y=state.selected_line_index())


def edit_run_settings(*, title: str, initial: RunSettings) -> RunSettings | None:
    """Full-screen toggle editor for per-run settings."""

    state = _EditorState(initial)
    result: RunSettings | None = None
    header = FormattedTextControl(lambda: _build_header(title))
    body = FormattedTextControl(
        lambda: _build_body(state),
        focusable=True,
        get_cursor_position=lambda: _body_cursor_position(state),
    )
    footer = FormattedTextControl(lambda: _build_footer(state))
    body_window = Window(content=body, always_hide_cursor=True)

    bindings = KeyBindings()

    @bindings.add("up")
    def _move_up(event) -> None:  # type: ignore[no-untyped-def]
        state.move_selection(-1)
        event.app.invalidate()

    @bindings.add("down")
    def _move_down(event) -> None:  # type: ignore[no-untyped-def]
        state.move_selection(1)
        event.app.invalidate()

    @bindings.add("left")
    def _left(event) -> None:  # type: ignore[no-untyped-def]
        state.change_selected(-1)
        event.app.invalidate()

    @bindings.add("right")
    def _right(event) -> None:  # type: ignore[no-untyped-def]
        state.change_selected(1)
        event.app.invalidate()

    @bindings.add("s-left")
    @bindings.add("c-left")
    def _left_big(event) -> None:  # type: ignore[no-untyped-def]
        for _ in range(5):
            state.change_selected(-1)
        event.app.invalidate()

    @bindings.add("s-right")
    @bindings.add("c-right")
    def _right_big(event) -> None:  # type: ignore[no-untyped-def]
        for _ in range(5):
            state.change_selected(1)
        event.app.invalidate()

    @bindings.add("enter")
    def _exact(event) -> None:  # type: ignore[no-untyped-def]
        event.app.run_in_terminal(state.prompt_exact_value)
        event.app.invalidate()

    @bindings.add("s")
    @bindings.add("S")
    def _save(event) -> None:  # type: ignore[no-untyped-def]
        nonlocal result
        try:
            result = state.build_result()
        except Exception as exc:  # noqa: BLE001
            state.error_message = str(exc)
            event.app.invalidate()
            return
        event.app.exit(result=result)

    @bindings.add("q")
    @bindings.add("Q")
    @bindings.add("escape")
    def _cancel(event) -> None:  # type: ignore[no-untyped-def]
        event.app.exit(result=None)

    app = Application(
        layout=Layout(
            HSplit(
                [
                    Window(content=header, height=2),
                    body_window,
                    Window(content=footer, height=3),
                ]
            ),
            focused_element=body_window,
        ),
        key_bindings=bindings,
        full_screen=True,
    )
    return app.run()
