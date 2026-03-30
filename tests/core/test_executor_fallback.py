from __future__ import annotations

from cookimport.core import executor_fallback


def test_preferred_multiprocessing_context_uses_spawn_for_multithreaded_fork(
    monkeypatch,
) -> None:
    sentinel = object()

    monkeypatch.setattr(executor_fallback.threading, "active_count", lambda: 2)
    monkeypatch.setattr(
        executor_fallback.multiprocessing,
        "get_start_method",
        lambda allow_none=True: "fork",
    )
    monkeypatch.setattr(
        executor_fallback.multiprocessing,
        "get_all_start_methods",
        lambda: ["fork", "spawn"],
    )
    monkeypatch.setattr(
        executor_fallback.multiprocessing,
        "get_context",
        lambda method: sentinel if method == "spawn" else None,
    )

    assert executor_fallback.preferred_multiprocessing_context() is sentinel


def test_preferred_multiprocessing_context_skips_spawn_for_single_thread(
    monkeypatch,
) -> None:
    monkeypatch.setattr(executor_fallback.threading, "active_count", lambda: 1)

    assert executor_fallback.preferred_multiprocessing_context() is None


def test_create_process_pool_executor_passes_spawn_context(monkeypatch) -> None:
    sentinel = object()
    captured: dict[str, object] = {}

    def _fake_process_pool_executor(max_workers, mp_context=None):
        captured["max_workers"] = max_workers
        captured["mp_context"] = mp_context
        return sentinel

    monkeypatch.setattr(
        executor_fallback,
        "preferred_multiprocessing_context",
        lambda: "spawn-context",
    )
    monkeypatch.setattr(
        executor_fallback,
        "ProcessPoolExecutor",
        _fake_process_pool_executor,
    )

    assert executor_fallback.create_process_pool_executor(3) is sentinel
    assert captured == {
        "max_workers": 3,
        "mp_context": "spawn-context",
    }


def test_create_sync_manager_uses_preferred_context(monkeypatch) -> None:
    sentinel = object()

    class _FakeContext:
        def Manager(self):
            return sentinel

    monkeypatch.setattr(
        executor_fallback,
        "preferred_multiprocessing_context",
        lambda: _FakeContext(),
    )

    assert executor_fallback.create_sync_manager() is sentinel
