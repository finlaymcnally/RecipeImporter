from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def find_epubcheck_jar(explicit_path: Path | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path)

    env_path = os.environ.get("C3IMP_EPUBCHECK_JAR")
    if env_path:
        candidates.append(Path(env_path))

    tools_dir = REPO_ROOT / "tools" / "epubcheck"
    candidates.append(tools_dir / "epubcheck.jar")
    if tools_dir.exists():
        candidates.extend(sorted(tools_dir.glob("*.jar")))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def detect_epubcheck_version(jar_path: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["java", "-jar", str(jar_path), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return None
    output = (proc.stdout or proc.stderr or "").strip()
    if not output:
        return None
    return output.splitlines()[0].strip()


def run_epubcheck(epub_path: Path, jar_path: Path) -> tuple[dict[str, object], str]:
    proc = subprocess.run(
        ["java", "-jar", str(jar_path), str(epub_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(
        chunk for chunk in ((proc.stdout or "").strip(), (proc.stderr or "").strip()) if chunk
    )
    error_count = len(re.findall(r"(?im)^\s*error\b", output))
    warning_count = len(re.findall(r"(?im)^\s*warning\b", output))
    info_count = len(re.findall(r"(?im)^\s*info\b", output))
    summary = {
        "jar_path": str(jar_path),
        "java_exit_code": proc.returncode,
        "error_count": error_count,
        "warning_count": warning_count,
        "info_count": info_count,
        "command": ["java", "-jar", str(jar_path), str(epub_path)],
        "version": detect_epubcheck_version(jar_path),
    }
    return summary, output
