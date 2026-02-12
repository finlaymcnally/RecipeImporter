"""Category policies: single vs multi, thresholds, max tags.

Rules:
  - single: pick only the highest-confidence tag if above threshold
  - multi: pick all tags above threshold, up to max_tags
"""

from __future__ import annotations

CATEGORY_POLICIES: dict[str, dict] = {
    # Single-pick categories (at most one tag)
    "main-protein": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},
    "main-carb": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},
    "meal-type": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},
    "course": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},

    # Multi-pick categories
    "cooking-style": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "equipment": {"mode": "multi", "min_confidence": 0.6, "max_tags": 4},
    "cooking-method": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "effort": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "storage": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "dish-type": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},
    "occasion": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},

    # Categories left for LLM (no deterministic rules yet, but policy still applies)
    "cuisine": {"mode": "multi", "min_confidence": 0.6, "max_tags": 2},
    "dietary": {"mode": "multi", "min_confidence": 0.6, "max_tags": 5},
    "flavor-profile": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "heat-source": {"mode": "single", "min_confidence": 0.6, "max_tags": 1},
    "vibe": {"mode": "multi", "min_confidence": 0.6, "max_tags": 3},
    "season": {"mode": "multi", "min_confidence": 0.6, "max_tags": 2},
    "holiday": {"mode": "multi", "min_confidence": 0.6, "max_tags": 2},
    "techniques": {"mode": "multi", "min_confidence": 0.6, "max_tags": 4},
}

DEFAULT_POLICY = {"mode": "multi", "min_confidence": 0.6, "max_tags": 3}


def get_policy(category_key: str) -> dict:
    return CATEGORY_POLICIES.get(category_key, DEFAULT_POLICY)
