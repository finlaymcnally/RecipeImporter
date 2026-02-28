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
    error: str | None
    best_seconds: float
    mean_seconds: float
    speedup_vs_stdlib_best: float | None
    speedup_vs_stdlib_mean: float | None
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
    if mode == "stdlib":
        selection = None
        implementation = "stdlib"
        version = None
    else:
        _with_matcher_mode(mode)
        try:
            selection = get_sequence_matcher_selection()
        except Exception as exc:  # noqa: BLE001
            return BenchmarkResult(
                mode=mode,
                implementation="unavailable",
                version=None,
                error=str(exc),
                best_seconds=0.0,
                mean_seconds=0.0,
                speedup_vs_stdlib_best=None,
                speedup_vs_stdlib_mean=None,
                opcode_count=0,
            )
        implementation = selection.implementation
        version = selection.version
    samples: list[float] = []
    opcode_count = 0
    for _ in range(max(1, int(repeats))):
        started = time.perf_counter()
        if mode == "stdlib":
            matcher = StdlibSequenceMatcher(
                None,
                left_text,
                right_text,
                autojunk=False,
            )
        else:
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
        implementation=implementation,
        version=version,
        error=None,
        best_seconds=best_seconds,
        mean_seconds=mean_seconds,
        speedup_vs_stdlib_best=None,
        speedup_vs_stdlib_mean=None,
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


def _selected_matching_block_signature(left_text: str, right_text: str) -> list[tuple[int, int, int]]:
    matcher = get_sequence_matcher_selection().matcher_class(
        None,
        left_text,
        right_text,
        autojunk=False,
    )
    return [
        (int(match.a), int(match.b), int(match.size))
        for match in matcher.get_matching_blocks()
        if int(match.size) > 0
    ]


def _stdlib_matching_block_signature(left_text: str, right_text: str) -> list[tuple[int, int, int]]:
    matcher = StdlibSequenceMatcher(None, left_text, right_text, autojunk=False)
    return [
        (int(match.a), int(match.b), int(match.size))
        for match in matcher.get_matching_blocks()
        if int(match.size) > 0
    ]


def _parse_modes(raw_modes: str) -> list[str]:
    parsed = [part.strip() for part in str(raw_modes or "").split(",") if part.strip()]
    if not parsed:
        return ["stdlib", "dmp"]
    # Preserve ordering while deduplicating.
    unique: list[str] = []
    for mode in parsed:
        if mode not in unique:
            unique.append(mode)
    return unique


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
    parser.add_argument(
        "--modes",
        default="stdlib,dmp",
        help=(
            "Comma-separated matcher modes to benchmark "
            "(default: stdlib,dmp)."
        ),
    )
    args = parser.parse_args()

    previous_mode = os.environ.get(SEQUENCE_MATCHER_ENV)
    try:
        left_text, right_text = _build_text_pair(token_count=args.tokens)
        modes = _parse_modes(args.modes)
        results = [_benchmark_mode(mode, left_text, right_text, args.repeats) for mode in modes]

        stdlib_result: BenchmarkResult | None = None
        for result in results:
            if result.mode == "stdlib" and result.error is None:
                stdlib_result = result
                break
        if stdlib_result is None:
            stdlib_result = _benchmark_mode("stdlib", left_text, right_text, args.repeats)
            results.append(stdlib_result)

        normalized_results: list[BenchmarkResult] = []
        for result in results:
            if result.error is not None:
                normalized_results.append(result)
                continue
            speedup_best = (
                stdlib_result.best_seconds / result.best_seconds
                if result.best_seconds > 0.0
                else None
            )
            speedup_mean = (
                stdlib_result.mean_seconds / result.mean_seconds
                if result.mean_seconds > 0.0
                else None
            )
            normalized_results.append(
                BenchmarkResult(
                    mode=result.mode,
                    implementation=result.implementation,
                    version=result.version,
                    error=None,
                    best_seconds=result.best_seconds,
                    mean_seconds=result.mean_seconds,
                    speedup_vs_stdlib_best=speedup_best,
                    speedup_vs_stdlib_mean=speedup_mean,
                    opcode_count=result.opcode_count,
                )
            )

        stdlib_opcodes = _stdlib_opcode_signature(left_text, right_text)
        stdlib_blocks = _stdlib_matching_block_signature(left_text, right_text)

        print(
            f"Generated texts: left_chars={len(left_text)} right_chars={len(right_text)} "
            f"tokens={args.tokens}"
        )
        for result in normalized_results:
            if result.error is not None:
                print(
                    f"{result.mode}: unavailable error={result.error}"
                )
                continue
            if result.mode == "stdlib":
                selected_opcodes = stdlib_opcodes
                selected_blocks = stdlib_blocks
            else:
                _with_matcher_mode(result.mode)
                selected_opcodes = _selected_opcode_signature(left_text, right_text)
                selected_blocks = _selected_matching_block_signature(left_text, right_text)
            opcode_parity = selected_opcodes == stdlib_opcodes
            block_parity = selected_blocks == stdlib_blocks
            print(
                f"{result.mode}: impl={result.implementation} version={result.version} "
                f"best_seconds={result.best_seconds:.6f} "
                f"mean_seconds={result.mean_seconds:.6f} "
                f"speedup_vs_stdlib_best={result.speedup_vs_stdlib_best:.3f}x "
                f"speedup_vs_stdlib_mean={result.speedup_vs_stdlib_mean:.3f}x "
                f"opcode_count={result.opcode_count} "
                f"opcode_parity_vs_stdlib={opcode_parity} "
                f"matching_block_parity_vs_stdlib={block_parity}"
            )
        return 0
    finally:
        if previous_mode is None:
            os.environ.pop(SEQUENCE_MATCHER_ENV, None)
        else:
            os.environ[SEQUENCE_MATCHER_ENV] = previous_mode
        reset_sequence_matcher_selection_cache()


if __name__ == "__main__":
    raise SystemExit(main())
