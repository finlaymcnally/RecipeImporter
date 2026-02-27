#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from difflib import SequenceMatcher as StdlibSequenceMatcher

from cookimport.bench.sequence_matcher_select import (
    SEQUENCE_MATCHER_ENV,
    get_sequence_matcher_selection,
    reset_sequence_matcher_selection_cache,
)


@dataclass(frozen=True)
class BenchmarkResult:
    mode: str
    implementation: str
    version: str | None
    best_seconds: float
    mean_seconds: float
    opcode_count: int


def _build_text_pair(token_count: int) -> tuple[str, str]:
    left_parts: list[str] = []
    right_parts: list[str] = []
    for index in range(max(1, int(token_count))):
        token = f"token{index % 17}"
        left_parts.append(token)
        if index % 37 == 0:
            right_parts.append(f"{token}_edit")
        else:
            right_parts.append(token)
    return " ".join(left_parts), " ".join(right_parts)


def _with_matcher_mode(mode: str) -> None:
    os.environ[SEQUENCE_MATCHER_ENV] = mode
    reset_sequence_matcher_selection_cache()


def _benchmark_mode(mode: str, left_text: str, right_text: str, repeats: int) -> BenchmarkResult:
    _with_matcher_mode(mode)
    selection = get_sequence_matcher_selection()
    samples: list[float] = []
    opcode_count = 0
    for _ in range(max(1, int(repeats))):
        started = time.perf_counter()
        matcher = selection.matcher_class(
            None,
            left_text,
            right_text,
            autojunk=False,
        )
        opcodes = matcher.get_opcodes()
        elapsed = max(0.0, time.perf_counter() - started)
        samples.append(elapsed)
        opcode_count = len(opcodes)

    best_seconds = min(samples)
    mean_seconds = sum(samples) / float(len(samples))
    return BenchmarkResult(
        mode=mode,
        implementation=selection.implementation,
        version=selection.version,
        best_seconds=best_seconds,
        mean_seconds=mean_seconds,
        opcode_count=opcode_count,
    )


def _stdlib_opcode_signature(left_text: str, right_text: str) -> list[tuple[str, int, int, int, int]]:
    matcher = StdlibSequenceMatcher(None, left_text, right_text, autojunk=False)
    return matcher.get_opcodes()


def _selected_opcode_signature(left_text: str, right_text: str) -> list[tuple[str, int, int, int, int]]:
    matcher = get_sequence_matcher_selection().matcher_class(
        None,
        left_text,
        right_text,
        autojunk=False,
    )
    return matcher.get_opcodes()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Quick local benchmark for SequenceMatcher implementation selection used by "
            "canonical-text evaluation."
        )
    )
    parser.add_argument(
        "--tokens",
        type=int,
        default=1400,
        help="Number of generated tokens per side (default: 1400).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Benchmark repeats per mode (default: 5).",
    )
    args = parser.parse_args()

    previous_mode = os.environ.get(SEQUENCE_MATCHER_ENV)
    try:
        left_text, right_text = _build_text_pair(token_count=args.tokens)
        stdlib_result = _benchmark_mode("stdlib", left_text, right_text, args.repeats)
        auto_result = _benchmark_mode("auto", left_text, right_text, args.repeats)

        _with_matcher_mode("stdlib")
        stdlib_opcodes = _stdlib_opcode_signature(left_text, right_text)
        _with_matcher_mode("auto")
        auto_opcodes = _selected_opcode_signature(left_text, right_text)
        opcodes_match = stdlib_opcodes == auto_opcodes

        print(
            f"Generated texts: left_chars={len(left_text)} right_chars={len(right_text)} "
            f"tokens={args.tokens}"
        )
        for result in (stdlib_result, auto_result):
            print(
                f"{result.mode}: impl={result.implementation} version={result.version} "
                f"best_seconds={result.best_seconds:.6f} "
                f"mean_seconds={result.mean_seconds:.6f} "
                f"opcode_count={result.opcode_count}"
            )
        print(f"opcode_parity={opcodes_match}")
        return 0
    finally:
        if previous_mode is None:
            os.environ.pop(SEQUENCE_MATCHER_ENV, None)
        else:
            os.environ[SEQUENCE_MATCHER_ENV] = previous_mode
        reset_sequence_matcher_selection_cache()


if __name__ == "__main__":
    raise SystemExit(main())
