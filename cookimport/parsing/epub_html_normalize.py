from __future__ import annotations

from bs4 import BeautifulSoup, FeatureNotFound, NavigableString, Tag

_SPLIT_TAG_NAMES = {"p", "div", "li"}
_DROP_TAG_NAMES = {"script", "style", "noscript", "svg"}


def normalize_epub_html_for_unstructured(html: str, *, mode: str) -> str:
    """Normalize EPUB XHTML/HTML into structures that partition_html can split well."""
    selected_mode = _normalize_mode(mode)
    if selected_mode == "none":
        return html

    soup = _parse_html_document(html)

    _remove_noise_elements(soup)
    _split_br_blocks(soup)
    _remove_empty_split_tags(soup)
    return str(soup)


def _normalize_mode(mode: str) -> str:
    selected_mode = mode.strip().lower()
    if selected_mode == "semantic_v1":
        # Temporary alias while semantic_v1 evolves.
        return "br_split_v1"
    if selected_mode in {"none", "br_split_v1"}:
        return selected_mode
    raise ValueError(
        f"Unsupported EPUB HTML normalize mode: {mode!r}. "
        "Expected one of: none, br_split_v1, semantic_v1."
    )


def _parse_html_document(html: str) -> BeautifulSoup:
    try:
        soup = BeautifulSoup(html, "lxml")
    except FeatureNotFound:
        soup = BeautifulSoup(html, "html.parser")

    if soup.html is None:
        html_tag = soup.new_tag("html")
        body_tag = soup.new_tag("body")
        for node in list(soup.contents):
            body_tag.append(node.extract())
        html_tag.append(body_tag)
        soup.append(html_tag)
        return soup

    if soup.body is None:
        body_tag = soup.new_tag("body")
        for node in list(soup.html.contents):
            body_tag.append(node.extract())
        soup.html.append(body_tag)

    return soup


def _split_br_blocks(soup: BeautifulSoup) -> None:
    candidates = [
        tag
        for tag in soup.find_all(_is_split_candidate)
        if isinstance(tag, Tag)
    ]
    for tag in candidates:
        _split_tag_on_br(tag, soup)


def _remove_noise_elements(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        if not tag.name:
            continue
        if tag.name in _DROP_TAG_NAMES:
            tag.decompose()
            continue
        if _is_toc_nav(tag) or _is_pagebreak_tag(tag):
            tag.decompose()


def _is_split_candidate(tag: Tag) -> bool:
    if tag.name not in _SPLIT_TAG_NAMES:
        return False
    for child in tag.children:
        if isinstance(child, Tag) and child.name.lower() == "br":
            return True
    return False


def _is_toc_nav(tag: Tag) -> bool:
    if tag.name != "nav":
        return False
    type_tokens = _attr_tokens(tag, "epub:type") + _attr_tokens(tag, "type")
    role_tokens = _attr_tokens(tag, "role")
    return any(token in {"toc", "doc-toc", "navigation"} for token in type_tokens + role_tokens)


def _is_pagebreak_tag(tag: Tag) -> bool:
    type_tokens = _attr_tokens(tag, "epub:type") + _attr_tokens(tag, "type")
    role_tokens = _attr_tokens(tag, "role")
    class_tokens = [token.lower() for token in tag.get("class", [])]
    if any("pagebreak" in token for token in type_tokens):
        return True
    if any("doc-pagebreak" in token for token in role_tokens):
        return True
    if any("pagebreak" in token for token in class_tokens):
        return True
    return False


def _attr_tokens(tag: Tag, key: str) -> list[str]:
    attrs = getattr(tag, "attrs", None)
    if not isinstance(attrs, dict):
        return []
    raw = attrs.get(key)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = [raw]
    tokens: list[str] = []
    for value in values:
        text = str(value).strip().lower()
        if not text:
            continue
        tokens.extend(part for part in text.split() if part)
    return tokens


def _split_tag_on_br(tag: Tag, soup: BeautifulSoup) -> None:
    segments: list[list[Tag | NavigableString]] = []
    current: list[Tag | NavigableString] = []

    for child in list(tag.contents):
        node = child.extract()
        if isinstance(node, Tag) and node.name.lower() == "br":
            if _segment_has_content(current):
                segments.append(current)
            current = []
            continue
        current.append(node)

    if _segment_has_content(current):
        segments.append(current)

    if not segments:
        tag.decompose()
        return

    attrs = dict(tag.attrs)
    original_id = attrs.pop("id", None)

    tag.clear()
    tag.attrs.clear()
    for key, value in attrs.items():
        tag.attrs[key] = value
    if original_id is not None:
        tag.attrs["id"] = original_id
    for node in segments[0]:
        tag.append(node)

    insert_after = tag
    for segment in segments[1:]:
        sibling = soup.new_tag(tag.name)
        for key, value in attrs.items():
            sibling.attrs[key] = value
        for node in segment:
            sibling.append(node)
        insert_after.insert_after(sibling)
        insert_after = sibling


def _segment_has_content(segment: list[Tag | NavigableString]) -> bool:
    for node in segment:
        if isinstance(node, NavigableString):
            if str(node).strip():
                return True
            continue
        if node.get_text(strip=True):
            return True
    return False


def _remove_empty_split_tags(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all(_is_split_tag)):
        if not isinstance(tag, Tag):
            continue
        if tag.get_text(strip=True):
            continue
        tag.decompose()


def _is_split_tag(tag: Tag) -> bool:
    return tag.name in _SPLIT_TAG_NAMES
