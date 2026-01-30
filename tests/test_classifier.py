"""Tests for the recipe text classifier."""

from __future__ import annotations

import pytest

from cookimport.parsing.classifier import (
    ClassificationResult,
    classify_lines,
    classifier_available,
)


def test_classifier_available():
    """Classifier should always be available (heuristic-based)."""
    assert classifier_available() is True


def test_classify_ingredients():
    """Test classification of ingredient lines."""
    lines = [
        "2 cups flour",
        "1/2 teaspoon salt",
        "1 tablespoon olive oil",
        "3 large eggs",
        "Salt and pepper to taste",
        "Fresh basil leaves",
        "1 (14 oz) can diced tomatoes",
    ]
    results = classify_lines(lines)

    for result in results:
        assert result.label == "ingredient", f"Expected ingredient: {result.text}"
        assert result.confidence > 0.5


def test_classify_instructions():
    """Test classification of instruction lines."""
    lines = [
        "Preheat oven to 350 degrees F.",
        "Mix the flour and sugar together.",
        "Bake for 30 minutes until golden brown.",
        "Let cool for 10 minutes before serving.",
        "Stir constantly over medium heat.",
        "1. Combine all dry ingredients in a bowl.",
    ]
    results = classify_lines(lines)

    for result in results:
        assert result.label == "instruction", f"Expected instruction: {result.text}"
        assert result.confidence > 0.5


def test_classify_other():
    """Test classification of other content (headers, narrative, etc.)."""
    lines = [
        "Ingredients",
        "Instructions:",
        "This recipe was passed down from my grandmother.",
        "I love making this on Sunday mornings with my family.",
        "Notes",
        "Tips:",
    ]
    results = classify_lines(lines)

    for result in results:
        assert result.label == "other", f"Expected other: {result.text}"


def test_classify_returns_classification_results():
    """Test that classify_lines returns ClassificationResult objects."""
    results = classify_lines(["2 cups flour"])

    assert len(results) == 1
    assert isinstance(results[0], ClassificationResult)
    assert results[0].text == "2 cups flour"
    assert results[0].label in ("ingredient", "instruction", "other")
    assert 0 <= results[0].confidence <= 1
    assert "ingredient" in results[0].scores
    assert "instruction" in results[0].scores
    assert "other" in results[0].scores


def test_classify_empty_list():
    """Test classification of empty list."""
    results = classify_lines([])
    assert results == []


def test_classify_mixed_content():
    """Test classification of mixed recipe content."""
    lines = [
        "Chocolate Chip Cookies",  # other (title)
        "Ingredients:",  # other (header)
        "2 cups flour",  # ingredient
        "1 cup sugar",  # ingredient
        "1/2 cup butter, softened",  # ingredient
        "2 eggs",  # ingredient
        "Instructions:",  # other (header)
        "Preheat oven to 375 degrees F.",  # instruction
        "Cream butter and sugar together.",  # instruction
        "Add eggs and vanilla.",  # instruction
        "This recipe makes the best cookies ever!",  # other (narrative)
    ]
    results = classify_lines(lines)

    # Check specific expected labels
    assert results[0].label == "other"  # Title
    assert results[1].label == "other"  # Ingredients header
    assert results[2].label == "ingredient"  # 2 cups flour
    assert results[6].label == "other"  # Instructions header
    assert results[7].label == "instruction"  # Preheat oven
