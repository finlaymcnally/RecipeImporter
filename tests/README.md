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

On failures, pytest prints short hints to matching `docs/*_log.md` files.
For full traceback/details, rerun with:

```bash
pytest -vv --tb=short --show-capture=all --assert=rewrite <failing_test>
```
