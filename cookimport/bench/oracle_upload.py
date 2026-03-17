from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ORACLE_BROWSER_CMD = "/home/mcnal/.nvm/versions/node/v20.19.6/bin/oracle"
ORACLE_BROWSER_CHROME_PATH = "/home/mcnal/.local/bin/chromium-nosandbox-xvfb"
ORACLE_BROWSER_REMOTE_DEBUG_HOST = "127.0.0.1"
ORACLE_DEFAULT_MODEL = "gpt-5.2"
ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES = 1_000_000
ORACLE_BROWSER_SHARD_TARGET_BYTES = 900_000
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


@dataclass(frozen=True)
class PreparedOracleUploadInputs:
    prompt: str
    file_paths: list[Path]
    note: str = ""


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


def _oracle_file_arguments(file_paths: list[Path]) -> list[str]:
    return [_oracle_file_argument(path) for path in file_paths]


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


def _split_text_to_byte_sized_chunks(text: str, *, max_bytes: int) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    current_parts: list[str] = []
    current_bytes = 0

    def flush() -> None:
        nonlocal current_parts, current_bytes
        if not current_parts:
            return
        chunks.append("".join(current_parts))
        current_parts = []
        current_bytes = 0

    def append_piece(piece: str) -> None:
        nonlocal current_bytes
        piece_bytes = len(piece.encode("utf-8"))
        if current_parts and current_bytes + piece_bytes > max_bytes:
            flush()
        if piece_bytes <= max_bytes:
            current_parts.append(piece)
            current_bytes += piece_bytes
            return
        oversized_chars: list[str] = []
        oversized_bytes = 0
        for char in piece:
            char_bytes = len(char.encode("utf-8"))
            if oversized_chars and oversized_bytes + char_bytes > max_bytes:
                chunks.append("".join(oversized_chars))
                oversized_chars = []
                oversized_bytes = 0
            oversized_chars.append(char)
            oversized_bytes += char_bytes
        if oversized_chars:
            chunks.append("".join(oversized_chars))

    for line in text.splitlines(keepends=True):
        append_piece(line)
    flush()
    return chunks or [text]


def _copy_or_shard_browser_upload_files(
    *,
    bundle_dir: Path,
    staging_dir: Path,
) -> tuple[list[Path], list[str]]:
    staged_paths: list[Path] = []
    shard_notes: list[str] = []
    for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES:
        source_path = bundle_dir / file_name
        size_bytes = source_path.stat().st_size
        if size_bytes <= ORACLE_INLINE_FILE_SIZE_LIMIT_BYTES:
            staged_path = staging_dir / file_name
            staged_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
            staged_paths.append(staged_path)
            continue

        shard_chunks = _split_text_to_byte_sized_chunks(
            source_path.read_text(encoding="utf-8"),
            max_bytes=ORACLE_BROWSER_SHARD_TARGET_BYTES,
        )
        shard_names: list[str] = []
        for index, chunk in enumerate(shard_chunks, start=1):
            shard_name = f"{source_path.stem}.part{index:03d}{source_path.suffix}"
            shard_path = staging_dir / shard_name
            shard_path.write_text(chunk, encoding="utf-8")
            staged_paths.append(shard_path)
            shard_names.append(shard_name)
        shard_notes.append(
            f"`{file_name}` was split into {len(shard_names)} ordered shards: "
            + ", ".join(f"`{name}`" for name in shard_names)
            + "."
        )
    return staged_paths, shard_notes


def _prepare_browser_upload_inputs(
    *,
    target: OracleBenchmarkBundleTarget,
    staging_dir: Path,
) -> PreparedOracleUploadInputs:
    prompt = build_oracle_benchmark_prompt(target=target)
    oversized_files = _oversized_bundle_files(target.bundle_dir)
    if not oversized_files:
        return PreparedOracleUploadInputs(
            prompt=prompt,
            file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
        )

    staged_paths, shard_notes = _copy_or_shard_browser_upload_files(
        bundle_dir=target.bundle_dir,
        staging_dir=staging_dir,
    )
    oversized_text = ", ".join(f"{name} ({size_bytes} bytes)" for name, size_bytes in oversized_files)
    prompt_lines = [
        prompt,
        "",
        "Oracle transport note: some attached bundle files were split into ordered shards to satisfy Oracle's per-file input limit before browser upload.",
        "Treat any `*.partNNN.*` attachments as the logical contents of the original file concatenated in lexical filename order.",
        *shard_notes,
        "Read `upload_bundle_overview.md` first, then `upload_bundle_index.json`, and consult payload shard rows only as needed.",
    ]
    note = (
        "Prepared sharded Oracle browser upload for oversized bundle files: "
        f"{oversized_text}."
    )
    return PreparedOracleUploadInputs(
        prompt="\n".join(prompt_lines),
        file_paths=staged_paths,
        note=note,
    )


def _oracle_command(
    *,
    mode: str,
    model: str,
    prompt: str,
    file_paths: list[Path],
) -> list[str]:
    normalized_mode = mode.strip().lower()
    file_arguments = _oracle_file_arguments(file_paths)
    if normalized_mode == "browser":
        command = [
            ORACLE_BROWSER_CMD,
            "--engine",
            "browser",
            "--browser-manual-login",
            "--browser-chrome-path",
            ORACLE_BROWSER_CHROME_PATH,
            "--browser-input-timeout",
            "90s",
            "--browser-attachments",
            "always",
            "--browser-bundle-files",
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


def _oracle_browser_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("ORACLE_BROWSER_REMOTE_DEBUG_HOST", ORACLE_BROWSER_REMOTE_DEBUG_HOST)
    return env


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
        browser_command = _oracle_command(
            mode="browser",
            model=model,
            prompt=build_oracle_benchmark_prompt(target=target),
            file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
        )
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

    if normalized_mode == "browser":
        with tempfile.TemporaryDirectory(prefix="oracle-benchmark-upload-") as staging_dir_str:
            prepared = _prepare_browser_upload_inputs(
                target=target,
                staging_dir=Path(staging_dir_str),
            )
            command = _oracle_command(
                mode=normalized_mode,
                model=model,
                prompt=prepared.prompt,
                file_paths=prepared.file_paths,
            )
            completed = runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                env=_oracle_browser_env(),
            )
        stdout = completed.stdout or ""
        if prepared.note:
            stdout = f"{prepared.note}\n{stdout}" if stdout else prepared.note
        return OracleUploadResult(
            success=completed.returncode == 0,
            mode=normalized_mode,
            command=command,
            bundle_dir=target.bundle_dir,
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=completed.stderr or "",
        )

    command = _oracle_command(
        mode=normalized_mode,
        model=model,
        prompt=build_oracle_benchmark_prompt(target=target),
        file_paths=[target.bundle_dir / file_name for file_name in BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES],
    )
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
