from __future__ import annotations

import tests.analytics.stats_dashboard_support as _support

# Reuse shared imports/helpers from the local support module.
globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


class TestSchema:
    def test_dashboard_data_minimal(self):
        d = DashboardData()
        assert d.schema_version == "14"
        assert d.stage_records == []
        assert d.benchmark_records == []

    def test_stage_record_from_dict(self):
        r = StageRecord(
            file_name="test.xlsx",
            recipes=10,
            total_seconds=5.0,
            per_recipe_seconds=0.5,
        )
        assert r.run_category == RunCategory.stage_import
        assert r.per_recipe_seconds == 0.5

    def test_benchmark_record_f1(self):
        r = BenchmarkRecord(precision=0.5, recall=0.5)
        # F1 is not computed automatically in the schema; the collector does it
        assert r.f1 is None

    def test_optional_fields_are_none(self):
        r = StageRecord(file_name="x")
        assert r.total_seconds is None
        assert r.recipes is None
        assert r.warnings_count is None
        assert r.run_config is None
        assert r.run_config_warning is None
