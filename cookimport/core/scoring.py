from __future__ import annotations

import re
from typing import List

from cookimport.core.models import RecipeCandidate
from cookimport.parsing import signals

def score_recipe_candidate(candidate: RecipeCandidate) -> float:
    """
    Calculates a confidence score (0.0 to 1.0) for a RecipeCandidate
    based on the presence and quality of its fields.
    """
    score = 0.0
    
    # 1. Title Quality (Max 0.2)
    # Penalize generic names or empty names
    if candidate.name:
        clean_name = candidate.name.strip()
        if clean_name and clean_name.lower() not in ("untitled recipe", "recipe"):
            # Check if it looks like a file path or generic ID
            if not re.search(r"\.\w{2,4}$", clean_name): # Not a filename
                score += 0.2
            else:
                score += 0.1 # Partial credit for having *something*
    
    # 2. Ingredients (Max 0.4)
    # We want a healthy list of ingredients.
    ing_count = len(candidate.ingredients)
    if ing_count > 0:
        # Check if ingredients look real (heuristics)
        # We can spot-check a few
        valid_looking = 0
        check_limit = min(ing_count, 5)
        for i in range(check_limit):
            line = candidate.ingredients[i]
            # Simple check: does it have a digit or unit-like word?
            # Or use signals if cheap.
            feats = signals.classify_block(line)
            if feats.get("is_ingredient_likely") or (feats.get("starts_with_quantity") and feats.get("has_unit")):
                valid_looking += 1
            elif feats.get("starts_with_quantity"):
                 # Partial credit? Maybe not.
                 # Let's trust is_ingredient_likely which is quantity AND unit.
                 # But sometimes "Salt" is an ingredient.
                 # Heuristic: if it's short and in an ingredient list, it's likely valid.
                 pass
            elif re.search(r"^\s*[-*•]", line):
                # Bullet point implies list item
                valid_looking += 1
        
        ratio = valid_looking / check_limit
        
        if ing_count >= 3:
            score += 0.3 * ratio
            score += 0.1 # Bonus for quantity
        else:
            score += 0.1 * ratio

    # 3. Instructions (Max 0.3)
    inst_count = len(candidate.instructions)
    if inst_count > 0:
        # Instructions should be sentence-like or imperative
        # If it's just one massive block, that's okay but less ideal than split steps
        score += 0.2
        if inst_count > 1:
            score += 0.1 # Bonus for structured steps
            
    # 4. Metadata (Max 0.1)
    if candidate.recipe_yield:
        score += 0.05
    if candidate.description:
        score += 0.05
        
    return round(max(0.0, min(1.0, score)), 2)

