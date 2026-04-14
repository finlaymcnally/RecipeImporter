from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import cookimport.bench.sequence_matcher_select as sequence_matcher_select
from cookimport.bench.sequence_matcher_select import (
    SEQUENCE_MATCHER_ENV,
    get_sequence_matcher_selection,
    reset_sequence_matcher_selection_cache,
    select_sequence_matcher,
)


@pytest.fixture(autouse=True)
def _reset_sequence_matcher_cache() -> None:
    reset_sequence_matcher_selection_cache()
    yield
    reset_sequence_matcher_selection_cache()


def _matching_blocks_as_tuples(matcher: object) -> list[tuple[int, int, int]]:
    return [
        (int(match.a), int(match.b), int(match.size))
        for match in matcher.get_matching_blocks()  # type: ignore[attr-defined]
        if int(match.size) > 0
    ]
def _largeish_edit_example() -> tuple[str, str]:
    left_parts: list[str] = []
    right_parts: list[str] = []
    for index in range(520):
        token = f"token{index % 17}"
        left_parts.append(token)
        if index % 37 == 0:
            right_parts.append(f"{token}_edit")
        else:
            right_parts.append(token)
    return " ".join(left_parts), " ".join(right_parts)


def _many_small_edits_example() -> tuple[str, str]:
    left_chars: list[str] = []
    for index in range(2200):
        left_chars.append(chr(ord("a") + (index % 26)))
        if index % 19 == 0:
            left_chars.append(" ")
    right_chars = list(left_chars)
    for index in range(11, len(right_chars), 97):
        current = right_chars[index]
        if current.isalpha():
            right_chars[index] = current.upper()
        elif current == " ":
            right_chars[index] = "-"
        else:
            right_chars[index] = "#"
    return "".join(left_chars), "".join(right_chars)


_TRICKY_TEXT_PAIRS: list[tuple[str, str]] = [
    (
        " ".join(["salt", "pepper", "garlic"] * 180),
        " ".join(["salt", "pepper", "garlic_x"] * 180),
    ),
    _many_small_edits_example(),
    (
        "step 1:\tmix flour\n\nstep 2:   add sugar\r\n\r\nstep 3:\t\tstir",
        "step 1: mix flour\nstep 2: add sugar\nstep 3: stir",
    ),
    _largeish_edit_example(),
]


def test_sequence_matcher_selector_defaults_to_dmp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SEQUENCE_MATCHER_ENV, raising=False)
    selection = get_sequence_matcher_selection()
    assert selection.implementation == "dmp"
    assert selection.forced_mode == "dmp"


@pytest.mark.parametrize(
    "mode",
    [
        "fallback",
        "stdlib",
        "cydifflib",
        "cdifflib",
        "multilayer",
        "auto",
        "not-a-mode",
    ],
)
def test_sequence_matcher_selector_rejects_archived_modes(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, mode)
    with pytest.raises(ValueError, match=SEQUENCE_MATCHER_ENV):
        select_sequence_matcher()


def test_sequence_matcher_selector_forced_missing_dmp_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "dmp")
    monkeypatch.setattr(sequence_matcher_select, "_try_dmp", lambda **_kwargs: None)
    with pytest.raises(RuntimeError, match="fast-diff-match-patch"):
        select_sequence_matcher()


@pytest.mark.parametrize(("prediction_text", "canonical_text"), _TRICKY_TEXT_PAIRS)
def test_dmp_matching_blocks_are_monotonic_and_equal_substrings(
    monkeypatch: pytest.MonkeyPatch,
    prediction_text: str,
    canonical_text: str,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "dmp")
    selection = select_sequence_matcher()
    matcher = selection.matcher_class(
        None,
        prediction_text,
        canonical_text,
        autojunk=False,
    )
    blocks = matcher.get_matching_blocks()
    assert blocks
    assert int(blocks[-1].size) == 0
    assert int(blocks[-1].a) == len(prediction_text)
    assert int(blocks[-1].b) == len(canonical_text)

    previous_a_end = 0
    previous_b_end = 0
    for block in blocks:
        a_start = int(block.a)
        b_start = int(block.b)
        size = int(block.size)
        assert 0 <= a_start <= len(prediction_text)
        assert 0 <= b_start <= len(canonical_text)
        assert size >= 0
        assert a_start + size <= len(prediction_text)
        assert b_start + size <= len(canonical_text)
        assert a_start >= previous_a_end
        assert b_start >= previous_b_end
        if size > 0:
            assert (
                prediction_text[a_start : a_start + size]
                == canonical_text[b_start : b_start + size]
            )
        previous_a_end = a_start + size
        previous_b_end = b_start + size


def test_sequence_matcher_selector_forced_dmp_reports_runtime_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SEQUENCE_MATCHER_ENV, "dmp")
    monkeypatch.setenv("COOKIMPORT_DMP_CLEANUP", "No")
    monkeypatch.setenv("COOKIMPORT_DMP_CHECKLINES", "0")
    monkeypatch.setenv("COOKIMPORT_DMP_TIMELIMIT", "0")
    selection = get_sequence_matcher_selection()

    assert selection.implementation == "dmp"
    assert selection.extra_telemetry is not None
    assert selection.extra_telemetry.get("alignment_dmp_cleanup") == "No"
    assert selection.extra_telemetry.get("alignment_dmp_checklines") is False
    assert selection.extra_telemetry.get("alignment_dmp_timelimit") == pytest.approx(0.0)


def test_matching_blocks_tuple_helper_drops_terminal_zero_block() -> None:
    matcher = sequence_matcher_select.SequenceMatcher(
        None,
        "abc",
        "abc",
        autojunk=False,
    )
    assert _matching_blocks_as_tuples(matcher) == [(0, 0, 3)]


def test_sequence_matcher_benchmark_script_supports_stdlib_and_dmp_modes() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "bench_sequence_matcher_impl.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--tokens",
            "80",
            "--repeats",
            "1",
            "--modes",
            "stdlib,dmp",
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert proc.returncode == 0
    output = proc.stdout
    assert "stdlib: impl=stdlib" in output
    assert "dmp: impl=dmp" in output
