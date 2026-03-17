from __future__ import annotations

import json
from pathlib import Path

from .codex_farm_knowledge_models import KnowledgeBundleOutputV2, KnowledgeChunkResultV2


def read_knowledge_outputs(out_dir: Path) -> dict[str, KnowledgeChunkResultV2]:
    """Load and validate all knowledge-stage output bundles from a directory."""
    outputs: dict[str, KnowledgeChunkResultV2] = {}
    for path in sorted(out_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid JSON in knowledge output bundle {path}: {exc}") from exc
        try:
            parsed = KnowledgeBundleOutputV2.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid knowledge output bundle {path}: {exc}") from exc
        for chunk_result in parsed.chunk_results:
            if chunk_result.chunk_id in outputs:
                raise ValueError(
                    "Duplicate chunk_id in knowledge outputs: "
                    f"{chunk_result.chunk_id!r} (file={path.name})."
                )
            outputs[chunk_result.chunk_id] = chunk_result
    return outputs
