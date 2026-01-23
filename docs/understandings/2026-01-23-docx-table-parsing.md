---
summary: "Docx tables are parsed row-wise using header aliases to recover fields."
read_when:
  - When debugging .docx imports that store recipes in tables
---

Word documents often store recipes in tables. The text importer now scans docx tables, detects header rows using the same header alias set as the Excel importer, and treats each data row as a recipe. This preserves ingredients/instructions instead of flattening table content into plain text.
