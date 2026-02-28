from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Literal

ExecutorBackend = Literal["process", "thread", "serial"]
ExecutorMessageFactory = Callable[[BaseException], str]
ExecutorFactory = Callable[[int], Executor]


@dataclass(frozen=True)
class ProcessThreadExecutorResolution:
    backend: ExecutorBackend
    executor: Executor | None
    messages: tuple[str, ...] = ()


def resolve_process_thread_executor(
    *,
    max_workers: int,
    process_unavailable_message: ExecutorMessageFactory | None,
    thread_unavailable_message: ExecutorMessageFactory | None,
    process_executor_factory: ExecutorFactory | None = None,
    thread_executor_factory: ExecutorFactory | None = None,
) -> ProcessThreadExecutorResolution:
    resolved_workers = max(1, int(max_workers))
    effective_process_executor_factory = (
        process_executor_factory or ProcessPoolExecutor
    )
    effective_thread_executor_factory = (
        thread_executor_factory or ThreadPoolExecutor
    )
    try:
        executor = effective_process_executor_factory(resolved_workers)
    except (PermissionError, OSError) as process_exc:
        messages: list[str] = []
        if process_unavailable_message is not None:
            message = str(process_unavailable_message(process_exc) or "").strip()
            if message:
                messages.append(message)
        try:
            executor = effective_thread_executor_factory(resolved_workers)
        except Exception as thread_exc:  # noqa: BLE001
            if thread_unavailable_message is not None:
                message = str(thread_unavailable_message(thread_exc) or "").strip()
                if message:
                    messages.append(message)
            return ProcessThreadExecutorResolution(
                backend="serial",
                executor=None,
                messages=tuple(messages),
            )
        return ProcessThreadExecutorResolution(
            backend="thread",
            executor=executor,
            messages=tuple(messages),
        )
    return ProcessThreadExecutorResolution(backend="process", executor=executor)


def shutdown_executor(
    executor: Executor | None,
    *,
    wait: bool = True,
    cancel_futures: bool = False,
) -> None:
    if executor is None:
        return
    shutdown_fn = getattr(executor, "shutdown", None)
    if not callable(shutdown_fn):
        return
    try:
        shutdown_fn(wait=wait, cancel_futures=cancel_futures)
    except TypeError:
        shutdown_fn(wait=wait)
