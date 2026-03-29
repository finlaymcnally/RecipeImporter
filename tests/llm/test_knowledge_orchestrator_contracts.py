from __future__ import annotations

from pathlib import Path

from cookimport.llm.codex_farm_knowledge_orchestrator import _preflight_knowledge_shard
from cookimport.llm.knowledge_stage.recovery import (
    _build_knowledge_workspace_worker_prompt,
    _write_knowledge_worker_hint,
)
from cookimport.llm.phase_worker_runtime import ShardManifestEntryV1


def test_preflight_knowledge_shard_accepts_shard_payload() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [{"i": 4, "t": "Whisk constantly."}],
        },
    )

    assert _preflight_knowledge_shard(shard) is None


def test_preflight_knowledge_shard_rejects_missing_bundle_id() -> None:
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={"v": "1", "b": [{"i": 4, "t": "Whisk constantly."}]},
    )

    assert _preflight_knowledge_shard(shard) == {
        "reason_code": "preflight_invalid_shard_payload",
        "reason_detail": "knowledge shard is missing `bid`",
    }


def test_worker_prompt_describes_phase_contract() -> None:
    prompt = _build_knowledge_workspace_worker_prompt(
        shards=[
            ShardManifestEntryV1(
                shard_id="book.ks0000.nr",
                owned_ids=("book.ks0000.nr",),
                input_payload={
                    "v": "1",
                    "bid": "book.ks0000.nr",
                    "b": [{"i": 4, "t": "Whisk constantly."}],
                },
                input_text=None,
                metadata={},
            )
        ]
    )

    assert "CURRENT_PHASE.md" in prompt
    assert "Pass 1 is block-local classification only" in prompt
    assert "Pass 2 runs only after Pass 1 installs" in prompt
    assert "python3 tools/knowledge_worker.py check-phase" in prompt
    assert "python3 tools/knowledge_worker.py install-phase" in prompt
    assert "If `hints/<shard_id>.md` exists, open it before `in/<shard_id>.json`." in prompt
    assert "`examples/` as calibration only" in prompt
    assert "snippets" not in prompt


def test_knowledge_worker_hint_includes_profile_examples_and_attention_rows(
    tmp_path: Path,
) -> None:
    hint_path = tmp_path / "hint.md"
    shard = ShardManifestEntryV1(
        shard_id="book.ks0000.nr",
        owned_ids=("book.ks0000.nr",),
        input_payload={
            "v": "1",
            "bid": "book.ks0000.nr",
            "b": [
                {"i": 4, "t": "WHAT IS ACID?", "hl": 2},
                {
                    "i": 18,
                    "t": "Acid brightens food because it balances richness and sharpens flavor perception across the whole dish.",
                },
                {
                    "i": 40,
                    "t": "Conversion table row",
                    "th": {"id": "tbl-1", "c": "Conversions", "r": 0},
                },
            ],
            "g": {"r": [2, 3]},
        },
        input_text=None,
        metadata={},
    )

    _write_knowledge_worker_hint(path=hint_path, shard=shard)
    rendered = hint_path.read_text(encoding="utf-8")

    assert "## Shard profile" in rendered
    assert "## Decision policy" in rendered
    assert "## Shard examples" in rendered
    assert "## Attention rows" in rendered
    assert "`examples/valid_heading_with_useful_body_packet.json`" in rendered
    assert "gap_from_prev=14" in rendered
    assert "table_hint" in rendered
