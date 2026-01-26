#!/usr/bin/env python3
"""Lightweight evaluation harness for topic candidates.

Usage:
  python tools/tip_eval.py template --input path/to/topic_candidates.json --out path/to/topic_labels.jsonl
  python tools/tip_eval.py score --labels path/to/topic_labels.jsonl [--overrides path/to/overrides.yaml]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from cookimport.core.overrides_io import load_parsing_overrides
from cookimport.parsing.tips import extract_tip_candidates


def _load_topic_candidates(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    raise ValueError("Expected a JSON list of topic candidates")


def _write_labels_template(candidates: list[dict], out_path: Path) -> None:
    lines: list[str] = []
    for idx, candidate in enumerate(candidates):
        entry = {
            "id": candidate.get("id") or f"tc{idx}",
            "text": candidate.get("text", ""),
            "anchors": candidate.get("tags", {}),
            "label": "",
            "notes": "",
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _iter_labels(path: Path) -> Iterable[dict]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        yield json.loads(line)


def _predict_is_tip(text: str, overrides_path: Path | None) -> bool:
    overrides = load_parsing_overrides(overrides_path) if overrides_path else None
    candidates = extract_tip_candidates(
        text,
        source_section="standalone_topic",
        overrides=overrides,
    )
    return any(c.scope == "general" and c.standalone for c in candidates)


def _normalize_label(label: str) -> str:
    return label.strip().lower()


def score_labels(labels_path: Path, overrides_path: Path | None) -> None:
    tp = fp = tn = fn = 0
    total = 0
    skipped = 0
    for entry in _iter_labels(labels_path):
        label = _normalize_label(entry.get("label", ""))
        if not label:
            skipped += 1
            continue
        text = entry.get("text", "")
        predicted_tip = _predict_is_tip(text, overrides_path)
        is_tip = label in {"tip", "general", "good"}
        is_negative = label in {"not_tip", "narrative", "reference", "recipe_specific"}
        if not (is_tip or is_negative):
            skipped += 1
            continue
        total += 1
        if predicted_tip and is_tip:
            tp += 1
        elif predicted_tip and is_negative:
            fp += 1
        elif not predicted_tip and is_negative:
            tn += 1
        elif not predicted_tip and is_tip:
            fn += 1

    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    print(f"Labeled: {total} (skipped: {skipped})")
    print(f"TP: {tp}  FP: {fp}  TN: {tn}  FN: {fn}")
    print(f"Precision: {precision:.2f}")
    print(f"Recall: {recall:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Tip evaluation harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    template_parser = subparsers.add_parser("template", help="Create a labeling template")
    template_parser.add_argument("--input", required=True, type=Path)
    template_parser.add_argument("--out", required=True, type=Path)

    score_parser = subparsers.add_parser("score", help="Score labeled tips")
    score_parser.add_argument("--labels", required=True, type=Path)
    score_parser.add_argument("--overrides", type=Path)

    args = parser.parse_args()

    if args.command == "template":
        candidates = _load_topic_candidates(args.input)
        _write_labels_template(candidates, args.out)
    elif args.command == "score":
        score_labels(args.labels, args.overrides)


if __name__ == "__main__":
    main()
