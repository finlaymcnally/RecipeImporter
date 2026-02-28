from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from cookimport.core.blocks import Block

_PATTERN_VERSION = "2026-02-28"

_TOC_DOT_LEADER_RE = re.compile(r"\.{2,}")
_TOC_TRAILING_PAGE_RE = re.compile(r"(?:\.{2,}\s*|\s+)(\d{1,4})\s*$")
_TOC_SECTION_RE = re.compile(r"^(chapter|part|section)\b", re.IGNORECASE)
_TOC_HEADING_RE = re.compile(r"\b(table of contents|contents)\b", re.IGNORECASE)
_TITLE_CLEAN_RE = re.compile(r"[^a-z0-9]+")

_STOP_TITLE_WORDS = {
    "ingredients",
    "instructions",
    "directions",
    "method",
    "notes",
    "tip",
    "tips",
    "serves",
}


@dataclass(frozen=True)
class PatternCluster:
    pattern: str
    start_block: int
    end_block: int
    score: float
    block_count: int
    evidence: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "pattern": self.pattern,
            "start_block": self.start_block,
            "end_block": self.end_block,
            "score": round(self.score, 4),
            "block_count": self.block_count,
            "evidence": self.evidence,
        }


@dataclass
class PatternDiagnostics:
    version: str
    block_flags: dict[int, set[str]]
    clusters: list[PatternCluster]
    duplicate_title_pairs: list[dict[str, Any]]
    excluded_indices: set[int]

    def flags_for_span(self, start: int, end: int) -> list[str]:
        flags: set[str] = set()
        for idx in range(max(0, start), max(0, end)):
            flags.update(self.block_flags.get(idx, set()))
        return sorted(flags)

    def to_artifact_content(self, *, total_blocks: int) -> dict[str, Any]:
        flags_by_block = [
            {"index": idx, "flags": sorted(flags)}
            for idx, flags in sorted(self.block_flags.items())
            if flags
        ]
        return {
            "version": self.version,
            "total_blocks": total_blocks,
            "flags_by_block": flags_by_block,
            "clusters": [cluster.to_payload() for cluster in self.clusters],
            "duplicate_title_pairs": list(self.duplicate_title_pairs),
            "pre_candidate_excluded_indices": sorted(self.excluded_indices),
        }


@dataclass(frozen=True)
class OverlapCandidate:
    candidate_index: int
    start_block: int
    end_block: int
    normalized_title: str
    score: float


