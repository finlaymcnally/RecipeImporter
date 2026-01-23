---
summary: "Headerless cookbook exports often use title + Serves lines to delimit recipes."
read_when:
  - When debugging text/docx imports with multiple recipes and no section headers
---

Some Word/Text cookbook exports are simple paragraph lists: a title line, a "Serves" line, ingredients, then instructions, repeated for each recipe. When explicit "Ingredients" headers are missing, splitting on repeated Serves/Yield lines (using the preceding title line as the start) and inferring ingredient vs. instruction blocks avoids collapsing the entire file into a single recipe.
