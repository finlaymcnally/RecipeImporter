from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .repair_recovery_policy import INLINE_JSON_TRANSPORT, TASKFILE_TRANSPORT

POLICY_MODE_SHELL_DISABLED = "shell_disabled"
POLICY_MODE_TASKFILE_ALLOWLIST = "taskfile_allowlist"
POLICY_MODE_DEBUG_PERMISSIVE = "debug_permissive"


@dataclass(frozen=True)
class CodexExecPolicySpec:
    stage_key: str | None
    transport: str | None
    policy_mode: str
    config_overrides: tuple[str, ...] = ()
    restrict_worker_path: bool = False
    shell_tool_enabled: bool | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            "stage_key": self.stage_key,
            "transport": self.transport,
            "policy_mode": self.policy_mode,
            "config_overrides": list(self.config_overrides),
            "restrict_worker_path": bool(self.restrict_worker_path),
            "shell_tool_enabled": self.shell_tool_enabled,
        }


def build_codex_exec_policy_spec(
    *,
    stage_key: str | None,
    transport: str | None,
    debug_permissive: bool = False,
) -> CodexExecPolicySpec:
    cleaned_stage_key = str(stage_key or "").strip() or None
    cleaned_transport = str(transport or "").strip() or None
    if debug_permissive:
        return CodexExecPolicySpec(
            stage_key=cleaned_stage_key,
            transport=cleaned_transport,
            policy_mode=POLICY_MODE_DEBUG_PERMISSIVE,
            shell_tool_enabled=None,
        )
    if cleaned_transport == INLINE_JSON_TRANSPORT:
        return CodexExecPolicySpec(
            stage_key=cleaned_stage_key,
            transport=cleaned_transport,
            policy_mode=POLICY_MODE_SHELL_DISABLED,
            config_overrides=('features.shell_tool=false',),
            restrict_worker_path=False,
            shell_tool_enabled=False,
        )
    if cleaned_transport == TASKFILE_TRANSPORT:
        return CodexExecPolicySpec(
            stage_key=cleaned_stage_key,
            transport=cleaned_transport,
            policy_mode=POLICY_MODE_TASKFILE_ALLOWLIST,
            restrict_worker_path=True,
            shell_tool_enabled=True,
        )
    return CodexExecPolicySpec(
        stage_key=cleaned_stage_key,
        transport=cleaned_transport,
        policy_mode=POLICY_MODE_DEBUG_PERMISSIVE,
        shell_tool_enabled=None,
    )