def normalize_title_for_pattern(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = _TITLE_CLEAN_RE.sub(" ", str(value).casefold())
    return " ".join(cleaned.split()).strip()


def detect_deterministic_patterns(blocks: Sequence[Block]) -> PatternDiagnostics:
    block_flags: dict[int, set[str]] = {}
    clusters: list[PatternCluster] = []
    duplicate_title_pairs: list[dict[str, Any]] = []
    excluded_indices: set[int] = set()

    texts = [str(block.text or "").strip() for block in blocks]
    toc_scores: dict[int, float] = {}
    toc_like_indices: list[int] = []
    for idx, text in enumerate(texts):
        score = _toc_line_score(text)
        if score <= 0:
            continue
        toc_scores[idx] = score
        if score >= 0.7:
            toc_like_indices.append(idx)

    for run in _contiguous_runs(toc_like_indices):
        if not run:
            continue
        run_scores = [toc_scores[idx] for idx in run]
        avg_score = sum(run_scores) / len(run_scores)
        has_heading = any(_is_toc_heading(texts[idx]) for idx in run)
        if not (
            (len(run) >= 4 and avg_score >= 0.72)
            or (has_heading and len(run) >= 2 and avg_score >= 0.55)
        ):
            continue
        start = run[0]
        end = run[-1] + 1
        clusters.append(
            PatternCluster(
                pattern="toc_like_cluster",
                start_block=start,
                end_block=end,
                score=avg_score,
                block_count=len(run),
                evidence="dot-leaders/trailing-page numbers with TOC-like headings",
            )
        )
        for idx in run:
            _add_flag(block_flags, idx, "toc_like_cluster")
            excluded_indices.add(idx)

    title_positions: dict[str, list[int]] = {}
    for idx, text in enumerate(texts):
        normalized = normalize_title_for_pattern(text)
        if not _is_duplicate_title_candidate(text, normalized):
            continue
        title_positions.setdefault(normalized, []).append(idx)

    for normalized_title, indices in sorted(title_positions.items()):
        if len(indices) < 2:
            continue
        for left, right in zip(indices, indices[1:]):
            gap = right - left
            if gap < 2 or gap > 36:
                continue
            if not _span_looks_like_intro(blocks, texts, left + 1, right):
                continue
            if not _has_recipe_anchor_after(blocks, texts, right):
                continue
            for idx in range(left, right):
                _add_flag(block_flags, idx, "duplicate_title_intro")
            duplicate_title_pairs.append(
                {
                    "title_norm": normalized_title,
                    "title_text": texts[left],
                    "left_block_index": left,
                    "right_block_index": right,
                    "intro_block_count": max(0, right - left - 1),
                }
            )
            clusters.append(
                PatternCluster(
                    pattern="duplicate_title_intro",
                    start_block=left,
                    end_block=right,
                    score=1.0,
                    block_count=max(1, right - left),
                    evidence="repeated short title with intro-like span before recipe anchor",
                )
            )
            break

    return PatternDiagnostics(
        version=_PATTERN_VERSION,
        block_flags=block_flags,
        clusters=clusters,
        duplicate_title_pairs=duplicate_title_pairs,
        excluded_indices=excluded_indices,
    )


def apply_candidate_start_trims(
    candidates: Sequence[tuple[int, int, float]],
    diagnostics: PatternDiagnostics,
) -> tuple[list[tuple[int, int, float]], list[dict[str, Any]]]:
    if not candidates:
        return [], []

    trimmed: list[tuple[int, int, float]] = []
    actions: list[dict[str, Any]] = []
    title_pairs = sorted(
        diagnostics.duplicate_title_pairs,
        key=lambda row: (
            int(row.get("left_block_index", 0)),
            int(row.get("right_block_index", 0)),
        ),
    )

    for candidate_index, (start, end, score) in enumerate(candidates):
        new_start = start
        for pair in title_pairs:
            left = int(pair.get("left_block_index", -1))
            right = int(pair.get("right_block_index", -1))
            if left < start or left > start + 8:
                continue
            if right <= start or right >= end:
                continue
            if right - start > 40:
                continue
            new_start = right
            actions.append(
                {
                    "candidate_index": candidate_index,
                    "action": "trim_candidate_start",
                    "original_start_block": start,
                    "trimmed_start_block": new_start,
                    "title_norm": str(pair.get("title_norm") or ""),
                }
            )
            break
        trimmed.append((new_start, end, score))

    return trimmed, actions


def resolve_overlap_duplicate_candidates(
    candidates: Sequence[OverlapCandidate],
) -> list[dict[str, Any]]:
    if len(candidates) < 2:
        return []

    decisions: list[dict[str, Any]] = []
    grouped: dict[str, list[OverlapCandidate]] = {}
    for candidate in candidates:
        if not candidate.normalized_title:
            continue
        grouped.setdefault(candidate.normalized_title, []).append(candidate)

    for normalized_title, group in grouped.items():
        if len(group) < 2:
            continue
        index_map = {item.candidate_index: item for item in group}
        remaining = set(index_map)
        while remaining:
            seed_index = min(remaining)
            remaining.remove(seed_index)
            component_indices = {seed_index}
            queue = [seed_index]
            while queue:
                current_index = queue.pop(0)
                current = index_map[current_index]
                to_visit: list[int] = []
                for other_index in list(remaining):
                    other = index_map[other_index]
                    if _ranges_overlap(
                        current.start_block,
                        current.end_block,
                        other.start_block,
                        other.end_block,
                    ):
                        to_visit.append(other_index)
                for other_index in to_visit:
                    remaining.remove(other_index)
                    component_indices.add(other_index)
                    queue.append(other_index)
            if len(component_indices) < 2:
                continue
            component = [index_map[idx] for idx in sorted(component_indices)]
            winner = max(
                component,
                key=lambda row: (
                    row.score,
                    -row.start_block,
                    -(row.end_block - row.start_block),
                    -row.candidate_index,
                ),
            )
            for row in component:
                if row.candidate_index == winner.candidate_index:
                    continue
                decisions.append(
                    {
                        "action": "reject_overlap_duplicate_candidate",
                        "normalized_title": normalized_title,
                        "winner_candidate_index": winner.candidate_index,
                        "loser_candidate_index": row.candidate_index,
                    }
                )

    decisions.sort(
        key=lambda row: (
            int(row.get("loser_candidate_index", 0)),
            int(row.get("winner_candidate_index", 0)),
        )
    )
    return decisions


def pattern_warning_lines(
    diagnostics: PatternDiagnostics,
    *,
    overlap_dropped_count: int = 0,
) -> list[str]:
    warnings: list[str] = []

    toc_clusters = [
        cluster for cluster in diagnostics.clusters if cluster.pattern == "toc_like_cluster"
    ]
    if toc_clusters:
        toc_blocks = sum(cluster.block_count for cluster in toc_clusters)
        warnings.append(
            "pattern_toc_like_cluster_detected: "
            f"clusters={len(toc_clusters)} blocks={toc_blocks}"
        )

    if diagnostics.duplicate_title_pairs:
        warnings.append(
            "pattern_duplicate_title_flow_detected: "
            f"title_groups={len(diagnostics.duplicate_title_pairs)}"
        )

    if overlap_dropped_count > 0:
        warnings.append(
            "pattern_overlap_duplicate_candidates_resolved: "
            f"dropped={int(overlap_dropped_count)}"
        )

    return warnings


def _add_flag(block_flags: dict[int, set[str]], index: int, flag: str) -> None:
    if index < 0:
        return
    block_flags.setdefault(index, set()).add(flag)


def _contiguous_runs(indices: Sequence[int]) -> list[list[int]]:
    if not indices:
        return []
    ordered = sorted(set(int(idx) for idx in indices if idx >= 0))
    if not ordered:
        return []
    runs: list[list[int]] = [[ordered[0]]]
    for idx in ordered[1:]:
        if idx == runs[-1][-1] + 1:
            runs[-1].append(idx)
            continue
        runs.append([idx])
    return runs


def _is_toc_heading(text: str) -> bool:
    return bool(_TOC_HEADING_RE.search(text))


def _toc_line_score(text: str) -> float:
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0.0

    score = 0.0
    if _is_toc_heading(cleaned):
        score += 1.0
    if _TOC_DOT_LEADER_RE.search(cleaned):
        score += 0.6
    if _TOC_TRAILING_PAGE_RE.search(cleaned):
        score += 0.35
    if _TOC_SECTION_RE.search(cleaned):
        score += 0.25
    word_count = len(cleaned.split())
    if 2 <= word_count <= 16:
        score += 0.15
    if len(cleaned) <= 120:
        score += 0.1
    if word_count <= 1 and not _is_toc_heading(cleaned):
        score *= 0.4
    return min(1.6, score)


def _is_duplicate_title_candidate(text: str, normalized: str) -> bool:
    if not normalized:
        return False
    if normalized in _STOP_TITLE_WORDS:
        return False
    if len(normalized) < 4:
        return False
    words = normalized.split()
    if len(words) < 2 or len(words) > 10:
        return False
    if len(text) > 90:
        return False
    if _TOC_TRAILING_PAGE_RE.search(text):
        return False
    return True


def _span_looks_like_intro(
    blocks: Sequence[Block],
    texts: Sequence[str],
    start: int,
    end: int,
) -> bool:
    non_empty = 0
    ingredient_signals = 0
    instruction_signals = 0
    for idx in range(max(0, start), max(0, end)):
        text = texts[idx]
        if not text:
            continue
        non_empty += 1
        lowered = text.casefold()
        block = blocks[idx]
        features = block.features if isinstance(block.features, dict) else {}
        if (
            bool(features.get("is_ingredient_likely"))
            or bool(features.get("starts_with_quantity"))
            or lowered in {"ingredients", "ingredient"}
        ):
            ingredient_signals += 1
        if (
            bool(features.get("is_instruction_likely"))
            or lowered in {"instructions", "directions", "method"}
        ):
            instruction_signals += 1
    if non_empty == 0:
        return False
    return ingredient_signals == 0 and instruction_signals <= 1


def _has_recipe_anchor_after(
    blocks: Sequence[Block],
    texts: Sequence[str],
    title_index: int,
) -> bool:
    window_end = min(len(blocks), title_index + 12)
    for idx in range(max(0, title_index + 1), window_end):
        text = texts[idx].casefold()
        block = blocks[idx]
        features = block.features if isinstance(block.features, dict) else {}
        if text in {"ingredients", "ingredient"}:
            return True
        if bool(features.get("is_ingredient_header")) or bool(features.get("starts_with_quantity")):
            return True
    return False


def _ranges_overlap(
    left_start: int,
    left_end: int,
    right_start: int,
    right_end: int,
) -> bool:
    return left_start < right_end and right_start < left_end

