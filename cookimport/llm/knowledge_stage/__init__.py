from __future__ import annotations

__all__ = [
    "CodexFarmNonrecipeFinalizeResult",
    "run_codex_farm_nonrecipe_finalize",
    "_preflight_knowledge_shard",
]


def __getattr__(name: str):
    if name == "CodexFarmNonrecipeFinalizeResult":
        from .planning import CodexFarmNonrecipeFinalizeResult

        return CodexFarmNonrecipeFinalizeResult
    if name == "run_codex_farm_nonrecipe_finalize":
        from .runtime import run_codex_farm_nonrecipe_finalize

        return run_codex_farm_nonrecipe_finalize
    if name == "_preflight_knowledge_shard":
        from .recovery import _preflight_knowledge_shard

        return _preflight_knowledge_shard
    raise AttributeError(name)
