from __future__ import annotations

import tests.labelstudio.benchmark_helper_support as _support

# Reuse shared imports/helpers from the benchmark helper support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})
def test_interactive_labelstudio_export_routes_to_export_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    menu_answers = iter(["labelstudio_export", "exit"])

    def fake_menu_select(*_args, **_kwargs):
        return next(menu_answers)

    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(
        monkeypatch,
        "_golden_pulled_from_labelstudio_root",
        lambda: selected_output / "pulled-from-labelstudio",
    )
    _patch_cli_attr(
        monkeypatch,
        "_resolve_interactive_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
    _patch_cli_attr(monkeypatch, "_select_export_project", lambda **_: ("Bench Project", "freeform-spans"))
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")

    captured: dict[str, object] = {}

    def fake_run_labelstudio_export(**kwargs):
        captured.update(kwargs)
        return {"summary_path": selected_output / "summary.json"}

    _patch_cli_attr(monkeypatch, "run_labelstudio_export", fake_run_labelstudio_export)

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert captured["project_name"] == "Bench Project"
    assert captured["output_dir"] == selected_output / "pulled-from-labelstudio"

def test_interactive_labelstudio_export_selects_project_before_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected_output = tmp_path / "golden"
    events: list[str] = []

    state = {"main_calls": 0}

    def fake_menu_select(prompt: str, *_args, **_kwargs):
        events.append(f"menu:{prompt}")
        if prompt == "What would you like to do?":
            state["main_calls"] += 1
            return "labelstudio_export" if state["main_calls"] == 1 else "exit"
        raise AssertionError(f"Unexpected prompt: {prompt}")

    def fake_select_export_project(**_kwargs):
        events.append("select_project")
        return "Bench Project", None

    _patch_cli_attr(monkeypatch, "_list_importable_files", lambda *_: [])
    _patch_cli_attr(monkeypatch, "_load_settings", lambda: {})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)
    _patch_cli_attr(
        monkeypatch,
        "_golden_pulled_from_labelstudio_root",
        lambda: selected_output / "pulled-from-labelstudio",
    )
    _patch_cli_attr(
        monkeypatch,
        "_resolve_interactive_labelstudio_settings",
        lambda *_: ("http://example", "api-key"),
    )
    _patch_cli_attr(monkeypatch, "_select_export_project", fake_select_export_project)
    monkeypatch.setenv("LABEL_STUDIO_URL", "http://localhost:8080")
    monkeypatch.setenv("LABEL_STUDIO_API_KEY", "key")
    _patch_cli_attr(monkeypatch, "run_labelstudio_export",
        lambda **_kwargs: {"summary_path": selected_output / "summary.json"},
    )

    with pytest.raises(cli.typer.Exit):
        cli._interactive_mode()

    assert events == [
        "menu:What would you like to do?",
        "select_project",
        "menu:What would you like to do?",
    ]

def test_select_export_project_returns_detected_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "Alpha"},
            ]

    _patch_cli_attr(monkeypatch, "LabelStudioClient", FakeClient)
    _patch_cli_attr(monkeypatch, "_discover_manifest_project_scopes", lambda *_: {"Alpha": "pipeline"})
    _patch_cli_attr(monkeypatch, "_menu_select", lambda *_args, **_kwargs: "Alpha")

    selected, scope = cli._select_export_project(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Alpha"
    assert scope == "pipeline"

def test_select_export_project_name_uses_project_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "beta"},
                {"title": "Alpha"},
                {"title": ""},
            ]

    def fake_menu_select(*_args, **_kwargs):
        assert _kwargs["choices"][1].value == "Alpha"
        assert _kwargs["choices"][1].title == "Alpha [type: pipeline]"
        assert _kwargs["choices"][2].value == "beta"
        assert _kwargs["choices"][2].title == "beta [type: unknown]"
        return "beta"

    _patch_cli_attr(monkeypatch, "LabelStudioClient", FakeClient)
    _patch_cli_attr(monkeypatch, "_discover_manifest_project_scopes", lambda *_: {"Alpha": "pipeline"})
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "beta"

def test_select_export_project_name_prefers_manifest_scope_over_payload_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            return [
                {"title": "Alpha", "label_config": "<Label value='RECIPE_VARIANT'/>"},
            ]

    def fake_menu_select(*_args, **_kwargs):
        assert _kwargs["choices"][1].title == "Alpha [type: canonical-blocks]"
        return "Alpha"

    _patch_cli_attr(monkeypatch, "LabelStudioClient", FakeClient)
    _patch_cli_attr(monkeypatch, "_discover_manifest_project_scopes",
        lambda *_: {"Alpha": "canonical-blocks"},
    )
    _patch_cli_attr(monkeypatch, "_menu_select", fake_menu_select)

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Alpha"

def test_select_export_project_name_falls_back_to_manual_on_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RaisingClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def list_projects(self):
            raise RuntimeError("boom")

    _patch_cli_attr(monkeypatch, "LabelStudioClient", RaisingClient)
    _patch_cli_attr(monkeypatch, "_prompt_manual_project_name", lambda: "Typed Name")

    selected = cli._select_export_project_name(
        label_studio_url="http://example",
        label_studio_api_key="k",
    )
    assert selected == "Typed Name"
