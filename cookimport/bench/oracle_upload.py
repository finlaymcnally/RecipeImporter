from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ORACLE_BROWSER_CMD = "/home/mcnal/.local/bin/oracle-browser-headless"
ORACLE_DEFAULT_MODEL = "gpt-5.2-pro"
ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES = 1_000_000
ORACLE_DRY_RUN_BASE_COMMAND = (
    "npx",
    "-y",
    "@steipete/oracle",
    "--dry-run",
    "summary",
    "--files-report",
)
BENCHMARK_UPLOAD_BUNDLE_DIR_NAME = "upload_bundle_v1"
BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES = (
    "upload_bundle_overview.md",
    "upload_bundle_index.json",
    "upload_bundle_payload.jsonl",
)


@dataclass(frozen=True)
class OracleBenchmarkBundleTarget:
    requested_path: Path
    source_root: Path
    bundle_dir: Path
    scope: str


@dataclass(frozen=True)
class OracleUploadResult:
    success: bool
    mode: str
    command: list[str]
    bundle_dir: Path
    returncode: int
    stdout: str
    stderr: str


def _infer_bundle_scope(source_root: Path) -> str:
    name = source_root.name.strip().lower()
    parent_name = source_root.parent.name.strip().lower()
    if name == "single-profile-benchmark":
        return "single_profile_group"
    if name == "single-offline-benchmark":
        return "single_offline"
    if parent_name == "single-profile-benchmark":
        return "single_profile_target"
    if parent_name == "single-offline-benchmark":
        return "single_offline"
    return "benchmark_bundle"


def _missing_bundle_files(bundle_dir: Path) -> list[str]:
    return [
        file_name
        for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES
        if not (bundle_dir / file_name).is_file()
    ]


def resolve_oracle_benchmark_bundle(path: Path) -> OracleBenchmarkBundleTarget:
    requested_path = path.expanduser().resolve(strict=False)
    if requested_path.name == BENCHMARK_UPLOAD_BUNDLE_DIR_NAME:
        bundle_dir = requested_path
        source_root = requested_path.parent
    else:
        source_root = requested_path
        bundle_dir = source_root / BENCHMARK_UPLOAD_BUNDLE_DIR_NAME

    missing = _missing_bundle_files(bundle_dir)
    if missing:
        missing_text = ", ".join(sorted(missing))
        raise ValueError(
            f"Benchmark upload bundle not found at {bundle_dir} (missing: {missing_text})."
        )

    return OracleBenchmarkBundleTarget(
        requested_path=requested_path,
        source_root=source_root,
        bundle_dir=bundle_dir,
        scope=_infer_bundle_scope(source_root),
    )


def build_oracle_benchmark_prompt(*, target: OracleBenchmarkBundleTarget) -> str:
    return "\n".join(
        [
            "You are reviewing a benchmark upload bundle for the local `cookimport` CLI.",
            "The attached directory is an existing `upload_bundle_v1` benchmark package, not raw repo source code.",
            "Start with `upload_bundle_overview.md`, then use `upload_bundle_index.json` and `upload_bundle_payload.jsonl` only as needed to verify details.",
            f"The bundle scope is `{target.scope}` and the benchmark root is `{target.source_root}`.",
            "Return a concise review with exactly three sections: `Top regressions`, `Likely cause buckets`, and `Immediate next checks`.",
            "Keep the response factual and grounded in the attached bundle. Do not suggest rerunning the benchmark unless the bundle is clearly missing required evidence.",
        ]
    )


def _oracle_file_argument(path: Path) -> str:
    try:
        return os.path.relpath(path, Path.cwd())
    except Exception:
        return str(path)


def _oracle_file_arguments(bundle_dir: Path) -> list[str]:
    return [
        _oracle_file_argument(bundle_dir / file_name)
        for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES
    ]


def _oversized_bundle_files(bundle_dir: Path) -> list[tuple[str, int]]:
    oversized: list[tuple[str, int]] = []
    for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
        path = bundle_dir / file_name
        try:
            size_bytes = path.stat().st_size
        except OSError:
            continue
        if size_bytes > ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES:
            oversized.append((file_name, size_bytes))
    return oversized


def _oracle_command(
    *,
    target: OracleBenchmarkBundleTarget,
    mode: str,
    model: str,
) -> list[str]:
    normalized_mode = mode.strip().lower()
    prompt = build_oracle_benchmark_prompt(target=target)
    file_arguments = _oracle_file_arguments(target.bundle_dir)
    if normalized_mode == "browser":
        command = [
            ORACLE_BROWSER_CMD,
            "--model",
            model,
            "-p",
            prompt,
        ]
        for file_argument in file_arguments:
            command.extend(["--file", file_argument])
        return command
    if normalized_mode == "dry-run":
        command = [
            *ORACLE_DRY_RUN_BASE_COMMAND,
            "--model",
            model,
            "-p",
            prompt,
        ]
        for file_argument in file_arguments:
            command.extend(["--file", file_argument])
        return command
    raise ValueError(f"Unsupported Oracle upload mode: {mode}")


def run_oracle_benchmark_upload(
    *,
    target: OracleBenchmarkBundleTarget,
    mode: str,
    model: str = ORACLE_DEFAULT_MODEL,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> OracleUploadResult:
    normalized_mode = mode.strip().lower()
    oversized_files = (
        _oversized_bundle_files(target.bundle_dir)
        if normalized_mode == "dry-run"
        else []
    )
    if oversized_files:
        browser_command = _oracle_command(target=target, mode="browser", model=model)
        oversized_text = ", ".join(
            f"{name} ({size_bytes} bytes)" for name, size_bytes in oversized_files
        )
        return OracleUploadResult(
            success=True,
            mode=normalized_mode,
            command=browser_command,
            bundle_dir=target.bundle_dir,
            returncode=0,
            stdout=(
                "Local dry-run preview only. Oracle inline dry-run rejects files over "
                f"{ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES} bytes, so no Oracle subprocess "
                f"was started. Oversized files: {oversized_text}. Use browser mode for "
                "the real upload."
            ),
            stderr="",
        )

    command = _oracle_command(target=target, mode=normalized_mode, model=model)
    completed = runner(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return OracleUploadResult(
        success=completed.returncode == 0,
        mode=normalized_mode,
        command=command,
        bundle_dir=target.bundle_dir,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )
