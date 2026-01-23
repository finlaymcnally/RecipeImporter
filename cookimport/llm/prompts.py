SYSTEM_PROMPT = """You are a precise data extraction assistant specialized in cookbooks.
You output strict JSON that matches the provided schema.
Do not include markdown formatting (like ```json ... ```) in your response, just the raw JSON string.
Do not invent information. If a field is missing, omit it or use null.
"""

REPAIR_TEMPLATE = """
Context:
The following text is from a cookbook. It may contain parsing errors, weird layout, or mixed content.
Your task is to extract a structured recipe from it.

Input Text:
---------------------
{text_block}
---------------------

Hints:
{hints}

Output Schema (JSON):
{schema}

Please extract the recipe data into the JSON format above.
"""
