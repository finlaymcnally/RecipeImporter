from __future__ import annotations

from prompt_toolkit.data_structures import Point

from cookimport.cli_ui.toggle_editor import (
    _EditorState,
    _body_cursor_position,
    _render_value_fragments,
)
from cookimport.config.run_settings import RunSettings, run_settings_ui_specs
from cookimport.epub_extractor_names import epub_extractor_enabled_choices


def _spec(name: str):
    return next(spec for spec in run_settings_ui_specs() if spec.name == name)


def _text(fragments: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in fragments)


def _extractor_row(selected: str) -> str:
    return " | ".join(
        f"[{choice}]" if choice == selected else choice
        for choice in epub_extractor_enabled_choices()
    )


def test_enum_rows_show_all_options_with_selected_boxed() -> None:
    spec = _spec("epub_extractor")

    fragments = _render_value_fragments(spec, "beautifulsoup", row_selected=False)

    assert _text(fragments) == _extractor_row("beautifulsoup")


def test_bool_rows_show_both_options_with_selected_boxed() -> None:
    spec = _spec("warm_models")

    fragments = _render_value_fragments(spec, True, row_selected=False)

    assert _text(fragments) == "[true] | false"


def test_selected_row_uses_highlight_style_on_selected_option() -> None:
    spec = _spec("epub_extractor")

    fragments = _render_value_fragments(spec, "beautifulsoup", row_selected=True)

    assert _text(fragments) == _extractor_row("beautifulsoup")
    assert any(style == "reverse bold" for style, _ in fragments)


def test_cursor_position_tracks_selected_row_for_editor_scrolling() -> None:
    state = _EditorState(RunSettings())

    first_point = _body_cursor_position(state)
    state.selected_row_index = state.field_indices[-1]
    last_point = _body_cursor_position(state)

    assert isinstance(first_point, Point)
    assert isinstance(last_point, Point)
    assert last_point.y > first_point.y
