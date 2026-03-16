from __future__ import annotations

from cookimport.parsing import canonical_line_roles as canonical_line_roles_module


def test_line_role_codex_max_inflight_reads_env_without_name_error(
    monkeypatch,
) -> None:
    monkeypatch.setenv("COOKIMPORT_LINE_ROLE_CODEX_MAX_INFLIGHT", "11")

    assert canonical_line_roles_module._resolve_line_role_codex_max_inflight() == 11
