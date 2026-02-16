from __future__ import annotations

from cookimport.cli_ui.toggle_editor import _render_value_fragments
from cookimport.config.run_settings import run_settings_ui_specs


def _spec(name: str):
    return next(spec for spec in run_settings_ui_specs() if spec.name == name)


def _text(fragments: list[tuple[str, str]]) -> str:
    return "".join(text for _, text in fragments)


def test_enum_rows_show_all_options_with_selected_boxed() -> None:
    spec = _spec("epub_extractor")

    fragments = _render_value_fragments(spec, "legacy", row_selected=False)

    assert _text(fragments) == "unstructured | [legacy]"


def test_bool_rows_show_both_options_with_selected_boxed() -> None:
    spec = _spec("warm_models")

    fragments = _render_value_fragments(spec, True, row_selected=False)

    assert _text(fragments) == "[true] | false"


def test_selected_row_uses_highlight_style_on_selected_option() -> None:
    spec = _spec("epub_extractor")

    fragments = _render_value_fragments(spec, "legacy", row_selected=True)

    assert _text(fragments) == "unstructured | [legacy]"
    assert any(style == "reverse bold" for style, _ in fragments)
