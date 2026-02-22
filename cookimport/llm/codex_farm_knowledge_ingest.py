from __future__ import annotations

import json
from pathlib import Path

from .codex_farm_knowledge_models import Pass4KnowledgeOutputV1


def read_pass4_knowledge_outputs(out_dir: Path) -> dict[str, Pass4KnowledgeOutputV1]:
    """Load and validate all pass4 knowledge output bundles from a directory."""
    outputs: dict[str, Pass4KnowledgeOutputV1] = {}
    for path in sorted(out_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid JSON in pass4 output bundle {path}: {exc}") from exc
        try:
            parsed = Pass4KnowledgeOutputV1.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Invalid pass4 output bundle {path}: {exc}") from exc
        if parsed.chunk_id in outputs:
            raise ValueError(
                "Duplicate chunk_id in pass4 outputs: "
                f"{parsed.chunk_id!r} (file={path.name})."
            )
        outputs[parsed.chunk_id] = parsed
    return outputs
