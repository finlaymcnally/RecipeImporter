from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Iterable

_SAFE_RESULT_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_UNSAFE_RESULT_ID_CHARS_RE = re.compile(r"[^A-Za-z0-9_-]+")
_COLLAPSE_DASHES_RE = re.compile(r"-{2,}")


def make_safe_label_studio_result_id(raw_id: str) -> str:
    raw_text = str(raw_id or "").strip()
    if raw_text and _SAFE_RESULT_ID_RE.fullmatch(raw_text):
        return raw_text
    digest = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:12]
    slug = _UNSAFE_RESULT_ID_CHARS_RE.sub("-", raw_text).strip("-_")
    slug = _COLLAPSE_DASHES_RE.sub("-", slug)
    if slug:
        slug = slug[:40].rstrip("-_")
        if slug:
            return f"{slug}-{digest}"
    return f"lsr-{digest}"


def sanitize_label_studio_result_ids(
    results: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    copied_results = [copy.deepcopy(result) for result in results if isinstance(result, dict)]
    used_ids: set[str] = set()
    id_map: dict[str, str] = {}

    for result in copied_results:
        raw_id = str(result.get("id") or "").strip()
        if not raw_id:
            continue
        candidate = make_safe_label_studio_result_id(raw_id)
        while candidate in used_ids:
            candidate = f"{candidate}-dup"
        used_ids.add(candidate)
        if candidate != raw_id:
            id_map[raw_id] = candidate
            result["id"] = candidate

    if not id_map:
        return copied_results

    for result in copied_results:
        for key in ("from_id", "to_id", "parentID", "parent_id"):
            value = result.get(key)
            if isinstance(value, str) and value in id_map:
                result[key] = id_map[value]
    return copied_results
