from __future__ import annotations

import json
from pathlib import Path

from cookimport.config.run_settings import RunSettings
from tests.paths import REPO_ROOT as TESTS_REPO_ROOT


def test_local_recipe_pipeline_pack_has_editable_prompt_files() -> None:
    repo_root = TESTS_REPO_ROOT
    pack_root = repo_root / "llm_pipelines"
    pipelines_dir = pack_root / "pipelines"

    pipeline_ids = (
        "recipe.correction.compact.v1",
        RunSettings().codex_farm_pipeline_knowledge,
        RunSettings().codex_farm_pipeline_tags,
    )

    for pipeline_id in pipeline_ids:
        pipeline_path = pipelines_dir / f"{pipeline_id}.json"
        assert pipeline_path.exists(), f"Missing pipeline spec: {pipeline_path}"

        payload = json.loads(pipeline_path.read_text(encoding="utf-8"))
        assert payload.get("pipeline_id") == pipeline_id
        assert payload.get("prompt_input_mode") == "inline"

        prompt_rel = payload.get("prompt_template_path")
        schema_rel = payload.get("output_schema_path")
        assert isinstance(prompt_rel, str) and prompt_rel.strip()
        assert isinstance(schema_rel, str) and schema_rel.strip()

        prompt_path = pack_root / prompt_rel
        schema_path = pack_root / schema_rel
        assert prompt_path.exists(), f"Missing prompt template: {prompt_path}"
        assert schema_path.exists(), f"Missing output schema: {schema_path}"

        prompt_text = prompt_path.read_text(encoding="utf-8")
        assert "{{INPUT_TEXT}}" in prompt_text
