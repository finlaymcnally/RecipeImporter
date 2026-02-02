from __future__ import annotations

from functools import lru_cache
from typing import Any

try:
    import spacy
except Exception:  # pragma: no cover - optional dependency
    spacy = None


def spacy_available() -> bool:
    return spacy is not None


def warm_spacy_model() -> None:
    """Proactively load the spaCy pipeline."""
    _load_pipeline()


@lru_cache
def _load_pipeline() -> Any:
    if spacy is None:
        return None
    for model in ("en_core_web_sm", "en_core_web_md", "en_core_web_lg", "en_core_web_trf"):
        try:
            return spacy.load(model)
        except Exception:
            continue
    try:
        return spacy.blank("en")
    except Exception:
        return None


def analyze_text(text: str) -> dict[str, Any]:
    pipeline = _load_pipeline()
    if pipeline is None:
        return {}
    doc = pipeline(text)
    if not doc or not doc.has_annotation("POS"):
        return {}
    first_token = next((token for token in doc if not token.is_space), None)
    if first_token is None:
        return {}

    features = {
        "spacy_first_pos": first_token.pos_,
        "spacy_starts_with_verb": first_token.pos_ == "VERB",
    }
    if doc.has_annotation("TAG"):
        features["spacy_first_tag"] = first_token.tag_
    features["spacy_imperative"] = first_token.pos_ == "VERB"
    return features
