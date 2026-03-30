from __future__ import annotations

import multiprocessing
import threading
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


def _effective_start_method() -> str | None:
    try:
        start_method = multiprocessing.get_start_method(allow_none=True)
    except TypeError:
        start_method = multiprocessing.get_start_method()
    if start_method:
        return str(start_method)
    try:
        start_methods = multiprocessing.get_all_start_methods()
    except Exception:  # noqa: BLE001
        return None
    if not start_methods:
        return None
    return str(start_methods[0])


def preferred_multiprocessing_context():
    """Use spawn when a multithreaded parent would otherwise fork on Python 3.12+."""
    try:
        if threading.active_count() <= 1:
            return None
    except Exception:  # noqa: BLE001
        return None
    if _effective_start_method() != "fork":
        return None
    try:
        available_methods = multiprocessing.get_all_start_methods()
    except Exception:  # noqa: BLE001
        return None
    if "spawn" not in available_methods:
        return None
    try:
        return multiprocessing.get_context("spawn")
    except Exception:  # noqa: BLE001
        return None


def create_process_pool_executor(max_workers: int) -> ProcessPoolExecutor:
    context = preferred_multiprocessing_context()
    if context is None:
        return ProcessPoolExecutor(max_workers=max_workers)
    return ProcessPoolExecutor(max_workers=max_workers, mp_context=context)


def create_sync_manager():
    context = preferred_multiprocessing_context()
    if context is None:
        return multiprocessing.Manager()
    return context.Manager()


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
        process_executor_factory or create_process_pool_executor
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
