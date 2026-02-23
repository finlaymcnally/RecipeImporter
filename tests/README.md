# Tests Quick Guide

The repo now tags tests by domain automatically in `tests/conftest.py`.
Use marker filters so AI runs only what is needed.

## Folder Layout

```text
tests/
  analytics/
  bench/
  cli/
  core/
  ingestion/
  labelstudio/
  llm/
  parsing/
  staging/
  tagging/
```

## Minimal Runs

```bash
. .venv/bin/activate
pytest -m smoke
pytest -m "not slow"
pytest tests/parsing
pytest tests/ingestion
pytest tests/labelstudio
pytest -m ingestion
pytest -m parsing
pytest -m staging
pytest -m cli
pytest -m labelstudio
pytest -m bench
pytest -m analytics
pytest -m tagging
pytest -m llm
```

Default output is intentionally compact, and this is enforced in `tests/conftest.py`
even if someone passes `-o addopts=''` by hand.

On failures, pytest prints short hints to matching `docs/*_log.md` files.
For full traceback/details, rerun with:

```bash
COOKIMPORT_PYTEST_VERBOSE_OUTPUT=1 pytest -o addopts='' -vv --tb=short --show-capture=all --assert=rewrite <failing_test>
```
