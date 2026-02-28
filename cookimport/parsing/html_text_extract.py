from __future__ import annotations

import importlib
import re
from typing import Any

from bs4 import BeautifulSoup

_SUPPORTED_TEXT_EXTRACTORS = {
    "bs4",
    "trafilatura",
    "readability_lxml",
    "justext",
    "boilerpy3",
    "ensemble_v1",
}
_WEBSCHEMA_EXTRA = "webschema"
_INSTRUCTION_VERB_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|cook|bake|roast|fry|grill|season|"
    r"serve|add|melt|place|put|pour|combine|fold|remove|drain|peel|chop|slice|cut|"
    r"toss|cool|refrigerate|strain|beat|whip|simmer|boil|reduce|cover)\b",
    re.IGNORECASE,
)
_INGREDIENT_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?\d+(?:[./]\d+)?\s*(cup|cups|tbsp|tsp|teaspoon|tablespoon|"
    r"oz|ounce|ounces|lb|pound|gram|g|kg|ml|l)\b",
    re.IGNORECASE,
)


def extract_main_text_from_html(
    html_text: str,
    *,
    extractor: str = "bs4",
) -> tuple[str, dict[str, Any]]:
    """Extract deterministic fallback text from HTML."""

    selected = str(extractor or "bs4").strip().lower()
    if selected not in _SUPPORTED_TEXT_EXTRACTORS:
        raise RuntimeError(
            f"Unsupported web HTML text extractor {extractor!r}. "
            f"Expected one of: {', '.join(sorted(_SUPPORTED_TEXT_EXTRACTORS))}."
        )

    if selected != "ensemble_v1":
        text = _extract_single_backend(html_text, selected)
        score = _text_quality_score(text)
        return text, {
            "extractor_requested": selected,
            "extractor_used": selected,
            "quality_score": score,
        }

    candidates: list[tuple[float, str, str]] = []
    for backend in ("bs4", "trafilatura", "readability_lxml", "justext", "boilerpy3"):
        try:
            text = _extract_single_backend(html_text, backend)
        except RuntimeError:
            continue
        if not text:
            continue
        score = _text_quality_score(text)
        candidates.append((score, backend, text))

    if not candidates:
        return "", {
            "extractor_requested": selected,
            "extractor_used": "none",
            "quality_score": 0.0,
        }

    # Highest quality score wins, then longer text as deterministic tie-breaker.
    candidates.sort(key=lambda item: (item[0], len(item[2])), reverse=True)
    best_score, best_backend, best_text = candidates[0]
    return best_text, {
        "extractor_requested": selected,
        "extractor_used": best_backend,
        "quality_score": best_score,
        "candidate_count": len(candidates),
    }


def _extract_single_backend(html_text: str, backend: str) -> str:
    if backend == "bs4":
        return _extract_with_bs4(html_text)
    if backend == "trafilatura":
        return _extract_with_trafilatura(html_text)
    if backend == "readability_lxml":
        return _extract_with_readability_lxml(html_text)
    if backend == "justext":
        return _extract_with_justext(html_text)
    if backend == "boilerpy3":
        return _extract_with_boilerpy3(html_text)
    raise RuntimeError(f"Unsupported text extractor backend {backend!r}.")


def _extract_with_bs4(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "lxml")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    container = soup.find("article") or soup.body or soup
    return _normalize_text_block(container.get_text("\n"))


def _extract_with_trafilatura(html_text: str) -> str:
    trafilatura = _import_optional_dependency(
        "trafilatura",
        context="web_html_text_extractor=trafilatura",
    )
    extracted = trafilatura.extract(
        html_text,
        include_comments=False,
        include_tables=False,
    )
    return _normalize_text_block(extracted or "")


def _extract_with_readability_lxml(html_text: str) -> str:
    readability = _import_optional_dependency(
        "readability",
        context="web_html_text_extractor=readability_lxml",
    )
    document = readability.Document(html_text)
    summary_html = document.summary(html_partial=True)
    return _extract_with_bs4(summary_html)


def _extract_with_justext(html_text: str) -> str:
    justext = _import_optional_dependency(
        "justext",
        context="web_html_text_extractor=justext",
    )
    paragraphs = justext.justext(html_text, justext.get_stoplist("English"))
    lines = [
        str(paragraph.text).strip()
        for paragraph in paragraphs
        if not getattr(paragraph, "is_boilerplate", False)
        and str(getattr(paragraph, "text", "")).strip()
    ]
    return _normalize_text_block("\n".join(lines))


def _extract_with_boilerpy3(html_text: str) -> str:
    extractors = _import_optional_dependency(
        "boilerpy3.extractors",
        context="web_html_text_extractor=boilerpy3",
    )
    extractor = extractors.ArticleExtractor()
    text = extractor.get_content(html_text)
    return _normalize_text_block(text or "")


def _normalize_text_block(text: str) -> str:
    lines = [line.strip() for line in str(text).replace("\r", "\n").split("\n")]
    filtered: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if previous_blank:
                continue
            previous_blank = True
            filtered.append("")
            continue
        previous_blank = False
        filtered.append(line)
    return "\n".join(filtered).strip()


def _text_quality_score(text: str) -> float:
    if not text:
        return 0.0

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    char_count = len(text)
    line_count = len(lines)
    instruction_hits = sum(1 for line in lines if _INSTRUCTION_VERB_RE.match(line))
    ingredient_hits = sum(1 for line in lines if _INGREDIENT_LINE_RE.match(line))

    density = min(1.0, char_count / 6000.0)
    shape = min(1.0, line_count / 120.0)
    structure = min(1.0, (instruction_hits + ingredient_hits) / 24.0)
    score = (density * 0.45) + (shape * 0.30) + (structure * 0.25)
    if char_count < 120:
        score *= 0.35
    return round(score, 4)


def _import_optional_dependency(module_name: str, *, context: str):
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        package_hint = module_name.split(".", 1)[0]
        raise RuntimeError(
            f"Selected {context} requires optional dependency '{package_hint}'. "
            f"Install with: pip install -e '.[{_WEBSCHEMA_EXTRA}]'."
        ) from exc

