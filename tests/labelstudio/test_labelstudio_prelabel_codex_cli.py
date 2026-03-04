from __future__ import annotations

import tests.labelstudio.test_labelstudio_prelabel as _base

# Reuse shared imports/helpers from the base prelabel test module.
globals().update({
    name: value
    for name, value in _base.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})

def test_default_codex_cmd_uses_noninteractive_exec(monkeypatch) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_CMD", raising=False)
    assert default_codex_cmd() == "codex exec -"


def test_default_codex_cmd_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("COOKIMPORT_CODEX_CMD", "codex2 exec -")
    assert default_codex_cmd() == "codex2 exec -"


def test_codex_provider_retries_plain_codex_with_exec(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        if len(calls) == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="Error: stdin is not a terminal",
            )
        return SimpleNamespace(
            returncode=0,
            stdout='[{"block_index": 0, "label": "OTHER"}]',
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(cmd="codex", timeout_s=10, cache_dir=tmp_path)
    response = provider.complete("label this")

    assert response == '[{"block_index": 0, "label": "OTHER"}]'
    assert calls == [["codex"], ["codex", "exec", "-"]]


def test_codex_provider_tracks_usage_from_json_events(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def _fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"[{\\"block_index\\": 0, \\"label\\": \\"OTHER\\"}]"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":7,"output_tokens":3}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(
        cmd="codex exec -",
        timeout_s=10,
        cache_dir=tmp_path,
        track_usage=True,
    )

    response = provider.complete("label this")
    usage = provider.usage_summary()

    assert response == '[{"block_index": 0, "label": "OTHER"}]'
    assert calls == [["codex", "exec", "--json", "-"]]
    assert usage["input_tokens"] == 11
    assert usage["cached_input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["reasoning_tokens"] == 0
    assert usage["calls_with_usage"] == 1
    assert usage["calls_total"] == 1


def test_codex_provider_tracks_reasoning_tokens_from_nested_usage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def _fake_run(argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"item.completed","item":{"type":"agent_message","text":"[{\\"block_index\\": 0, \\"label\\": \\"OTHER\\"}]"}}\n'
                '{"type":"turn.completed","usage":{"input_tokens":11,"cached_input_tokens":7,"output_tokens":3,"output_tokens_details":{"reasoning_tokens":9}}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(
        cmd="codex exec -",
        timeout_s=10,
        cache_dir=tmp_path,
        track_usage=True,
    )

    provider.complete("label this")
    usage = provider.usage_summary()

    assert usage["input_tokens"] == 11
    assert usage["cached_input_tokens"] == 7
    assert usage["output_tokens"] == 3
    assert usage["reasoning_tokens"] == 9
    assert usage["calls_with_usage"] == 1
    assert usage["calls_total"] == 1


def test_codex_cmd_with_model_injects_model_for_exec() -> None:
    assert (
        codex_cmd_with_model("codex exec -", "gpt-5.3-codex")
        == "codex exec --model gpt-5.3-codex -"
    )
    assert (
        codex_cmd_with_model("codex2 exec -", "gpt-5.3-codex")
        == "codex2 exec --model gpt-5.3-codex -"
    )
    assert (
        codex_cmd_with_model("codex exec --model gpt-5.3-codex -", "gpt-5-codex")
        == "codex exec --model gpt-5.3-codex -"
    )


def test_codex_cmd_with_reasoning_effort_injects_config_for_exec() -> None:
    assert (
        codex_cmd_with_reasoning_effort("codex exec -", "high")
        == "codex exec -c 'model_reasoning_effort=\"high\"' -"
    )
    assert (
        codex_cmd_with_reasoning_effort("codex2 exec -", "xhigh")
        == "codex2 exec -c 'model_reasoning_effort=\"xhigh\"' -"
    )
    assert (
        codex_cmd_with_reasoning_effort(
            'codex exec -c model_reasoning_effort="low" -',
            "high",
        )
        == 'codex exec -c model_reasoning_effort="low" -'
    )


def test_codex_reasoning_effort_from_cmd_reads_config_override() -> None:
    assert (
        codex_reasoning_effort_from_cmd(
            'codex exec -c model_reasoning_effort="medium" -'
        )
        == "medium"
    )
    assert (
        codex_reasoning_effort_from_cmd(
            "codex exec --config 'model_reasoning_effort=\"xhigh\"' -"
        )
        == "xhigh"
    )


def test_default_codex_model_reads_codex_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config_dir = tmp_path / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-test-codex"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model() == "gpt-test-codex"


def test_default_codex_model_prefers_codex_over_codex_alt(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    codex_dir = tmp_path / ".codex"
    codex_alt_dir = tmp_path / ".codex-alt"
    codex_dir.mkdir(parents=True, exist_ok=True)
    codex_alt_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex-primary"\n',
        encoding="utf-8",
    )
    (codex_alt_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex-alt"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model() == "gpt-codex-primary"


def test_default_codex_model_reads_command_specific_codex_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("COOKIMPORT_CODEX_MODEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".codex2").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codex2" / "config.toml").write_text(
        'approval_policy = "never"\nmodel = "gpt-codex2-default"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_model(cmd="codex2 exec -") == "gpt-codex2-default"


def test_default_codex_reasoning_effort_reads_codex_config(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    config_dir = tmp_path / ".codex"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        'approval_policy = "never"\nmodel_reasoning_effort = "high"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert default_codex_reasoning_effort() == "high"


def test_list_codex_models_reads_models_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom_codex"))
    custom_root = tmp_path / "custom_codex"
    custom_root.mkdir(parents=True, exist_ok=True)
    (custom_root / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex",
                        "display_name": "gpt-5.3-codex",
                        "description": "Latest coding model",
                        "visibility": "list",
                    },
                    {
                        "slug": "private-model",
                        "display_name": "private-model",
                        "description": "hidden",
                        "visibility": "hidden",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)

    models = list_codex_models()

    assert models == [
        {
            "slug": "gpt-5.3-codex",
            "display_name": "gpt-5.3-codex",
            "description": "Latest coding model",
        }
    ]


def test_list_codex_models_reads_command_specific_cache(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    (tmp_path / ".codex2").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".codex2" / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-pro",
                        "display_name": "gpt-5.3-codex-pro",
                        "description": "Pro model",
                        "visibility": "list",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    models = list_codex_models(cmd="codex2 exec -")
    assert models == [
        {
            "slug": "gpt-5.3-codex-pro",
            "display_name": "gpt-5.3-codex-pro",
            "description": "Pro model",
        }
    ]


def test_list_codex_models_includes_supported_reasoning_efforts(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom_codex"))
    custom_root = tmp_path / "custom_codex"
    custom_root.mkdir(parents=True, exist_ok=True)
    (custom_root / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-5.3-codex-spark",
                        "display_name": "gpt-5.3-codex-spark",
                        "description": "Ultra-fast coding model",
                        "visibility": "list",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "high"},
                            {"effort": "high"},
                            {"effort": "invalid"},
                            "xhigh",
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)

    models = list_codex_models()

    assert models == [
        {
            "slug": "gpt-5.3-codex-spark",
            "display_name": "gpt-5.3-codex-spark",
            "description": "Ultra-fast coding model",
            "supported_reasoning_efforts": ["low", "high", "xhigh"],
        }
    ]


def test_codex_account_summary_reads_email_from_command_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    claims = {
        "email": "pro-account@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii")
    token = f"header.{encoded.rstrip('=')}.signature"
    auth_path = tmp_path / ".codex2" / "auth.json"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": token, "access_token": token},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert codex_account_summary("codex2 exec -") == "pro-account@example.com (pro)"


def test_codex_account_summary_prefers_codex_over_codex_alt(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    primary_claims = {
        "email": "primary@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
    }
    alt_claims = {
        "email": "alt@example.com",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    primary_token = (
        "header."
        + base64.urlsafe_b64encode(json.dumps(primary_claims).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        + ".signature"
    )
    alt_token = (
        "header."
        + base64.urlsafe_b64encode(json.dumps(alt_claims).encode("utf-8"))
        .decode("ascii")
        .rstrip("=")
        + ".signature"
    )
    primary_auth = tmp_path / ".codex" / "auth.json"
    alt_auth = tmp_path / ".codex-alt" / "auth.json"
    primary_auth.parent.mkdir(parents=True, exist_ok=True)
    alt_auth.parent.mkdir(parents=True, exist_ok=True)
    primary_auth.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": primary_token, "access_token": primary_token},
            }
        ),
        encoding="utf-8",
    )
    alt_auth.write_text(
        json.dumps(
            {
                "OPENAI_API_KEY": None,
                "tokens": {"id_token": alt_token, "access_token": alt_token},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("cookimport.labelstudio.prelabel.Path.home", lambda: tmp_path)
    assert codex_account_summary("codex exec -") == "primary@example.com (pro)"


def test_preflight_codex_model_access_raises_on_turn_failed(monkeypatch) -> None:
    def _fake_run(_argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"turn.started"}\n'
                '{"type":"turn.failed","error":{"message":"{\\"detail\\":\\"Model not supported\\"}"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)

    try:
        preflight_codex_model_access(cmd="codex exec -", timeout_s=5)
        raise AssertionError("expected preflight failure")
    except RuntimeError as exc:
        assert "Model not supported" in str(exc)


def test_codex_provider_raises_turn_failed_message(monkeypatch, tmp_path: Path) -> None:
    def _fake_run(_argv, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"type":"thread.started"}\n'
                '{"type":"turn.started"}\n'
                '{"type":"turn.failed","error":{"message":"{\\"detail\\":\\"Model denied\\"}"}}\n'
            ),
            stderr="",
        )

    monkeypatch.setattr("cookimport.labelstudio.prelabel.subprocess.run", _fake_run)
    provider = CodexCliProvider(cmd="codex exec -", timeout_s=5, cache_dir=tmp_path)

    try:
        provider.complete("label this")
        raise AssertionError("expected provider failure")
    except RuntimeError as exc:
        assert "Model denied" in str(exc)
