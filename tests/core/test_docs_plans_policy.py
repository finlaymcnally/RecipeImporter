from __future__ import annotations

from tests.paths import REPO_ROOT


def test_docs_plans_contains_only_markdown_files() -> None:
    plans_dir = REPO_ROOT / "docs" / "plans"
    non_markdown = sorted(
        path.relative_to(plans_dir).as_posix()
        for path in plans_dir.rglob("*")
        if path.is_file() and path.suffix.lower() != ".md"
    )
    assert not non_markdown, f"docs/plans only allows .md files: {', '.join(non_markdown)}"
