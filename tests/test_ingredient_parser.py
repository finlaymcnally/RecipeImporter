"""Tests for ingredient parsing module."""

import pytest

from cookimport.parsing.ingredients import parse_ingredient_line


class TestBasicParsing:
    """Test basic ingredient parsing."""

    def test_simple_ingredient_with_unit(self):
        """Parse '1 cup flour' into structured components."""
        result = parse_ingredient_line("1 cup flour")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 1.0
        assert result["input_unit_id"] == "cup"
        assert result["input_item"] == "flour"
        assert result["raw_text"] == "1 cup flour"

    def test_ingredient_with_preparation(self):
        """Parse '2 cloves garlic, minced' with prep instructions."""
        result = parse_ingredient_line("2 cloves garlic, minced")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 2.0
        assert result["input_item"] == "garlic"
        assert result["preparation"] == "minced"

    def test_ingredient_with_stalks(self):
        """Parse '3 stalks celery, sliced'."""
        result = parse_ingredient_line("3 stalks celery, sliced")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 3.0
        assert result["input_unit_id"] == "stalks"
        assert result["input_item"] == "celery"
        assert result["preparation"] == "sliced"


class TestFractions:
    """Test fraction handling."""

    def test_unicode_fraction(self):
        """Parse '⅓ cup sugar' with unicode fraction."""
        result = parse_ingredient_line("⅓ cup sugar")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] is not None
        assert abs(result["input_qty"] - 0.333) < 0.01
        assert result["input_unit_id"] in ("cup", "cups")
        assert result["input_item"] == "sugar"

    def test_mixed_fraction(self):
        """Parse '1 1/2 cups flour' with mixed fraction."""
        result = parse_ingredient_line("1 1/2 cups flour")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 1.5
        assert result["input_unit_id"] in ("cup", "cups")

    def test_quarter_fraction(self):
        """Parse '¼ teaspoon salt'."""
        result = parse_ingredient_line("¼ teaspoon salt")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 0.25
        assert result["input_unit_id"] in ("teaspoon", "teaspoons")


class TestRanges:
    """Test quantity range handling."""

    def test_range_rounds_up(self):
        """Parse '3-4 Tbsp butter' - midpoint 3.5 rounds to 4."""
        result = parse_ingredient_line("3-4 Tbsp butter")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 4.0  # ceil((3+4)/2) = ceil(3.5) = 4
        assert result["input_unit_id"] is not None

    def test_range_even_midpoint(self):
        """Parse '2-4 cups water' - midpoint 3 stays 3."""
        result = parse_ingredient_line("2-4 cups water")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 3.0  # ceil((2+4)/2) = ceil(3) = 3


class TestUnquantified:
    """Test unquantified ingredients."""

    def test_to_taste(self):
        """Parse 'salt, to taste' as unquantified."""
        result = parse_ingredient_line("salt, to taste")
        assert result["quantity_kind"] == "unquantified"
        assert result["input_qty"] is None
        assert result["input_item"] is not None

    def test_pepper_to_taste(self):
        """Parse 'Pepper, to taste'."""
        result = parse_ingredient_line("Pepper, to taste")
        assert result["quantity_kind"] == "unquantified"
        assert result["input_qty"] is None
        assert result["note"] is not None
        assert "taste" in result["note"].lower()


class TestSectionHeaders:
    """Test section header detection."""

    def test_all_caps_header(self):
        """Detect 'FILLING' as section header."""
        result = parse_ingredient_line("FILLING")
        assert result["quantity_kind"] == "section_header"
        assert result["input_item"] == "FILLING"
        assert result["input_qty"] is None

    def test_all_caps_multi_word(self):
        """Detect 'MASHED POTATOES' as section header."""
        result = parse_ingredient_line("MASHED POTATOES")
        assert result["quantity_kind"] == "section_header"
        assert result["input_item"] == "MASHED POTATOES"

    def test_title_case_header(self):
        """Detect 'Marinade' as section header."""
        result = parse_ingredient_line("Marinade")
        assert result["quantity_kind"] == "section_header"
        assert result["input_item"] == "Marinade"

    def test_garnish_header(self):
        """Detect 'Garnish' as section header."""
        result = parse_ingredient_line("Garnish")
        assert result["quantity_kind"] == "section_header"


class TestComplexIngredients:
    """Test complex ingredient formats."""

    def test_ingredient_with_parenthetical(self):
        """Parse ingredient with parenthetical note."""
        result = parse_ingredient_line("1 1/2 cups lentils (rinsed and drained)")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 1.5
        assert result["input_item"] is not None

    def test_compound_unit(self):
        """Parse '1 10-ounce bag frozen peas'."""
        result = parse_ingredient_line("1 10-ounce bag frozen peas")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] is not None
        assert result["input_item"] is not None

    def test_chicken_breasts(self):
        """Parse '2 chicken breasts, cubed'."""
        result = parse_ingredient_line("2 chicken breasts, cubed")
        assert result["quantity_kind"] == "quantified"
        assert result["input_qty"] == 2.0
        assert result["input_unit_id"] == "medium"  # Default for count-based
        assert result["input_item"] == "chicken breasts"
        assert result["preparation"] == "cubed"


class TestOptional:
    """Test optional ingredient detection."""

    def test_optional_in_note(self):
        """Detect optional from note."""
        result = parse_ingredient_line("1 cup nuts (optional)")
        assert result["is_optional"] is True


class TestEdgeCases:
    """Test edge cases."""

    def test_empty_string(self):
        """Handle empty input gracefully."""
        result = parse_ingredient_line("")
        assert result["quantity_kind"] == "unquantified"
        assert result["raw_text"] == ""

    def test_whitespace_only(self):
        """Handle whitespace-only input."""
        result = parse_ingredient_line("   ")
        assert result["quantity_kind"] == "unquantified"

    def test_preserves_raw_text(self):
        """Raw text is always preserved."""
        original = "3 stalks celery, sliced"
        result = parse_ingredient_line(original)
        assert result["raw_text"] == original


class TestConfidence:
    """Test confidence scoring."""

    def test_has_confidence(self):
        """Parsed results include confidence score."""
        result = parse_ingredient_line("1 cup flour")
        assert "confidence" in result
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0

    def test_section_header_zero_confidence(self):
        """Section headers have zero confidence."""
        result = parse_ingredient_line("FILLING")
        assert result["confidence"] == 0.0
