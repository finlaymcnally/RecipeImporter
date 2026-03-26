from __future__ import annotations

import subprocess
import sys

from tests.paths import REPO_ROOT


def test_benchmark_stack_has_no_undefined_names() -> None:
    targets = ["cookimport/cli_commands/labelstudio.py"]

    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F821", *targets],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        output = "\n".join(
            part for part in (result.stdout.strip(), result.stderr.strip()) if part
        )
        raise AssertionError(
            "Ruff F821 found undefined names in the benchmark command surface:\n"
            f"{output}"
        )
