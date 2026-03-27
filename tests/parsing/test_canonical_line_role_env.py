from __future__ import annotations

import pytest

from cookimport.config.run_settings import RunSettings
from cookimport.parsing import canonical_line_roles as canonical_line_roles_module
from cookimport.parsing.canonical_line_roles.planning import (
    _LINE_ROLE_CODEX_EXEC_DEFAULT_CMD,
    _resolve_line_role_codex_exec_cmd,
)


def test_line_role_codex_max_inflight_reads_env_without_name_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT", "11")

    assert canonical_line_roles_module._resolve_line_role_codex_max_inflight() == 11


@pytest.mark.parametrize(
    ("configured_cmd", "expected_cmd"),
    [
        ("codex-farm", _LINE_ROLE_CODEX_EXEC_DEFAULT_CMD),
        ("codex exec", "codex exec"),
        ("codex2 e", "codex2 e"),
        ("/tmp/fake-codex-farm.py", "/tmp/fake-codex-farm.py"),
    ],
)
def test_line_role_codex_exec_cmd_uses_only_direct_exec_commands(
    configured_cmd: str,
    expected_cmd: str,
) -> None:
    settings = RunSettings.from_dict(
        {
            "line_role_pipeline": "codex-line-role-shard-v1",
            "codex_farm_cmd": configured_cmd,
        }
    )

    assert (
        _resolve_line_role_codex_exec_cmd(
            settings=settings,
            codex_cmd_override=None,
        )
        == expected_cmd
    )
