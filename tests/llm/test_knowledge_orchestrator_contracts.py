from __future__ import annotations

from pathlib import Path

from cookimport.llm.codex_farm_knowledge_orchestrator import _preflight_knowledge_shard
from cookimport.llm.knowledge_stage import _shared as knowledge_stage_shared
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
    assert (
        "Start by opening `worker_manifest.json`, then `CURRENT_PHASE.md`."
        in prompt
    )
    assert (
        "Then open the active work ledger named there and `hints/<shard_id>.md`."
        in prompt
    )
    assert (
        "Open `in/<shard_id>.json` only when the phase brief, feedback, hint, and active work ledger are still insufficient."
        in prompt
    )
    assert "Pass 1 is your first-authority semantic judgment" in prompt
    assert "The repo does not know the `knowledge` versus `other` answer ahead of time." in prompt
    assert "Pass 2 runs only after Pass 1 installs, and it continues from the accepted Pass 1 knowledge rows" in prompt
    assert "assign a non-empty local `group_key` plus `topic_label`" in prompt
    assert "python3 tools/knowledge_worker.py check-phase" in prompt
    assert "python3 tools/knowledge_worker.py install-phase" in prompt
    assert (
        "Do not reconstruct `packet_id`, `block_decisions`, or `idea_groups` by hand."
        in prompt
    )
    assert (
        "`OUTPUT_CONTRACT.md`, `examples/`, and `tools/knowledge_worker.py` are fallback contract/debug surfaces"
        in prompt
    )
    assert "Top level keys: `packet_id`, `block_decisions`, `idea_groups`." not in prompt
    assert "snippets" not in prompt


def test_knowledge_worker_hint_stays_compact_and_keeps_high_signal_sections(
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
    assert "## Shard interpretation" in rendered
    assert "## Decision policy" in rendered
    assert "## Shard examples" in rendered
    assert "## Attention rows" in rendered
    assert "## How to use this task" not in rendered
    assert "## Packet summary" not in rendered
    assert "`examples/valid_heading_with_useful_body_packet.json`" in rendered
    assert "Nearby recipe guardrail block indices: `2, 3`." in rendered
    assert "gap_from_prev=14" in rendered
    assert "table_hint" in rendered
    assert rendered.count("## ") == 5


def test_knowledge_stage_shared_no_longer_imports_legacy_workspace_helper_surface() -> None:
    shared_source = Path(knowledge_stage_shared.__file__).read_text(encoding="utf-8")

    assert "knowledge_workspace_tools" not in shared_source
