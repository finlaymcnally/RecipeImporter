from typing import Any, Dict, List, Union

from cookimport.core.blocks import Block
from cookimport.parsing import patterns

def classify_block(block: Union[str, Block]) -> Dict[str, Any]:
    """
    Analyzes a text block and returns a dictionary of signal features.
    Accepts either a raw string or a Block object.
    """
    text = block.text if isinstance(block, Block) else str(block)
    features = {}

    # 1. Ingredient Signals
    features["starts_with_quantity"] = bool(patterns.QUANTITY_RE.match(text))
    features["has_unit"] = bool(patterns.UNIT_RE.search(text))
    
    # Simple heuristic for ingredient likelihood
    # If it has quantity AND unit, it's very likely an ingredient
    features["is_ingredient_likely"] = features["starts_with_quantity"] and features["has_unit"]
    
    # 2. Instruction Signals
    features["starts_with_number"] = bool(patterns.STEP_START_RE.match(text))
    
    # Check for imperative verbs at the start (allow for "First, mix..." or "Then add...")
    words = text.lower().split()
    # Check first 3 words
    found_verb = False
    for i in range(min(3, len(words))):
        clean_word = words[i].strip(".,:;")
        if clean_word in patterns.IMPERATIVE_VERBS:
            found_verb = True
            break
    features["has_imperative_verb"] = found_verb
    
    features["is_instruction_likely"] = features["starts_with_number"] or features["has_imperative_verb"]

    # 3. Structure Signals
    lower_text = text.lower().strip()
    
    # Header detection
    is_short = len(text) < 50
    is_title_case = text.istitle()
    has_keyword = (lower_text in patterns.INGREDIENT_HEADERS or 
                   lower_text in patterns.INSTRUCTION_HEADERS or 
                   lower_text.endswith(":"))
                   
    features["is_header_likely"] = is_short and (is_title_case or has_keyword)
    features["is_ingredient_header"] = lower_text in patterns.INGREDIENT_HEADERS
    features["is_instruction_header"] = lower_text in patterns.INSTRUCTION_HEADERS

    # Metadata
    features["is_yield"] = bool(patterns.YIELD_RE.match(text))
    features["is_time"] = bool(patterns.TIME_RE.match(text))

    return features

def enrich_block(block: Block):
    """
    In-place update of a Block object with calculated features.
    """
    feats = classify_block(block.text)
    for k, v in feats.items():
        block.add_feature(k, v)
