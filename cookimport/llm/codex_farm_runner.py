from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

logger = logging.getLogger(__name__)


class CodexFarmRunnerError(RuntimeError):
    """Raised when codex-farm subprocess execution fails."""


class CodexFarmRunner(Protocol):
    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        """Run a codex-farm pipeline over input/output directories."""


@dataclass(frozen=True)
class SubprocessCodexFarmRunner:
    cmd: str = "codex-farm"

    def run_pipeline(
        self,
        pipeline_id: str,
        in_dir: Path,
        out_dir: Path,
        env: Mapping[str, str],
        *,
        root_dir: Path | None = None,
        workspace_root: Path | None = None,
    ) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        command = [
            *shlex.split(self.cmd),
            "process",
            "--pipeline",
            pipeline_id,
            "--in",
            str(in_dir),
            "--out",
            str(out_dir),
            "--json",
        ]
        if root_dir is not None:
            command.extend(["--root", str(root_dir)])
        if workspace_root is not None:
            command.extend(["--workspace-root", str(workspace_root)])
        merged_env = os.environ.copy()
        for key, value in env.items():
            merged_env[str(key)] = str(value)
        try:
            completed = subprocess.run(
                command,
                text=True,
                capture_output=True,
                check=False,
                env=merged_env,
            )
        except FileNotFoundError as exc:
            raise CodexFarmRunnerError(
                f"codex-farm command not found: {self.cmd!r}. "
                "Install codex-farm or disable llm_recipe_pipeline."
            ) from exc
        except OSError as exc:
            raise CodexFarmRunnerError(
                f"Failed to execute codex-farm command {self.cmd!r}: {exc}"
            ) from exc

        if completed.stdout.strip():
            logger.info(
                "codex-farm stdout (%s): %s",
                pipeline_id,
                completed.stdout.strip(),
            )
        if completed.stderr.strip():
            logger.warning(
                "codex-farm stderr (%s): %s",
                pipeline_id,
                completed.stderr.strip(),
            )
        if completed.returncode != 0:
            raise CodexFarmRunnerError(
                "codex-farm failed for "
                f"{pipeline_id} (exit={completed.returncode}, out_dir={out_dir})"
            )
