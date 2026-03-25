from __future__ import annotations

import sys

from cookimport.cli_support.test_safety import (
    require_heavy_test_side_effect_permission,
)

runtime = sys.modules["cookimport.cli_support.bench"]
globals().update(
    {
        name: value
        for name, value in vars(runtime).items()
        if not name.startswith("__")
    }
)

def _write_single_book_starter_pack(*, session_root: Path) -> Path | None:
    require_heavy_test_side_effect_permission("single-book starter pack generation")
    build_starter_pack_for_existing_runs = None

    try:
        from scripts.benchmark_cutdown_for_external_ai import (
            build_starter_pack_for_existing_runs,
        )
    except Exception as import_exc:  # noqa: BLE001
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "benchmark_cutdown_for_external_ai.py"
        )
        try:
            module_spec = importlib.util.spec_from_file_location(
                "cookimport_benchmark_cutdown_for_external_ai",
                script_path,
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(f"unable to load module spec from {script_path}")
            module = importlib.util.module_from_spec(module_spec)
            module_name = str(module_spec.name or "cookimport_benchmark_cutdown_for_external_ai")
            # Ensure dataclass/type introspection inside the helper script can
            # resolve its module namespace during exec_module().
            sys.modules[module_name] = module
            try:
                module_spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            build_starter_pack_for_existing_runs = getattr(
                module,
                "build_starter_pack_for_existing_runs",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            typer.secho(
                (
                    "Skipped single-book starter pack: unable to load helper "
                    f"({import_exc}; fallback failed: {fallback_exc})."
                ),
                fg=typer.colors.YELLOW,
            )
            return None

    if build_starter_pack_for_existing_runs is None:
        typer.secho(
            "Skipped single-book starter pack: helper loader unavailable.",
            fg=typer.colors.YELLOW,
        )
        return None

    try:
        build_starter_pack_for_existing_runs(
            input_dir=session_root,
            output_dir=session_root,
            write_flattened_summary=True,
        )
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Skipped single-book starter pack generation: {exc}",
            fg=typer.colors.YELLOW,
        )
        return None

    starter_pack_dir = session_root / "starter_pack_v1"
    if not starter_pack_dir.is_dir():
        typer.secho(
            "Skipped single-book starter pack generation: starter_pack_v1 missing after export.",
            fg=typer.colors.YELLOW,
        )
        return None
    return starter_pack_dir


def _write_benchmark_upload_bundle(
    *,
    source_root: Path,
    output_dir: Path,
    suppress_summary: bool,
    high_level_only: bool = False,
    target_bundle_size_bytes: int | None = None,
) -> Path | None:
    require_heavy_test_side_effect_permission("benchmark upload bundle generation")
    build_upload_bundle_for_existing_output = None

    try:
        from scripts.benchmark_cutdown_for_external_ai import (
            build_upload_bundle_for_existing_output,
        )
    except Exception as import_exc:  # noqa: BLE001
        script_path = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "benchmark_cutdown_for_external_ai.py"
        )
        try:
            module_spec = importlib.util.spec_from_file_location(
                "cookimport_benchmark_cutdown_for_external_ai",
                script_path,
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError(f"unable to load module spec from {script_path}")
            module = importlib.util.module_from_spec(module_spec)
            module_name = str(module_spec.name or "cookimport_benchmark_cutdown_for_external_ai")
            sys.modules[module_name] = module
            try:
                module_spec.loader.exec_module(module)
            except Exception:
                sys.modules.pop(module_name, None)
                raise
            build_upload_bundle_for_existing_output = getattr(
                module,
                "build_upload_bundle_for_existing_output",
            )
        except Exception as fallback_exc:  # noqa: BLE001
            if not suppress_summary:
                typer.secho(
                    (
                        "Skipped benchmark upload bundle generation: unable to load helper "
                        f"({import_exc}; fallback failed: {fallback_exc})."
                    ),
                    fg=typer.colors.YELLOW,
                )
            return None

    if build_upload_bundle_for_existing_output is None:
        if not suppress_summary:
            typer.secho(
                "Skipped benchmark upload bundle generation: helper loader unavailable.",
                fg=typer.colors.YELLOW,
            )
        return None

    try:
        build_upload_bundle_for_existing_output(
            source_dir=source_root,
            output_dir=output_dir,
            overwrite=True,
            prune_output_dir=False,
            high_level_only=high_level_only,
            target_bundle_size_bytes=target_bundle_size_bytes,
        )
    except Exception as exc:  # noqa: BLE001
        if not suppress_summary:
            typer.secho(
                f"Skipped benchmark upload bundle generation: {exc}",
                fg=typer.colors.YELLOW,
            )
        return None

    if not output_dir.is_dir():
        if not suppress_summary:
            typer.secho(
                "Skipped benchmark upload bundle generation: bundle folder missing after export.",
                fg=typer.colors.YELLOW,
            )
        return None

    output_files = {
        path.name for path in output_dir.iterdir() if path.is_file()
    }
    if output_files != set(BENCHMARK_UPLOAD_BUNDLE_FILE_NAMES):
        if not suppress_summary:
            typer.secho(
                (
                    "Skipped benchmark upload bundle generation: unexpected bundle file set "
                    f"({sorted(output_files)})."
                ),
                fg=typer.colors.YELLOW,
            )
        return None
    return output_dir


def _oracle_upload_output_excerpt(result: OracleUploadResult, *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for block in (result.stdout, result.stderr):
        if not block:
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line:
                lines.append(line)
    if len(lines) <= limit:
        return lines
    return lines[-limit:]


def _print_oracle_upload_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    result: OracleUploadResult,
    success_color: str,
) -> None:
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    if result.review_profile:
        profile_label = result.review_profile_display_name or result.review_profile
        typer.secho(f"Oracle review profile: {profile_label}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle mode: {result.mode}", fg=typer.colors.CYAN)
    if result.oracle_version:
        typer.secho(f"Oracle version: {result.oracle_version}", fg=typer.colors.BRIGHT_BLACK)
    if result.status:
        typer.secho(
            f"Oracle status: {result.status}"
            + (f" ({result.status_reason})" if result.status_reason else ""),
            fg=success_color,
        )
    if result.reattach_command:
        typer.secho(f"Reattach: {result.reattach_command}", fg=typer.colors.BRIGHT_BLACK)
    if result.conversation_url:
        typer.secho(f"Conversation: {result.conversation_url}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle command: {shlex.join(result.command)}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    excerpt = _oracle_upload_output_excerpt(result)
    if excerpt:
        typer.secho("Oracle output:", fg=success_color)
        for line in excerpt:
            typer.echo(f"  {line}")


def _print_oracle_followup_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    source_run: str,
    result: OracleUploadResult,
    workspace: OracleFollowupWorkspace,
    success_color: str,
) -> None:
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle follow-up source run: {source_run}", fg=typer.colors.CYAN)
    if result.status:
        typer.secho(
            f"Oracle follow-up status: {result.status}"
            + (f" ({result.status_reason})" if result.status_reason else ""),
            fg=success_color,
        )
    if result.reattach_command:
        typer.secho(f"Reattach: {result.reattach_command}", fg=typer.colors.BRIGHT_BLACK)
    if result.conversation_url:
        typer.secho(f"Conversation: {result.conversation_url}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up launch dir: {workspace.launch_dir}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Codex handoff: {workspace.handoff_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up request: {workspace.request_json_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Follow-up packet: {workspace.followup_packet_dir}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(f"Turn-2 prompt: {workspace.prompt_path}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle command: {shlex.join(result.command)}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    excerpt = _oracle_upload_output_excerpt(result)
    if excerpt:
        typer.secho("Oracle output:", fg=success_color)
        for line in excerpt:
            typer.echo(f"  {line}")


def _print_background_oracle_upload_summary(
    *,
    target: OracleBenchmarkBundleTarget,
    launch: OracleBackgroundUploadLaunch,
) -> None:
    profile_label = launch.review_profile_display_name or launch.review_profile or "Oracle"
    typer.secho(
        f"{profile_label} Oracle benchmark upload started in background for {target.scope}.",
        fg=typer.colors.GREEN,
    )
    typer.secho(f"Oracle benchmark bundle: {target.bundle_dir}", fg=typer.colors.CYAN)
    if launch.review_profile:
        typer.secho(f"Oracle review profile: {profile_label}", fg=typer.colors.CYAN)
    typer.secho(f"Oracle mode: {launch.mode}", fg=typer.colors.CYAN)
    typer.secho(
        "Oracle browser launcher: auto (visible with display, xvfb otherwise)",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if launch.browser_profile_dir is not None:
        typer.secho(
            f"Oracle browser profile: {launch.browser_profile_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.oracle_version:
        typer.secho(f"Oracle version: {launch.oracle_version}", fg=typer.colors.BRIGHT_BLACK)
    if launch.status:
        typer.secho(
            f"Oracle status: {launch.status}"
            + (f" ({launch.status_reason})" if launch.status_reason else ""),
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.reattach_command:
        typer.secho(
            f"Reattach: {launch.reattach_command}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.conversation_url:
        typer.secho(
            f"Conversation: {launch.conversation_url}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.note:
        transport_message = launch.note.strip()
        typer.secho(
            transport_message,
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.secho(f"Oracle PID: {launch.pid}", fg=typer.colors.BRIGHT_BLACK)
    typer.secho(
        f"Oracle response/log: {launch.log_path}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        f"Watch live: tail -f {launch.log_path}",
        fg=typer.colors.BRIGHT_BLACK,
    )
    if launch.auto_followup_status_path is not None:
        typer.secho(
            f"Oracle auto-follow-up status: {launch.auto_followup_status_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    if launch.auto_followup_log_path is not None:
        typer.secho(
            f"Oracle auto-follow-up log: {launch.auto_followup_log_path}",
            fg=typer.colors.BRIGHT_BLACK,
        )
    typer.secho(
        "When Oracle finishes, open that log file to read the response. If follow-up data is requested, turn 2 will launch automatically.",
        fg=typer.colors.BRIGHT_BLACK,
    )
    typer.secho(
        f"Retry manually: cookimport bench oracle-upload {target.bundle_dir}",
        fg=typer.colors.BRIGHT_BLACK,
    )


def _start_background_oracle_followup_worker(
    *,
    target: OracleBenchmarkBundleTarget,
    launch: OracleBackgroundUploadLaunch,
    model: str | None,
    popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
) -> OracleBackgroundUploadLaunch:
    source_launch_dir = launch.launch_dir
    status_path = source_launch_dir / ORACLE_AUTO_FOLLOWUP_STATUS_NAME
    log_path = source_launch_dir / ORACLE_AUTO_FOLLOWUP_LOG_NAME
    explicit_model = str(model or "").strip() or None
    status_model = explicit_model or str(launch.model or "").strip() or None
    status_path.write_text(
        json.dumps(
            {
                "status": "pending",
                "status_reason": "Background worker has not started yet.",
                "updated_at": dt.datetime.now().strftime("%Y-%m-%d_%H.%M.%S"),
                "bundle_dir": str(target.bundle_dir),
                "source_run": source_launch_dir.name,
                "model": status_model,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    command = [
        sys.executable,
        "-m",
        "cookimport.cli",
        "bench",
        "oracle-autofollowup-worker",
        str(target.bundle_dir),
        "--from-run",
        source_launch_dir.name,
    ]
    if explicit_model is not None:
        command.extend(["--model", explicit_model])
    with log_path.open("w", encoding="utf-8") as log_handle:
        worker = popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(Path.cwd()),
            start_new_session=True,
        )
    return replace(
        launch,
        auto_followup_worker_pid=int(worker.pid),
        auto_followup_log_path=log_path,
        auto_followup_status_path=status_path,
    )


def _start_benchmark_bundle_oracle_upload_background(
    *,
    bundle_dir: Path,
    scope: str,
    mode: str = "browser",
    model: str | None = None,
    review_profile: str = "all",
) -> None:
    require_heavy_test_side_effect_permission("background Oracle benchmark upload")
    try:
        target = resolve_oracle_benchmark_bundle(bundle_dir)
        target = replace(target, scope=scope)
        profiles = resolve_oracle_benchmark_review_profiles(review_profile)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Oracle benchmark upload not started for {bundle_dir}: {exc}",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            f"Retry manually: cookimport bench oracle-upload {bundle_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        return

    for profile in profiles:
        try:
            launch = start_oracle_benchmark_upload_background(
                target=target,
                mode=mode,
                model=model,
                review_profile=profile.profile_id,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Oracle {profile.profile_id} upload not started for {bundle_dir}: {exc}",
                fg=typer.colors.YELLOW,
            )
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            continue
        if launch.mode == "browser":
            try:
                launch = _start_background_oracle_followup_worker(
                    target=target,
                    launch=launch,
                    model=model,
                )
            except Exception as exc:  # noqa: BLE001
                typer.secho(
                    f"Oracle auto-follow-up worker not started for {bundle_dir}: {exc}",
                    fg=typer.colors.YELLOW,
                )
                typer.secho(
                    (
                        "Retry manually after turn 1 finishes: "
                        f"cookimport bench oracle-followup {bundle_dir} --from-run {launch.launch_dir.name}"
                    ),
                    fg=typer.colors.BRIGHT_BLACK,
                )
        _print_background_oracle_upload_summary(target=target, launch=launch)


def _maybe_upload_benchmark_bundle_to_oracle(
    *,
    bundle_dir: Path,
    scope: str,
    mode: str = "browser",
    model: str | None = None,
    review_profile: str = "all",
) -> None:
    try:
        target = resolve_oracle_benchmark_bundle(bundle_dir)
        target = replace(target, scope=scope)
        profiles = resolve_oracle_benchmark_review_profiles(review_profile)
    except Exception as exc:  # noqa: BLE001
        typer.secho(
            f"Oracle benchmark upload skipped for {bundle_dir}: {exc}",
            fg=typer.colors.YELLOW,
        )
        typer.secho(
            f"Retry manually: cookimport bench oracle-upload {bundle_dir}",
            fg=typer.colors.BRIGHT_BLACK,
        )
        return

    had_failure = False
    for profile in profiles:
        try:
            result = run_oracle_benchmark_upload(
                target=target,
                mode=mode,
                model=model,
                review_profile=profile.profile_id,
            )
        except Exception as exc:  # noqa: BLE001
            typer.secho(
                f"Oracle {profile.profile_id} upload skipped for {bundle_dir}: {exc}",
                fg=typer.colors.YELLOW,
            )
            had_failure = True
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            continue

        status_color = typer.colors.GREEN if result.success else typer.colors.YELLOW
        typer.secho(
            (
                f"Oracle {profile.profile_id} upload "
                f"{'completed' if result.success else 'failed'} "
                f"for {target.scope}."
            ),
            fg=status_color,
        )
        _print_oracle_upload_summary(
            target=target,
            result=result,
            success_color=status_color,
        )
        if not result.success:
            had_failure = True
            typer.secho(
                f"Retry manually: cookimport bench oracle-upload {bundle_dir} --profile {profile.profile_id}",
                fg=typer.colors.BRIGHT_BLACK,
            )
            if result.reattach_command:
                typer.secho(
                    f"Reattach directly: {result.reattach_command}",
                    fg=typer.colors.BRIGHT_BLACK,
                )
            else:
                typer.secho(
                    "If the Oracle session detached, inspect it with `oracle status --hours 72`.",
                    fg=typer.colors.BRIGHT_BLACK,
                )
