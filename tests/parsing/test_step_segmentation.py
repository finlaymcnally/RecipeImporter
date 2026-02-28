from __future__ import annotations

import pytest

from cookimport.parsing import step_segmentation
from cookimport.parsing.step_segmentation import (
    segment_instruction_steps,
    should_fallback_segment,
)


def test_segment_instruction_steps_policy_off_preserves_boundaries() -> None:
    instructions = [
        "Mix flour and sugar thoroughly before adding eggs and milk.",
    ]

    segmented = segment_instruction_steps(
        instructions,
        policy="off",
        backend="heuristic_v1",
    )

    assert segmented == instructions


def test_segment_instruction_steps_always_splits_inline_numbering() -> None:
    instructions = [
        "1. Mix flour and water. 2. Knead the dough for 5 minutes. 3. Bake until golden.",
    ]

    segmented = segment_instruction_steps(
        instructions,
        policy="always",
        backend="heuristic_v1",
    )

    assert segmented == [
        "1. Mix flour and water.",
        "2. Knead the dough for 5 minutes.",
        "3. Bake until golden.",
    ]


def test_should_fallback_segment_detects_long_blob() -> None:
    instructions = [
        "Whisk flour, salt, and sugar together until smooth. Add milk slowly while stirring. "
        "Simmer for 10 minutes, then finish with butter and pepper.",
    ]

    assert should_fallback_segment(instructions) is True
    segmented = segment_instruction_steps(
        instructions,
        policy="auto",
        backend="heuristic_v1",
    )
    assert len(segmented) >= 3


def test_auto_policy_keeps_already_step_like_input() -> None:
    instructions = [
        "Whisk flour and salt.",
        "Add milk and simmer.",
    ]

    assert should_fallback_segment(instructions) is False
    segmented = segment_instruction_steps(
        instructions,
        policy="auto",
        backend="heuristic_v1",
    )
    assert segmented == instructions


def test_segmentation_preserves_section_headers() -> None:
    instructions = [
        "For the sauce:\nWhisk flour into drippings. Cook for 2 minutes. Add stock and simmer.",
    ]

    segmented = segment_instruction_steps(
        instructions,
        policy="always",
        backend="heuristic_v1",
    )

    assert segmented[0] == "For the sauce:"
    assert "Whisk flour into drippings." in segmented
    assert "Add stock and simmer." in segmented


def test_pysbd_backend_missing_dependency_has_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_missing_dependency() -> object:
        raise ValueError("Install with `pip install pysbd`.")

    monkeypatch.setattr(
        step_segmentation,
        "_build_pysbd_segmenter",
        _raise_missing_dependency,
    )

    with pytest.raises(ValueError, match="pip install pysbd"):
        segment_instruction_steps(
            ["Mix and bake."],
            policy="always",
            backend="pysbd_v1",
        )
