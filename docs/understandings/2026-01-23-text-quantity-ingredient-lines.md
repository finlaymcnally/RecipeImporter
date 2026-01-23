---
summary: "Quantity-only lines like \"2 eggs\" should be treated as ingredients."
read_when:
  - When debugging text imports with quantity-only ingredient lines
---

# Quantity-only ingredient lines

Text imports treat short lines that start with a quantity (but no unit) as ingredients when they are not time phrases (e.g., "2 eggs" -> ingredient, "2 minutes" -> not).
