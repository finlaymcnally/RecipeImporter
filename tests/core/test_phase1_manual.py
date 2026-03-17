from pathlib import Path

from cookimport.parsing import cleaning, signals
from cookimport.core import reporting


def test_cleaning() -> None:
    # Mojibake
    messy = "SautÃ© the onions with a touch of crÃ¨me fraÃ®che."
    cleaned = cleaning.normalize_text(messy)
    assert "Sauté" in cleaned
    assert "crème" in cleaned

    # Hyphenation
    split_word = """ingre-
dient"""
    rejoined = cleaning.repair_hyphenation(split_word)
    assert rejoined == "ingredient"

    # Whitespace
    spaces = "Too   many    spaces."
    fixed = cleaning.standardize_whitespace(spaces)
    assert fixed == "Too many spaces."


def test_signals() -> None:
    # Ingredient
    ing_text = "1 1/2 cups flour"
    ing_feats = signals.classify_block(ing_text)
    assert ing_feats["starts_with_quantity"] is True
    assert ing_feats["has_unit"] is True
    assert ing_feats["is_ingredient_likely"] is True

    # Instruction
    step_text = "Mix the flour and sugar."
    step_feats = signals.classify_block(step_text)
    assert step_feats["has_imperative_verb"] is True
    assert step_feats["is_instruction_likely"] is True

    # Header
    head_text = "Ingredients"
    head_feats = signals.classify_block(head_text)
    assert head_feats["is_header_likely"] is True


def test_reporting(tmp_path: Path) -> None:
    source_file = Path("test_cookbook.pdf")

    with reporting.ReportBuilder(source_file, tmp_path) as report:
        report.add_candidate("id_1", "valid", 0.95, "Test Recipe")
        report.add_error("warning", "Something minor happened")

    report_file = tmp_path / "reports" / "test_cookbook.pdf.report.json"
    assert report_file.exists()
    assert report_file.read_text(encoding="utf-8").strip()
