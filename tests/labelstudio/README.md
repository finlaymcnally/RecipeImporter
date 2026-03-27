# Label Studio Tests

`benchmark_helper_support.py` keeps shared benchmark-helper imports and helper writers.
It also forces the Oracle test lane (`ORACLE_TEST_MODEL`), still stubs the lowest-level heavy helpers as a backstop, and now exposes lightweight single-book and single-profile benchmark publishers for routine helper tests. Use those fake publishers first; save real heavy helper opt-in for the small tests marked `heavy_side_effects`.
Use the focused `test_labelstudio_benchmark_helpers_*.py` files for targeted runs instead of giant mixed modules.
Fallback helper-path regressions for single-book starter-pack and upload-bundle loading are guarded in `test_labelstudio_benchmark_helpers_single_book_artifacts.py`.
Routing-only interactive benchmark tests should stub `_interactive_single_book_benchmark(...)`; the real single-book helper coverage lives in `test_labelstudio_benchmark_helpers_single_book_run.py`.
