"""Deterministic tag rules keyed by tag key_norm.

Each rule has:
  - patterns: list of {field, regex, weight, evidence}
  - exclude_patterns (optional): list of {field, regex} — if any match, suppress this tag
  - min_score: threshold (default 0.6)

Fields: title, description, notes, ingredients, instructions
"""

from __future__ import annotations

TAG_RULES: dict[str, dict] = {
    # -----------------------------------------------------------------------
    # Cooking Style
    # -----------------------------------------------------------------------
    "instant-pot": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\binstant pot\b", "weight": 0.8, "evidence": "matched 'instant pot' in title"},
            {"field": "instructions", "regex": r"\binstant pot\b", "weight": 0.5, "evidence": "matched 'instant pot' in instructions"},
            {"field": "instructions", "regex": r"\bpressure cook(?:er|ing)?\b", "weight": 0.3, "evidence": "matched pressure cook phrasing in instructions"},
            {"field": "instructions", "regex": r"\b(?:natural|quick)\s+release\b", "weight": 0.3, "evidence": "matched pressure release phrasing in instructions"},
        ],
    },
    "slow-cooker": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bslow\s*cook(?:er|ed)?\b|\bcrock[\s-]?pot\b", "weight": 0.8, "evidence": "matched slow cooker in title"},
            {"field": "instructions", "regex": r"\bslow\s*cook(?:er|ed|ing)?\b|\bcrock[\s-]?pot\b", "weight": 0.5, "evidence": "matched slow cooker in instructions"},
            {"field": "instructions", "regex": r"\bcook\s+on\s+(?:low|high)\s+for\s+\d+\s+hours\b", "weight": 0.4, "evidence": "matched slow-cooker timing pattern in instructions"},
        ],
    },
    "air-fryer": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bair\s*fr(?:yer|ied|y)\b", "weight": 0.8, "evidence": "matched air fryer in title"},
            {"field": "instructions", "regex": r"\bair\s*fr(?:yer|ied|y)\b", "weight": 0.5, "evidence": "matched air fryer in instructions"},
        ],
    },
    "grill": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bgrilled?\b", "weight": 0.7, "evidence": "matched grill in title"},
            {"field": "instructions", "regex": r"\b(?:preheat|heat)\s+(?:the\s+)?grill\b", "weight": 0.5, "evidence": "matched grill preheat in instructions"},
            {"field": "instructions", "regex": r"\bgrill(?:ed|ing)?\b", "weight": 0.3, "evidence": "matched grill in instructions"},
        ],
        "exclude_patterns": [
            {"field": "title", "regex": r"\bgrilled?\s+cheese\b"},
        ],
    },
    "sheet-pan": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsheet\s*pan\b", "weight": 0.8, "evidence": "matched sheet pan in title"},
            {"field": "instructions", "regex": r"\bsheet\s*pan\b|\bbaking\s+sheet\b", "weight": 0.4, "evidence": "matched sheet pan in instructions"},
        ],
    },
    "one-pot": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bone[\s-]pot\b|\bone[\s-]pan\b|\bone[\s-]skillet\b", "weight": 0.8, "evidence": "matched one-pot in title"},
            {"field": "description", "regex": r"\bone[\s-]pot\b|\bone[\s-]pan\b", "weight": 0.5, "evidence": "matched one-pot in description"},
        ],
    },
    "no-cook": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bno[\s-]cook\b|\bno[\s-]bake\b|\braw\b", "weight": 0.8, "evidence": "matched no-cook in title"},
            {"field": "description", "regex": r"\bno[\s-]cook\b|\bno[\s-]bake\b|\bno\s+cooking\s+required\b", "weight": 0.5, "evidence": "matched no-cook in description"},
        ],
    },
    "stovetop-only": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bstovetop\b", "weight": 0.7, "evidence": "matched stovetop in title"},
            {"field": "description", "regex": r"\bstovetop\s+only\b", "weight": 0.6, "evidence": "matched stovetop only in description"},
        ],
    },
    "oven-only": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\boven\b", "weight": 0.4, "evidence": "matched oven in title"},
            {"field": "description", "regex": r"\boven\s+only\b", "weight": 0.6, "evidence": "matched oven only in description"},
        ],
    },

    # -----------------------------------------------------------------------
    # Equipment
    # -----------------------------------------------------------------------
    "blender": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bblender\b|\bblend\s+until\b", "weight": 0.5, "evidence": "matched blender in instructions"},
            {"field": "title", "regex": r"\bblended\b|\bsmoothie\b", "weight": 0.4, "evidence": "matched blended/smoothie in title"},
        ],
        "exclude_patterns": [
            {"field": "instructions", "regex": r"\bimmersion\s+blender\b"},
        ],
    },
    "immersion-blender": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bimmersion\s+blender\b|\bstick\s+blender\b|\bhand\s+blender\b", "weight": 0.7, "evidence": "matched immersion blender in instructions"},
        ],
    },
    "food-processor": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bfood\s+processor\b", "weight": 0.7, "evidence": "matched food processor in instructions"},
        ],
    },
    "dutch-oven": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bdutch\s+oven\b", "weight": 0.7, "evidence": "matched dutch oven in instructions"},
            {"field": "title", "regex": r"\bdutch\s+oven\b", "weight": 0.7, "evidence": "matched dutch oven in title"},
        ],
    },
    "wok": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bwok\b", "weight": 0.6, "evidence": "matched wok in instructions"},
            {"field": "title", "regex": r"\bwok\b", "weight": 0.5, "evidence": "matched wok in title"},
        ],
    },
    "cast-iron": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bcast[\s-]iron\b", "weight": 0.7, "evidence": "matched cast iron in instructions"},
            {"field": "title", "regex": r"\bcast[\s-]iron\b", "weight": 0.6, "evidence": "matched cast iron in title"},
        ],
    },
    "stand-mixer": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bstand\s+mixer\b|\bkitchenaid\b", "weight": 0.7, "evidence": "matched stand mixer in instructions"},
        ],
    },
    "instant-pot-pressure-cooker": {
        "min_score": 0.7,
        "patterns": [
            {"field": "instructions", "regex": r"\bpressure\s+cook(?:er|ing)?\b", "weight": 0.6, "evidence": "matched pressure cooker in instructions"},
            {"field": "title", "regex": r"\bpressure\s+cook(?:er)?\b|\binstant\s+pot\b", "weight": 0.7, "evidence": "matched pressure cooker in title"},
        ],
    },
    "smoker": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsmoked?\b|\bsmoker\b", "weight": 0.6, "evidence": "matched smoker in title"},
            {"field": "instructions", "regex": r"\bsmoker\b|\bsmoking\s+chips\b|\bwood\s+chips\b", "weight": 0.5, "evidence": "matched smoker equipment in instructions"},
        ],
    },

    # -----------------------------------------------------------------------
    # Cooking Method
    # -----------------------------------------------------------------------
    "bake": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bbake\b|\bbaking\b|\bpreheat\s+(?:the\s+)?oven\b", "weight": 0.5, "evidence": "matched bake/oven preheat in instructions"},
            {"field": "title", "regex": r"\bbaked?\b", "weight": 0.4, "evidence": "matched bake in title"},
        ],
    },
    "roast": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\broast(?:ed)?\b", "weight": 0.6, "evidence": "matched roast in title"},
            {"field": "instructions", "regex": r"\broast(?:ed|ing)?\b", "weight": 0.4, "evidence": "matched roast in instructions"},
        ],
    },
    "steam": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bsteamed?\b", "weight": 0.6, "evidence": "matched steam in title"},
            {"field": "instructions", "regex": r"\bsteam(?:ed|ing|er)?\b", "weight": 0.4, "evidence": "matched steam in instructions"},
        ],
    },
    "simmer": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bsimmer(?:ed|ing)?\b", "weight": 0.6, "evidence": "matched simmer in instructions"},
            {"field": "title", "regex": r"\bsimmer(?:ed)?\b", "weight": 0.5, "evidence": "matched simmer in title"},
        ],
    },
    "saute": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bsaute(?:ed|d)?\b", "weight": 0.6, "evidence": "matched saute in title"},
            {"field": "instructions", "regex": r"\bsaute(?:ed?|ing|d)?\b", "weight": 0.6, "evidence": "matched saute in instructions"},
        ],
    },
    "braise": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bbraised?\b", "weight": 0.6, "evidence": "matched braise in title"},
            {"field": "instructions", "regex": r"\bbrais(?:e|ed|ing)\b", "weight": 0.4, "evidence": "matched braise in instructions"},
        ],
    },
    "pressure-cook": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bpressure\s+cook(?:er|ing)?\b", "weight": 0.6, "evidence": "matched pressure cook in instructions"},
            {"field": "instructions", "regex": r"\b(?:natural|quick)\s+release\b", "weight": 0.3, "evidence": "matched pressure release in instructions"},
        ],
    },
    "deep-fry": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bdeep[\s-]?fr(?:ied|y)\b", "weight": 0.7, "evidence": "matched deep fry in title"},
            {"field": "instructions", "regex": r"\bdeep[\s-]?fr(?:ied|y|ying)\b", "weight": 0.5, "evidence": "matched deep fry in instructions"},
        ],
    },
    "fry": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bfried\b|\bfry\b", "weight": 0.5, "evidence": "matched fry in title"},
            {"field": "instructions", "regex": r"\b(?:pan[\s-]?)?fr(?:y|ied|ying)\b", "weight": 0.4, "evidence": "matched fry in instructions"},
        ],
        "exclude_patterns": [
            {"field": "title", "regex": r"\bair[\s-]?fr(?:yer|ied|y)\b|\bstir[\s-]?fr(?:y|ied)\b|\bdeep[\s-]?fr(?:ied|y)\b"},
        ],
    },
    "smoke": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsmoked\b", "weight": 0.6, "evidence": "matched smoked in title"},
            {"field": "instructions", "regex": r"\bsmok(?:e|ed|ing)\b.*\b(?:hours?|minutes?|wood|chips)\b", "weight": 0.5, "evidence": "matched smoking method in instructions"},
        ],
    },
    "sous-vide": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsous[\s-]?vide\b", "weight": 0.8, "evidence": "matched sous vide in title"},
            {"field": "instructions", "regex": r"\bsous[\s-]?vide\b|\bimmersion\s+circulator\b", "weight": 0.6, "evidence": "matched sous vide in instructions"},
        ],
    },
    "broil": {
        "min_score": 0.6,
        "patterns": [
            {"field": "instructions", "regex": r"\bbroil(?:ed|ing|er)?\b", "weight": 0.5, "evidence": "matched broil in instructions"},
            {"field": "title", "regex": r"\bbroiled?\b", "weight": 0.6, "evidence": "matched broil in title"},
        ],
    },
    "poach": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bpoached?\b", "weight": 0.6, "evidence": "matched poach in title"},
            {"field": "instructions", "regex": r"\bpoach(?:ed|ing)?\b", "weight": 0.4, "evidence": "matched poach in instructions"},
        ],
    },
    "raw-no-cook": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\braw\b|\bno[\s-]cook\b", "weight": 0.7, "evidence": "matched raw/no-cook in title"},
        ],
    },

    # -----------------------------------------------------------------------
    # Effort
    # -----------------------------------------------------------------------
    "quick": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bquick\b|\b(?:15|20|25)[\s-]?min(?:ute)?s?\b", "weight": 0.6, "evidence": "matched quick/time in title"},
            {"field": "description", "regex": r"\bquick\b|\beasy\b", "weight": 0.3, "evidence": "matched quick/easy in description"},
        ],
        # Also triggered by numeric check in engine (total_time <= 25 min)
    },
    "hands-off-friendly": {
        "min_score": 0.6,
        "patterns": [
            {"field": "description", "regex": r"\bhands[\s-]off\b|\bset\s+(?:it\s+)?and\s+forget\b", "weight": 0.6, "evidence": "matched hands-off in description"},
            {"field": "instructions", "regex": r"\bset\s+(?:it\s+)?and\s+forget\b", "weight": 0.5, "evidence": "matched set and forget in instructions"},
        ],
        # Also triggered by attention_level == set_and_forget in engine
    },
    "minimal-prep": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bminimal\s+prep\b|\bno[\s-]prep\b", "weight": 0.7, "evidence": "matched minimal prep in title"},
            {"field": "description", "regex": r"\bminimal\s+prep\b|\bno\s+chopping\b|\bpre[\s-]chopped\b", "weight": 0.6, "evidence": "matched minimal prep in description"},
        ],
    },
    "beginner-friendly": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bbeginner\b|\beasy\b|\bsimple\b", "weight": 0.4, "evidence": "matched beginner/easy in title"},
            {"field": "description", "regex": r"\bbeginner\b|\bfor\s+beginners\b", "weight": 0.5, "evidence": "matched beginner in description"},
        ],
    },
    "weekend": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bweekend\b|\bsunday\b|\bsaturday\b", "weight": 0.5, "evidence": "matched weekend in title"},
            {"field": "description", "regex": r"\bweekend\s+project\b|\bweekend\s+cooking\b", "weight": 0.5, "evidence": "matched weekend in description"},
        ],
    },

    # -----------------------------------------------------------------------
    # Main Protein (ingredient-driven, conservative)
    # -----------------------------------------------------------------------
    "chicken": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bchicken\s+(?:breast|thigh|leg|wing|drumstick|tender|cutlet|pieces?)\b", "weight": 0.7, "evidence": "matched chicken cut in ingredients"},
            {"field": "ingredients", "regex": r"\bchicken\b", "weight": 0.4, "evidence": "matched 'chicken' in ingredients"},
            {"field": "title", "regex": r"\bchicken\b", "weight": 0.3, "evidence": "matched 'chicken' in title"},
        ],
    },
    "beef": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bbeef\s+(?:chuck|roast|stew|round|sirloin|tenderloin|brisket|short\s+ribs?|ground)\b|\bsteak\b|\bground\s+beef\b|\bbrisket\b|\bchuck\b|\bsirloin\b|\brib\s+eye\b|\btenderloin\b", "weight": 0.7, "evidence": "matched beef cut in ingredients"},
            {"field": "ingredients", "regex": r"\bbeef\b", "weight": 0.3, "evidence": "matched 'beef' in ingredients"},
            {"field": "title", "regex": r"\bbeef\b|\bsteak\b|\bbrisket\b", "weight": 0.3, "evidence": "matched beef in title"},
        ],
    },
    "pork": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bpork\b|\bbacon\b|\bham\b|\bsausage\b|\bpancetta\b|\bprosciutto\b", "weight": 0.7, "evidence": "matched pork in ingredients"},
            {"field": "title", "regex": r"\bpork\b|\bbacon\b", "weight": 0.3, "evidence": "matched pork in title"},
        ],
        "exclude_patterns": [
            {"field": "ingredients", "regex": r"\bturkey\s+bacon\b|\bchicken\s+sausage\b"},
        ],
    },
    "fish": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bsalmon\b|\btuna\b|\bcod\b|\btilapia\b|\bhalibut\b|\btrout\b|\bswordfish\b|\bbass\b|\bsnapper\b|\bmahi\b|\bfish\b", "weight": 0.7, "evidence": "matched fish in ingredients"},
            {"field": "title", "regex": r"\bsalmon\b|\btuna\b|\bcod\b|\bfish\b|\bhalibut\b", "weight": 0.3, "evidence": "matched fish in title"},
        ],
        "exclude_patterns": [
            {"field": "ingredients", "regex": r"\bfish\s+sauce\b"},
        ],
    },
    "shrimp": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bshrimp\b|\bprawns?\b", "weight": 0.7, "evidence": "matched shrimp in ingredients"},
            {"field": "title", "regex": r"\bshrimp\b|\bprawns?\b", "weight": 0.3, "evidence": "matched shrimp in title"},
        ],
    },
    "tofu": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\btofu\b", "weight": 0.7, "evidence": "matched tofu in ingredients"},
            {"field": "title", "regex": r"\btofu\b", "weight": 0.3, "evidence": "matched tofu in title"},
        ],
    },
    "chickpeas": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bchickpeas?\b|\bgarbanzo\b", "weight": 0.7, "evidence": "matched chickpeas in ingredients"},
            {"field": "title", "regex": r"\bchickpea\b|\bgarbanzo\b", "weight": 0.3, "evidence": "matched chickpeas in title"},
        ],
    },
    "lentils": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\blentils?\b", "weight": 0.7, "evidence": "matched lentils in ingredients"},
            {"field": "title", "regex": r"\blentil\b", "weight": 0.3, "evidence": "matched lentils in title"},
        ],
    },
    "eggs": {
        "min_score": 0.7,
        "patterns": [
            {"field": "ingredients", "regex": r"\beggs?\b", "weight": 0.4, "evidence": "matched eggs in ingredients"},
            {"field": "title", "regex": r"\begg\b|\bfrittata\b|\bomelette?\b|\bquiche\b|\bshakshuka\b", "weight": 0.5, "evidence": "matched egg dish in title"},
        ],
    },
    "lamb": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\blamb\b", "weight": 0.7, "evidence": "matched lamb in ingredients"},
            {"field": "title", "regex": r"\blamb\b", "weight": 0.3, "evidence": "matched lamb in title"},
        ],
    },
    "turkey": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bturkey\b", "weight": 0.7, "evidence": "matched turkey in ingredients"},
            {"field": "title", "regex": r"\bturkey\b", "weight": 0.3, "evidence": "matched turkey in title"},
        ],
    },
    "beans": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\b(?:black|kidney|pinto|navy|cannellini|white|lima)\s+beans?\b|\bbeans?\b", "weight": 0.6, "evidence": "matched beans in ingredients"},
            {"field": "title", "regex": r"\bbeans?\b", "weight": 0.3, "evidence": "matched beans in title"},
        ],
        "exclude_patterns": [
            {"field": "ingredients", "regex": r"\bgreen\s+beans?\b|\bstring\s+beans?\b|\bbean\s+sprouts?\b"},
        ],
    },
    "tempeh": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\btempeh\b", "weight": 0.7, "evidence": "matched tempeh in ingredients"},
            {"field": "title", "regex": r"\btempeh\b", "weight": 0.3, "evidence": "matched tempeh in title"},
        ],
    },
    "seitan": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bseitan\b", "weight": 0.7, "evidence": "matched seitan in ingredients"},
            {"field": "title", "regex": r"\bseitan\b", "weight": 0.3, "evidence": "matched seitan in title"},
        ],
    },

    # -----------------------------------------------------------------------
    # Main Carb (ingredient-driven, conservative)
    # -----------------------------------------------------------------------
    "rice": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\brice\b", "weight": 0.6, "evidence": "matched rice in ingredients"},
            {"field": "title", "regex": r"\brice\b|\brisotto\b|\bfried\s+rice\b|\bpaella\b|\bbiryani\b|\bpilaf\b", "weight": 0.4, "evidence": "matched rice dish in title"},
        ],
        "exclude_patterns": [
            {"field": "ingredients", "regex": r"\brice\s+(?:vinegar|wine)\b"},
        ],
    },
    "pasta-noodles": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bpasta\b|\bspaghetti\b|\bpenne\b|\blinguine\b|\bfettuccine\b|\bnoodles?\b|\bmacaroni\b|\brigatoni\b|\blasagna\b|\borzo\b|\bfusilli\b|\bravioli\b|\btortellini\b", "weight": 0.6, "evidence": "matched pasta/noodles in ingredients"},
            {"field": "title", "regex": r"\bpasta\b|\bnoodle\b|\bspaghetti\b|\blasagna\b|\bmac\s+(?:and|&|n)\s+cheese\b|\bramen\b|\bpad\s+thai\b|\budon\b|\blo\s+mein\b", "weight": 0.4, "evidence": "matched pasta dish in title"},
        ],
    },
    "potatoes": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bpotato(?:es)?\b", "weight": 0.6, "evidence": "matched potatoes in ingredients"},
            {"field": "title", "regex": r"\bpotato\b|\bmashed\b|\bhash\s+browns?\b|\bfries\b", "weight": 0.3, "evidence": "matched potato in title"},
        ],
        "exclude_patterns": [
            {"field": "ingredients", "regex": r"\bsweet\s+potato(?:es)?\b"},
        ],
    },
    "sweet-potatoes": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bsweet\s+potato(?:es)?\b|\byam\b", "weight": 0.6, "evidence": "matched sweet potatoes in ingredients"},
            {"field": "title", "regex": r"\bsweet\s+potato\b", "weight": 0.4, "evidence": "matched sweet potato in title"},
        ],
    },
    "tortillas": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\btortillas?\b", "weight": 0.6, "evidence": "matched tortillas in ingredients"},
            {"field": "title", "regex": r"\btacos?\b|\bburritos?\b|\bwrap\b|\bquesadillas?\b|\benchiladas?\b", "weight": 0.4, "evidence": "matched tortilla-based dish in title"},
        ],
    },
    "bread": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bbread\b|\bsandwich\b|\btoast\b|\bfocaccia\b|\bbaguette\b|\bciabatta\b|\bbrioche\b", "weight": 0.5, "evidence": "matched bread in title"},
            {"field": "ingredients", "regex": r"\bbread\b|\bbuns?\b|\brolls?\b", "weight": 0.4, "evidence": "matched bread in ingredients"},
        ],
    },
    "quinoa": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bquinoa\b", "weight": 0.7, "evidence": "matched quinoa in ingredients"},
            {"field": "title", "regex": r"\bquinoa\b", "weight": 0.3, "evidence": "matched quinoa in title"},
        ],
    },
    "couscous": {
        "min_score": 0.6,
        "patterns": [
            {"field": "ingredients", "regex": r"\bcouscous\b", "weight": 0.7, "evidence": "matched couscous in ingredients"},
            {"field": "title", "regex": r"\bcouscous\b", "weight": 0.3, "evidence": "matched couscous in title"},
        ],
    },

    # -----------------------------------------------------------------------
    # Storage & Meal Prep
    # -----------------------------------------------------------------------
    "freezer-friendly": {
        "min_score": 0.7,
        "patterns": [
            {"field": "notes", "regex": r"\bfreez(?:er|e|es|able)\b", "weight": 0.5, "evidence": "matched freezer in notes"},
            {"field": "description", "regex": r"\bfreez(?:er|e|es|able)\b", "weight": 0.5, "evidence": "matched freezer in description"},
            {"field": "title", "regex": r"\bfreezer\b", "weight": 0.5, "evidence": "matched freezer in title"},
        ],
    },
    "meal-prep-friendly": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bmeal\s+prep\b", "weight": 0.7, "evidence": "matched meal prep in title"},
            {"field": "description", "regex": r"\bmeal\s+prep\b", "weight": 0.5, "evidence": "matched meal prep in description"},
        ],
    },
    "make-ahead": {
        "min_score": 0.7,
        "patterns": [
            {"field": "notes", "regex": r"\bmake[\s-]ahead\b|\bprepare\s+in\s+advance\b", "weight": 0.6, "evidence": "matched make-ahead in notes"},
            {"field": "description", "regex": r"\bmake[\s-]ahead\b", "weight": 0.5, "evidence": "matched make-ahead in description"},
            {"field": "title", "regex": r"\bmake[\s-]ahead\b|\bovernight\b", "weight": 0.5, "evidence": "matched make-ahead in title"},
        ],
    },
    "batch-cooking": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bbatch\b", "weight": 0.5, "evidence": "matched batch in title"},
            {"field": "description", "regex": r"\bbatch\s+cook\b|\blarge\s+batch\b", "weight": 0.5, "evidence": "matched batch cooking in description"},
        ],
    },

    # -----------------------------------------------------------------------
    # Meal Type
    # -----------------------------------------------------------------------
    "breakfast": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bbreakfast\b|\bpancakes?\b|\bwaffles?\b|\boatmeal\b|\bcereal\b|\bfrench\s+toast\b|\bgranola\b", "weight": 0.6, "evidence": "matched breakfast dish in title"},
            {"field": "description", "regex": r"\bbreakfast\b", "weight": 0.4, "evidence": "matched breakfast in description"},
        ],
    },
    "dessert": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bdessert\b|\bcake\b|\bcookies?\b|\bbrownies?\b|\bpie\b|\btart\b|\bpudding\b|\bice\s+cream\b|\bcheesecake\b|\bmousse\b|\bfudge\b|\bsorbet\b", "weight": 0.6, "evidence": "matched dessert in title"},
            {"field": "description", "regex": r"\bdessert\b|\bsweet\s+treat\b", "weight": 0.3, "evidence": "matched dessert in description"},
        ],
    },
    "snack": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsnack\b|\btrail\s+mix\b|\benergy\s+(?:balls?|bites?|bars?)\b|\bgranola\s+bars?\b", "weight": 0.6, "evidence": "matched snack in title"},
            {"field": "description", "regex": r"\bsnack\b", "weight": 0.3, "evidence": "matched snack in description"},
        ],
    },

    # -----------------------------------------------------------------------
    # Course
    # -----------------------------------------------------------------------
    "appetizer": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bappetizer\b|\bstarter\b|\bhors\s+d\s*oeuvre\b|\bcrostini\b|\bbruschetta\b", "weight": 0.6, "evidence": "matched appetizer in title"},
            {"field": "description", "regex": r"\bappetizer\b|\bstarter\b", "weight": 0.4, "evidence": "matched appetizer in description"},
        ],
    },
    "side-dish": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bside\s+dish\b|\bside\b", "weight": 0.4, "evidence": "matched side dish in title"},
            {"field": "description", "regex": r"\bside\s+dish\b|\bside\b", "weight": 0.3, "evidence": "matched side dish in description"},
        ],
    },
    "sauce": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsauce\b|\bgravy\b|\bsalsa\b|\bpesto\b", "weight": 0.6, "evidence": "matched sauce in title"},
        ],
    },
    "drink": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bsmoothie\b|\bcocktail\b|\blemonade\b|\bjuice\b|\bdrink\b|\bbeverage\b|\blatte\b|\btea\b|\bcoffee\b", "weight": 0.6, "evidence": "matched drink in title"},
        ],
    },
    "condiment": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bcondiment\b|\brelish\b|\bchutney\b|\baioli\b|\bketchup\b|\bmustard\b|\bhot\s+sauce\b", "weight": 0.6, "evidence": "matched condiment in title"},
        ],
    },
    "dressing": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bdressing\b|\bvinaigrette\b", "weight": 0.7, "evidence": "matched dressing in title"},
        ],
    },

    # -----------------------------------------------------------------------
    # Dish Type
    # -----------------------------------------------------------------------
    "soup": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bsoup\b|\bbisque\b|\bchowder\b|\bgazpacho\b|\bminestrone\b|\bpho\b", "weight": 0.7, "evidence": "matched soup in title"},
        ],
    },
    "stew": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bstew\b|\bchili\b|\bgoulash\b|\btagine\b", "weight": 0.7, "evidence": "matched stew in title"},
        ],
    },
    "salad": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bsalad\b|\bslaw\b", "weight": 0.7, "evidence": "matched salad in title"},
        ],
    },
    "sandwich": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bsandwich\b|\bsub\b|\bhoagie\b|\bpanini\b|\bclub\b", "weight": 0.7, "evidence": "matched sandwich in title"},
        ],
    },
    "pasta": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bpasta\b|\bspaghetti\b|\blasagna\b|\bfettuccine\b|\bcarbonara\b|\bbolognese\b|\bmacaroni\b|\bcacio\b", "weight": 0.7, "evidence": "matched pasta dish in title"},
        ],
    },
    "curry": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bcurry\b|\bvindaloo\b|\btikka\s+masala\b|\bkorma\b", "weight": 0.7, "evidence": "matched curry in title"},
        ],
    },
    "casserole": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bcasserole\b|\bgratin\b|\bbake\b", "weight": 0.5, "evidence": "matched casserole in title"},
        ],
    },
    "stir-fry": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bstir[\s-]?fr(?:y|ied)\b", "weight": 0.8, "evidence": "matched stir fry in title"},
            {"field": "instructions", "regex": r"\bstir[\s-]?fr(?:y|ied|ying)\b", "weight": 0.4, "evidence": "matched stir fry in instructions"},
        ],
    },
    "tacos": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\btacos?\b", "weight": 0.8, "evidence": "matched tacos in title"},
        ],
    },
    "pizza": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bpizza\b|\bflatbread\b", "weight": 0.8, "evidence": "matched pizza in title"},
        ],
    },
    "bowl": {
        "min_score": 0.7,
        "patterns": [
            {"field": "title", "regex": r"\bbowl\b|\bbudda\s+bowl\b|\bgrain\s+bowl\b|\bpoke\s+bowl\b", "weight": 0.6, "evidence": "matched bowl in title"},
        ],
    },
    "rice-dish": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bfried\s+rice\b|\brisotto\b|\bpaella\b|\bbiryani\b|\bpilaf\b|\bjambalaya\b", "weight": 0.7, "evidence": "matched rice dish in title"},
        ],
    },
    "wrap": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bwrap\b|\bburritos?\b", "weight": 0.7, "evidence": "matched wrap in title"},
        ],
    },
    "baked-goods": {
        "min_score": 0.6,
        "patterns": [
            {"field": "title", "regex": r"\bmuffins?\b|\bscones?\b|\bbiscuits?\b|\bcroissants?\b|\brolls?\b|\bbread\b|\bcinnamon\s+rolls?\b", "weight": 0.6, "evidence": "matched baked goods in title"},
        ],
    },
}
