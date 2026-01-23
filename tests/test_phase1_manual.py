
import os
import shutil
import logging
from pathlib import Path
from cookimport.parsing import cleaning, signals
from cookimport.core.blocks import Block
from cookimport.core import reporting
from cookimport.llm import repair

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_phase1")

def test_cleaning():
    print("\n--- Testing Cleaning ---")
    
    # 1. Mojibake
    messy = "SautÃ© the onions with a touch of crÃ¨me fraÃ®che."
    cleaned = cleaning.normalize_text(messy)
    print(f"Mojibake Input:  '{messy}'")
    print(f"Mojibake Output: '{cleaned}'")
    assert "Sauté" in cleaned
    assert "crème" in cleaned

    # 2. Hyphenation
    split_word = """ingre-
dient"""
    rejoined = cleaning.repair_hyphenation(split_word)
    print(f"Hyphen Input:  {repr(split_word)}")
    print(f"Hyphen Output: {repr(rejoined)}")
    assert rejoined == "ingredient"

    # 3. Whitespace
    spaces = "Too   many    spaces."
    fixed = cleaning.standardize_whitespace(spaces)
    print(f"Spaces Input:  '{spaces}'")
    print(f"Spaces Output: '{fixed}'")
    assert fixed == "Too many spaces."

def test_signals():
    print("\n--- Testing Signals ---")
    
    # Ingredient
    ing_text = "1 1/2 cups flour"
    ing_feats = signals.classify_block(ing_text)
    print(f"Text: '{ing_text}' -> Signals: {ing_feats}")
    assert ing_feats["starts_with_quantity"] is True
    assert ing_feats["has_unit"] is True
    assert ing_feats["is_ingredient_likely"] is True

    # Instruction
    step_text = "Mix the flour and sugar."
    step_feats = signals.classify_block(step_text)
    print(f"Text: '{step_text}' -> Signals: {step_feats}")
    assert step_feats["has_imperative_verb"] is True
    assert step_feats["is_instruction_likely"] is True

    # Header
    head_text = "Ingredients"
    head_feats = signals.classify_block(head_text)
    print(f"Text: '{head_text}' -> Signals: {head_feats}")
    assert head_feats["is_header_likely"] is True

def test_reporting():
    print("\n--- Testing Reporting ---")
    tmp_dir = Path("./tmp_test_reports")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir()

    source_file = Path("test_cookbook.pdf")
    
    with reporting.ReportBuilder(source_file, tmp_dir) as report:
        report.add_candidate("id_1", "valid", 0.95, "Test Recipe")
        report.add_error("warning", "Something minor happened")

    report_file = tmp_dir / "reports" / "test_cookbook.pdf.report.json"
    if report_file.exists():
        print(f"Report successfully created at {report_file}")
        with open(report_file, "r") as f:
            print("Content:", f.read())
    else:
        print("ERROR: Report file not found!")
    
    # Cleanup
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

def test_llm():
    print("\n--- Testing LLM Repair (Mock) ---")
    # This should hit the mock provider in client.py
    candidate = repair.repair_candidate("Some messy text", hints={"type": "test"})
    if candidate:
        print("LLM Repair returned a candidate object:")
        print(candidate.model_dump_json(indent=2))
        assert candidate.name == "Repaired Recipe"
        assert candidate.ingredients[0] == "1 cup flour"
    else:
        print("ERROR: LLM Repair failed to return a candidate")

if __name__ == "__main__":
    test_cleaning()
    test_signals()
    test_reporting()
    test_llm()
    print("\nAll manual tests passed execution.")
