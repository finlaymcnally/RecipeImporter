# Label Studio Tests

`benchmark_helper_support.py` keeps shared benchmark-helper imports and helper writers.
It also forces the Oracle test lane (`ORACLE_TEST_MODEL`) and stubs `_start_benchmark_bundle_oracle_upload_background(...)` by default, so routine benchmark-helper tests do not open live Oracle / ChatGPT browser chats. Tests that need launch assertions should override that stub explicitly.
Use the focused `test_labelstudio_benchmark_helpers_*.py` files for targeted runs instead of giant mixed modules.
Routing-only interactive benchmark tests should stub `_interactive_single_book_benchmark(...)`; the real single-book helper coverage lives in `test_labelstudio_benchmark_helpers_single_book_run.py`.
