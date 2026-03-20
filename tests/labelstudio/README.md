# Label Studio Tests

`benchmark_helper_support.py` keeps shared benchmark-helper imports and helper writers.
It also forces the Oracle test lane (`ORACLE_TEST_MODEL`) and stamps helper-origin benchmark uploads as `TEST HELPER ONLY`, so any real chats created by helper tests are obviously disposable and stay off the genuine Pro lane.
Use the focused `test_labelstudio_benchmark_helpers_*.py` files for targeted runs instead of giant mixed modules.
Routing-only interactive benchmark tests should stub `_interactive_single_offline_benchmark(...)`; the real single-offline helper coverage lives in `test_labelstudio_benchmark_helpers_single_offline_run.py`.
