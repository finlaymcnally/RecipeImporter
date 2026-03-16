"""Tests for the auto-tagging subsystem."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cookimport.llm.codex_farm_runner import CodexFarmRunnerError
from cookimport.llm.fake_codex_farm_runner import FakeCodexFarmRunner
from cookimport.config.run_settings import RunSettings
from cookimport.tagging.catalog import (
    TagCatalog,
    TagCategory,
    Tag,
    load_catalog_from_json,
    export_catalog_to_json,
    _build_catalog,
)
from cookimport.tagging.codex_farm_tags_provider import (
    CodexFarmTagsJob,
    TagCandidate,
    run_codex_farm_tags_pass,
)
from cookimport.tagging.engine import TagSuggestion, suggest_tags_deterministic
from cookimport.tagging.eval import evaluate, EvalResult, format_eval_report
from cookimport.tagging.llm_second_pass import (
    LlmSecondPassConfig,
    LlmSecondPassRequest,
    suggest_tags_with_llm_batch,
)
from cookimport.tagging.orchestrator import suggest_tags_for_draft_files
from cookimport.tagging.orchestrator import run_stage_tagging_pass
from cookimport.tagging.signals import (
    RecipeSignalPack,
    normalize_text_for_matching,
    signals_from_dict,
)
from cookimport.tagging.render import render_suggestions_text, serialize_suggestions_json
from tests.paths import TAGGING_GOLD_DIR as TESTS_TAGGING_GOLD_DIR

GOLD_DIR = TESTS_TAGGING_GOLD_DIR
CATALOG_PATH = GOLD_DIR / "tag_catalog.small.json"
FIXTURES_PATH = GOLD_DIR / "fixtures.json"
GOLD_LABELS_PATH = GOLD_DIR / "gold_labels.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def catalog() -> TagCatalog:
    return load_catalog_from_json(CATALOG_PATH)


@pytest.fixture
def fixtures() -> dict:
    with open(FIXTURES_PATH) as f:
        return json.load(f)


@pytest.fixture
def gold_labels() -> dict[str, list[str]]:
    with open(GOLD_LABELS_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Unit tests: catalog
# ---------------------------------------------------------------------------

class TestCatalog:
    def test_load_from_json(self, catalog: TagCatalog):
        assert catalog.category_count == 8
        assert catalog.tag_count == 30

    def test_get_tag_id(self, catalog: TagCatalog):
        assert catalog.get_tag_id("chicken") == "tag-chicken"
        assert catalog.get_tag_id("nonexistent") is None

    def test_category_key_for_tag(self, catalog: TagCatalog):
        assert catalog.category_key_for_tag("chicken") == "main-protein"
        assert catalog.category_key_for_tag("bake") == "cooking-method"

    def test_export_roundtrip(self, catalog: TagCatalog, tmp_path: Path):
        out = tmp_path / "exported.json"
        fp = export_catalog_to_json(catalog, out)
        assert out.exists()
        assert len(fp) == 64  # SHA-256 hex

        reloaded = load_catalog_from_json(out)
        assert reloaded.category_count == catalog.category_count
        assert reloaded.tag_count == catalog.tag_count


# ---------------------------------------------------------------------------
# Unit tests: signals
# ---------------------------------------------------------------------------

class TestSignals:
    def test_normalize_text(self):
        assert normalize_text_for_matching("Café & Résumé!") == "cafe resume"
        assert normalize_text_for_matching("  Hello   World  ") == "hello world"
        assert normalize_text_for_matching("") == ""

    def test_signals_from_dict(self):
        data = {
            "title": "Test Recipe",
            "ingredients": ["1 cup flour", "2 eggs"],
            "instructions": ["Mix well."],
            "total_time_minutes": 15,
        }
        signals = signals_from_dict(data)
        assert signals.title == "Test Recipe"
        assert len(signals.ingredients) == 2
        assert signals.total_time_minutes == 15


# ---------------------------------------------------------------------------
# Unit tests: scoring engine
# ---------------------------------------------------------------------------

class TestEngine:
    def test_instant_pot_chicken(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["instant_pot_chicken_chili"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}

        assert "instant-pot" in tag_keys, f"Expected instant-pot, got {tag_keys}"
        assert "chicken" in tag_keys, f"Expected chicken, got {tag_keys}"
        assert "pressure-cook" in tag_keys, f"Expected pressure-cook, got {tag_keys}"

    def test_slow_cooker_beef_stew(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["slow_cooker_beef_stew"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}

        assert "slow-cooker" in tag_keys
        assert "beef" in tag_keys
        assert "stew" in tag_keys
        assert "hands-off-friendly" in tag_keys

    def test_quick_pasta(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["quick_pasta_aglio_olio"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}

        assert "quick" in tag_keys
        assert "pasta-noodles" in tag_keys
        assert "saute" in tag_keys

    def test_single_category_policy(self, catalog: TagCatalog):
        """main-protein is single: should only keep the top tag."""
        signals = signals_from_dict({
            "title": "Chicken and Beef Burrito",
            "ingredients": ["1 lb chicken breast", "1 lb ground beef", "tortillas"],
            "instructions": ["Cook the chicken.", "Cook the beef.", "Assemble burritos."],
        })
        suggestions = suggest_tags_deterministic(catalog, signals)
        protein_tags = [s for s in suggestions if s.category_key == "main-protein"]
        assert len(protein_tags) <= 1, f"Single policy violated: {[s.tag_key for s in protein_tags]}"

    def test_no_cook_salad(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["no_cook_summer_salad"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}

        assert "no-cook" in tag_keys
        assert "salad" in tag_keys
        assert "quick" in tag_keys

    def test_dutch_oven_pot_roast(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["dutch_oven_pot_roast"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}

        assert "dutch-oven" in tag_keys
        assert "beef" in tag_keys
        assert "simmer" in tag_keys

    def test_missing_tag_in_catalog_skipped(self):
        """Rules for tags not in catalog should be silently skipped."""
        catalog = _build_catalog(
            [TagCategory(id="cat1", key_norm="test", display_name="Test")],
            [Tag(id="t1", key_norm="chicken", display_name="Chicken", category_id="cat1")],
        )
        signals = signals_from_dict({
            "title": "Instant Pot Chicken",
            "ingredients": ["chicken"],
            "instructions": ["Pressure cook."],
        })
        suggestions = suggest_tags_deterministic(catalog, signals)
        tag_keys = {s.tag_key for s in suggestions}
        # instant-pot is NOT in this catalog, so should not appear
        assert "instant-pot" not in tag_keys
        assert "chicken" in tag_keys

    def test_evidence_present(self, catalog: TagCatalog, fixtures: dict):
        signals = signals_from_dict(fixtures["instant_pot_chicken_chili"])
        suggestions = suggest_tags_deterministic(catalog, signals)
        for s in suggestions:
            assert len(s.evidence) > 0, f"No evidence for {s.tag_key}"

    def test_deterministic_same_input(self, catalog: TagCatalog, fixtures: dict):
        """Same inputs + same catalog = identical outputs."""
        signals = signals_from_dict(fixtures["grilled_salmon_rice_bowl"])
        run1 = suggest_tags_deterministic(catalog, signals)
        run2 = suggest_tags_deterministic(catalog, signals)
        assert [(s.tag_key, s.confidence) for s in run1] == [(s.tag_key, s.confidence) for s in run2]


# ---------------------------------------------------------------------------
# Unit tests: rendering
# ---------------------------------------------------------------------------

class TestRender:
    def test_render_text(self):
        suggestions = [
            TagSuggestion(tag_key="chicken", category_key="main-protein", confidence=0.7, evidence=["in ingredients"]),
        ]
        text = render_suggestions_text("Test Recipe", suggestions, explain=True)
        assert "chicken" in text
        assert "0.70" in text
        assert "in ingredients" in text

    def test_serialize_json(self):
        suggestions = [
            TagSuggestion(tag_key="bake", category_key="cooking-method", confidence=0.6, evidence=["oven"]),
        ]
        data = serialize_suggestions_json(suggestions, title="Test")
        assert data["title"] == "Test"
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["tag_key"] == "bake"


# ---------------------------------------------------------------------------
# Gold set regression test
# ---------------------------------------------------------------------------

class TestGoldSet:
    def test_gold_set_precision(self, catalog: TagCatalog, fixtures: dict, gold_labels: dict):
        """Protect single-category precision and overall quality."""
        predictions: dict[str, list[TagSuggestion]] = {}
        for fixture_id, fixture_data in fixtures.items():
            signals = signals_from_dict(fixture_data)
            suggestions = suggest_tags_deterministic(catalog, signals)
            predictions[fixture_id] = suggestions

        result = evaluate(catalog, predictions, gold_labels)
        report = format_eval_report(result)

        # Overall precision must stay above 70% (conservative bar)
        assert result.overall_precision >= 0.70, (
            f"Overall precision dropped to {result.overall_precision:.2%}. "
            f"Investigate false positives.\n{report}"
        )

        # Single-category precision must stay above 80%
        for cat_key in ("main-protein", "main-carb"):
            if cat_key in result.per_category:
                m = result.per_category[cat_key]
                assert m.precision >= 0.80, (
                    f"{cat_key} precision dropped to {m.precision:.2%}. "
                    f"FP={m.false_positives}\n{report}"
                )

    def test_gold_set_recall(self, catalog: TagCatalog, fixtures: dict, gold_labels: dict):
        """Recall should be reasonable (>= 50%)."""
        predictions: dict[str, list[TagSuggestion]] = {}
        for fixture_id, fixture_data in fixtures.items():
            signals = signals_from_dict(fixture_data)
            suggestions = suggest_tags_deterministic(catalog, signals)
            predictions[fixture_id] = suggestions

        result = evaluate(catalog, predictions, gold_labels)
        assert result.overall_recall >= 0.50, (
            f"Overall recall dropped to {result.overall_recall:.2%}. "
            f"Investigate false negatives."
        )


class _AlwaysFailRunner:
    def run_pipeline(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise CodexFarmRunnerError("synthetic failure")


class TestLlmTagPass:
    def test_codex_farm_provider_rejects_tag_outside_shortlist(self, catalog: TagCatalog):
        signals = signals_from_dict(
            {
                "recipe_id": "r-test",
                "title": "Beef stew",
                "ingredients": ["beef chuck"],
                "instructions": ["Simmer until tender."],
            }
        )
        job = CodexFarmTagsJob(
            recipe_key="r-test",
            recipe_id="r-test",
            signals=signals,
            missing_categories=("main-protein",),
            candidates_by_category={
                "main-protein": (TagCandidate(tag_key_norm="chicken", display_name="Chicken"),)
            },
        )

        runner = FakeCodexFarmRunner(
            output_builders={
                "recipe.tags.v1": lambda payload: {
                    "bundle_version": "1",
                    "recipe_id": payload["recipe_id"],
                    "selected_tags": [
                        {
                            "tag_key_norm": "beef",
                            "category_key_norm": "main-protein",
                            "confidence": 0.82,
                            "evidence": "mentions beef",
                        }
                    ],
                    "new_tag_proposals": [],
                }
            }
        )

        result = run_codex_farm_tags_pass(
            jobs=[job],
            catalog=catalog,
            pipeline_id="recipe.tags.v1",
            runner=runner,
        )

        assert result.suggestions_by_recipe["r-test"] == []
        assert result.llm_validation["selected_entries_dropped"] == 1
        assert result.llm_validation["drop_reasons"]["tag_not_in_shortlist"] == 1
        assert "output_schema_path" in result.llm_report
        assert "process_run" in result.llm_report
        assert result.llm_report["process_run"]["pipeline_id"] == "recipe.tags.v1"
        assert "telemetry_report" in result.llm_report["process_run"]
        assert "autotune_report" in result.llm_report["process_run"]

    def test_llm_second_pass_fallback_mode_returns_deterministic_only(self, catalog: TagCatalog):
        request = LlmSecondPassRequest(
            recipe_key="r0",
            signals=signals_from_dict(
                {
                    "recipe_id": "r0",
                    "title": "Mystery Dish",
                    "ingredients": [],
                    "instructions": [],
                }
            ),
            missing_categories=("main-protein",),
        )
        result = suggest_tags_with_llm_batch(
            [request],
            catalog,
            config=LlmSecondPassConfig(
                enabled=True,
                runner=_AlwaysFailRunner(),
                failure_mode="fallback",
            ),
        )

        assert result.suggestions_by_recipe == {}
        assert result.llm_report.get("fallbackApplied") is True
        assert result.llm_report.get("fatalError")

    def test_suggest_tags_for_drafts_uses_fake_runner(self, catalog: TagCatalog, tmp_path: Path):
        draft_path = tmp_path / "r0.json"
        draft_path.write_text(
            json.dumps(
                {
                    "recipe": {"title": "Mystery Dish", "description": "", "notes": ""},
                    "steps": [],
                }
            ),
            encoding="utf-8",
        )

        report_path = tmp_path / "tags" / "tagging_report.json"
        result = suggest_tags_for_draft_files(
            draft_files=[draft_path],
            catalog=catalog,
            catalog_fingerprint="test-fingerprint",
            per_recipe_out_dir=tmp_path / "tags",
            report_path=report_path,
            llm_config=LlmSecondPassConfig(
                enabled=True,
                pipeline_id="recipe.tags.v1",
                runner=FakeCodexFarmRunner(),
                failure_mode="fail",
            ),
        )

        assert len(result.records) == 1
        assert report_path.exists()
        assert (tmp_path / "tags" / "r0.tags.json").exists()
        assert any(suggestion.source == "llm" for suggestion in result.records[0].suggestions)

    def test_stage_tagging_pass_writes_tags_and_raw_io(self, tmp_path: Path):
        run_root = tmp_path / "2026-02-25_12.00.00"
        workbook_dir = run_root / "final drafts" / "book-a"
        workbook_dir.mkdir(parents=True, exist_ok=True)
        (workbook_dir / "r0.json").write_text(
            json.dumps(
                {
                    "recipe": {"title": "Mystery Dish", "description": "", "notes": ""},
                    "steps": [],
                }
            ),
            encoding="utf-8",
        )

        settings = RunSettings.from_dict(
            {
                "llm_tags_pipeline": "codex-farm-tags-v1",
                "codex_farm_failure_mode": "fail",
                "tag_catalog_json": str(CATALOG_PATH),
            },
            warn_context="test stage tags",
        )
        result = run_stage_tagging_pass(
            run_root=run_root,
            run_settings=settings,
            llm_runner=FakeCodexFarmRunner(),
        )

        assert result.enabled is True
        assert (run_root / "tags" / "book-a" / "r0.tags.json").exists()
        assert (run_root / "tags" / "book-a" / "tagging_report.json").exists()
        assert (run_root / "tags" / "tags_index.json").exists()
        assert (run_root / "raw" / "llm" / "book-a" / "tags" / "in").exists()
        assert (run_root / "raw" / "llm" / "book-a" / "tags" / "out").exists()
        assert (run_root / "raw" / "llm" / "book-a" / "tags_manifest.json").exists()

    def test_stage_tagging_pass_projects_tags_into_final_and_intermediate_outputs(
        self, tmp_path: Path
    ):
        run_root = tmp_path / "2026-02-25_12.00.00"
        final_dir = run_root / "final drafts" / "book-a"
        intermediate_dir = run_root / "intermediate drafts" / "book-a"
        final_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        (final_dir / "r0.json").write_text(
            json.dumps(
                {
                    "schema_v": 1,
                    "source": "book-a.txt",
                    "recipe": {"title": "Mystery Dish", "description": "", "notes": None},
                    "steps": [],
                }
            ),
            encoding="utf-8",
        )
        (intermediate_dir / "r0.jsonld").write_text(
            json.dumps(
                {
                    "@context": ["https://schema.org"],
                    "@type": "Recipe",
                    "name": "Mystery Dish",
                }
            ),
            encoding="utf-8",
        )

        settings = RunSettings.from_dict(
            {
                "llm_tags_pipeline": "codex-farm-tags-v1",
                "codex_farm_failure_mode": "fail",
                "tag_catalog_json": str(CATALOG_PATH),
            },
            warn_context="test stage tags projection",
        )
        run_stage_tagging_pass(
            run_root=run_root,
            run_settings=settings,
            llm_runner=FakeCodexFarmRunner(),
        )

        tags_payload = json.loads(
            (run_root / "tags" / "book-a" / "r0.tags.json").read_text(encoding="utf-8")
        )
        expected_tags = [row["tag_key"] for row in tags_payload["suggestions"]]
        final_payload = json.loads((final_dir / "r0.json").read_text(encoding="utf-8"))
        intermediate_payload = json.loads(
            (intermediate_dir / "r0.jsonld").read_text(encoding="utf-8")
        )

        assert final_payload["recipe"]["tags"] == expected_tags
        assert intermediate_payload["keywords"] == ", ".join(expected_tags)
