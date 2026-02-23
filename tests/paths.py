from __future__ import annotations

from pathlib import Path


TESTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent
FIXTURES_DIR = TESTS_ROOT / "fixtures"
TAGGING_GOLD_DIR = TESTS_ROOT / "tagging_gold"
DOCS_EXAMPLES_DIR = REPO_ROOT / "docs" / "template" / "examples"
