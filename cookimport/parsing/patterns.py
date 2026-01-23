import re

# Quantity Patterns
# Matches: 1, 1.5, 1/2, 1-2, 1 1/2
QUANTITY_RE = re.compile(r"^\s*(\d+(\.\d+)?(\s*[-]\s*\d+(\.\d+)?)?(\s*/\s*\d+(\.\d+)?)?|\d+\s+\d+/\d+)", re.IGNORECASE)

# Unit Patterns
# Common cooking units
UNITS = [
    "cup", "cups", "c", "c.",
    "tablespoon", "tablespoons", "tbsp", "tbsp.", "tbs", "tbs.", "T", "T.",
    "teaspoon", "teaspoons", "tsp", "tsp.", "t", "t.",
    "gram", "grams", "g", "g.",
    "kilogram", "kilograms", "kg", "kg.",
    "ounce", "ounces", "oz", "oz.",
    "pound", "pounds", "lb", "lb.", "lbs", "lbs.",
    "milliliter", "milliliters", "ml", "ml.",
    "liter", "liters", "l", "l.",
    "pinch", "dash", "clove", "cloves", "slice", "slices",
    "can", "cans", "jar", "jars", "bottle", "bottles",
    "package", "packages", "pkg", "pkg.",
    "stick", "sticks"
]
# Create a joined regex for units: \b(cup|oz|...)\b
UNIT_RE = re.compile(r"\b(" + "|".join(re.escape(u) for u in UNITS) + r")\b", re.IGNORECASE)

# Header Patterns
INGREDIENT_HEADERS = [
    "ingredients", "for the filling", "for the dough", "for the sauce", 
    "filling", "crust", "topping", "dressing"
]
INSTRUCTION_HEADERS = [
    "instructions", "directions", "method", "preparation", "how to make", "steps"
]

# Time Patterns
TIME_RE = re.compile(r"(prep|cook|total|active)\s*time:", re.IGNORECASE)

# Yield Patterns
YIELD_RE = re.compile(r"(serves|yield|makes):?", re.IGNORECASE)

# Instruction Start Patterns
# Matches: 1., 1), Step 1:, A)
STEP_START_RE = re.compile(r"^(\d+\.|Step\s+\d+|[A-Z]\)|\d+\))", re.IGNORECASE)

# Imperative Verbs (strong signals for instructions)
IMPERATIVE_VERBS = [
    "add", "mix", "stir", "whisk", "beat", "bake", "boil", "fry", "sauté",
    "chop", "slice", "dice", "mince", "combine", "pour", "place", "set",
    "preheat", "grease", "line", "remove", "serve", "garnish"
]
