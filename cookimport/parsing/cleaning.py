import re
import unicodedata

_SOFT_HYPHEN = "\u00ad"
_ZERO_WIDTH_RE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
_EPUB_PUNCT_REPLACEMENTS = {
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "–": "-",
    "—": "-",
    "⁄": "/",
}


def normalize_text(text: str) -> str:
    """
    Main entry point for text cleaning.
    Applies unicode normalization, mojibake repair, and whitespace standardization.
    """
    if not text:
        return ""
    
    text = fix_mojibake(text)
    text = unicodedata.normalize("NFKC", text)
    text = standardize_whitespace(text)
    return text


def normalize_epub_text(text: str) -> str:
    """EPUB-specific normalization on top of shared text cleanup."""
    if not text:
        return ""

    text = fix_mojibake(text)
    text = text.replace(_SOFT_HYPHEN, "")
    text = _ZERO_WIDTH_RE.sub("", text)
    for bad, good in _EPUB_PUNCT_REPLACEMENTS.items():
        text = text.replace(bad, good)
    for fraction, ascii_fraction in _UNICODE_FRACTIONS.items():
        text = text.replace(fraction, ascii_fraction)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(_SOFT_HYPHEN, "")
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("⁄", "/")
    text = standardize_whitespace(text)
    return text


def fix_mojibake(text: str) -> str:
    """
    Fixes common mojibake encoding errors using heuristics.
    Replacements for Windows-1252 misinterpreted as UTF-8.
    """
    replacements = {
        "â€™": "'",
        "â€œ": '"',
        "â€\u009d": '"',  # Sometimes appears as â€” followed by control char
        "â€“": "-",
        "â€”": "-",
        "Â": " ",     # Often appears before non-breaking space
        "â€¦": "...",
        "Ã©": "é",
        "Ã¨": "è",
        "Ã®": "î",
        "Ã": "à",      # Incomplete, but common prefix
    }
    
    for bad, good in replacements.items():
        text = text.replace(bad, good)
        
    return text

def standardize_whitespace(text: str) -> str:
    """
    Collapses multiple spaces, standardizes line endings, strips control chars.
    """
    # Replace non-breaking spaces
    text = text.replace("\u00a0", " ")
    
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    
    # Collapse horizontal whitespace (except newlines)
    # This regex matches any whitespace that is NOT a newline
    text = re.sub(r"[^\S\n]+", " ", text)
    
    # Strip leading/trailing whitespace per line
    lines = [line.strip() for line in text.split("\n")]
    
    return "\n".join(lines).strip()

def repair_hyphenation(text: str) -> str:
    """
    Rejoins words split across lines (e.g., 'ingre-\ndient' -> 'ingredient').
    Simple heuristic: if line ends with -, and next line starts with lowercase letter.
    """
    lines = text.split("\n")
    output = []
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Check if this line ends with a hyphen and there is a next line
        if line.endswith("-") and i + 1 < len(lines):
            next_line = lines[i+1]
            
            # Simple check: next line starts with lowercase (part of same word)
            # This avoids joining list items like "- Milk"
            if next_line and next_line[0].islower():
                # Remove hyphen and join
                combined = line[:-1] + next_line
                output.append(combined)
                i += 2 # Skip next line
                continue
        
        output.append(line)
        i += 1
        
    return "\n".join(output)
