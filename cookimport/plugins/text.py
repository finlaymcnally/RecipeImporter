from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

try:
    import docx
except ImportError:
    docx = None

from cookimport import __version__
from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RecipeCandidate,
    SkippedRow,
    WorkbookInspection,
    SheetInspection,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
    generate_recipe_id,
)
from cookimport.parsing import cleaning, signals
from cookimport.parsing.tips import extract_tips_from_candidate
from cookimport.plugins import registry

logger = logging.getLogger(__name__)

# Constants for splitting
_SPLIT_DELIMITER_RE = re.compile(r"\n={3,}\s*(?:RECIPE)?\s*={3,}\n", re.IGNORECASE)
_MARKDOWN_HEADER_RE = re.compile(r"^#+\s+(.+)$", re.MULTILINE)
# Matches "1. Title" or "10. Title" at start of line
_NUMBERED_TITLE_RE = re.compile(r"^\d+\.\s+([^\n]+)$", re.MULTILINE)
_YIELD_LINE_RE = re.compile(r"^\s*(serves|yield|yields|makes)\b", re.IGNORECASE)
_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|crush|cook|bake|roast|fry|grill|"
    r"blanch|season|serve|add|melt|place|put|pour|combine|fold|return|remove|drain|"
    r"peel|chop|slice|cut|toss|leave|cool|refrigerate|strain|set|beat|whip|simmer|"
    r"boil|reduce|cover|unwrap|sear|saute)\b",
    re.IGNORECASE,
)

_TABLE_HEADER_ALIASES = {
    "name": ["name", "title", "recipe", "recipe name"],
    "ingredients": ["ingredients", "ingredient", "ingredient list", "recipe/ingredients"],
    "instructions": ["instructions", "instruction", "steps", "method", "directions"],
    "description": ["description", "notes", "headnote"],
    "recipeYield": ["yield", "servings", "serves"],
    "sourceUrl": ["url", "source", "link"],
    "tags": ["tags", "keywords", "categories", "cuisine", "type", "tool"],
}

_SECTION_HEADER_RE = re.compile(
    r"^\s*(ingredients?|instructions?|directions?|method|steps?|preparation|notes?|tips?)\s*:?\s*$",
    re.IGNORECASE,
)

_TABLE_ALIAS_LOOKUP: dict[str, str] = {}


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def _table_alias_lookup() -> dict[str, str]:
    if _TABLE_ALIAS_LOOKUP:
        return _TABLE_ALIAS_LOOKUP
    for field, aliases in _TABLE_HEADER_ALIASES.items():
        for alias in aliases:
            _TABLE_ALIAS_LOOKUP[_normalize_label(alias)] = field
    return _TABLE_ALIAS_LOOKUP


def _split_lines(value: Any, delimiters: list[str]) -> list[str]:
    if value is None:
        return []
    text = cleaning.normalize_text(str(value))
    for delim in delimiters:
        if delim and delim != "\n":
            text = text.replace(delim, "\n")
    lines = text.split("\n")
    return [line.strip() for line in lines if line and line.strip()]


def _normalize_ingredient_line(line: str) -> str:
    return re.sub(r"^\s*[-*]+\s+", "", line).strip()


def _normalize_instruction_line(line: str) -> str:
    cleaned = re.sub(r"^\s*[-*]+\s+", "", line)
    cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned)
    return cleaned.strip()


def _split_ingredients(value: Any, mapping: MappingConfig | None) -> list[str]:
    delimiters = mapping.ingredient_delimiters if mapping else ["\n"]
    lines = _split_lines(value, delimiters)
    return [_normalize_ingredient_line(line) for line in lines if _normalize_ingredient_line(line)]


def _split_instructions(value: Any, mapping: MappingConfig | None) -> list[str]:
    delimiters = mapping.instruction_delimiters if mapping else ["\n"]
    lines = _split_lines(value, delimiters)
    return [
        _normalize_instruction_line(line) for line in lines if _normalize_instruction_line(line)
    ]


def _extract_sections_from_blob(text: str) -> dict[str, list[str]]:
    normalized = cleaning.normalize_text(str(text))
    lines = normalized.split("\n")
    sections: dict[str, list[str]] = {
        "ingredients": [],
        "instructions": [],
        "notes": [],
    }
    current_section: str | None = None
    found_any_header = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        match = _SECTION_HEADER_RE.match(stripped)
        if match:
            header = match.group(1).lower()
            found_any_header = True
            if header in ("ingredient", "ingredients"):
                current_section = "ingredients"
            elif header in (
                "instruction",
                "instructions",
                "direction",
                "directions",
                "method",
                "step",
                "steps",
                "preparation",
            ):
                current_section = "instructions"
            elif header in ("note", "notes", "tip", "tips"):
                current_section = "notes"
            continue

        if current_section == "ingredients":
            normalized_line = _normalize_ingredient_line(stripped)
            if normalized_line:
                sections["ingredients"].append(normalized_line)
        elif current_section == "instructions":
            normalized_line = _normalize_instruction_line(stripped)
            if normalized_line:
                sections["instructions"].append(normalized_line)
        elif current_section == "notes":
            sections["notes"].append(stripped)

    if not found_any_header:
        return {}
    return sections


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    raw = re.split(r",|\n", str(value))
    tags = [cleaning.normalize_text(tag) for tag in raw if str(tag).strip()]
    return [tag for tag in tags if tag]


def _extract_yield_phrase(line: str) -> str | None:
    match = _YIELD_LINE_RE.match(line)
    if not match:
        return None
    remainder = line[match.end():].strip(" :-")
    return remainder or line.strip()


def _is_ingredient_like(line: str, feats: dict[str, Any] | None = None) -> bool:
    if feats is None:
        feats = signals.classify_block(line)
    if feats.get("is_ingredient_likely"):
        return True
    if feats.get("starts_with_quantity") and not feats.get("is_instruction_likely"):
        word_count = len(line.split())
        if word_count <= 5 and not feats.get("is_time"):
            return True
    if feats.get("has_unit") and not feats.get("is_instruction_likely"):
        return True
    if re.match(r"^\s*[-*•]\s+", line):
        return True
    return False


def _is_instruction_like(line: str, feats: dict[str, Any] | None = None) -> bool:
    if feats is None:
        feats = signals.classify_block(line)
    if feats.get("is_instruction_likely"):
        return True
    if feats.get("is_ingredient_likely"):
        return False
    if _INSTRUCTION_LEAD_RE.match(line):
        return True
    word_count = len(line.split())
    if word_count >= 8 and re.search(r"[.!?]$", line.strip()):
        return True
    if word_count >= 10 and "," in line:
        return True
    return False


def _is_title_candidate(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return False
    if _YIELD_LINE_RE.match(stripped):
        return False
    if _is_ingredient_like(stripped):
        return False
    return stripped[0].isupper() or stripped.isupper()


def _find_recipe_starts_by_yield(lines: list[str]) -> list[int]:
    starts: list[int] = []
    for idx, line in enumerate(lines):
        if not _YIELD_LINE_RE.match(line):
            continue
        prev = idx - 1
        while prev >= 0 and not lines[prev].strip():
            prev -= 1
        if prev >= 0 and _is_title_candidate(lines[prev]):
            starts.append(prev)
    if starts and starts[0] != 0:
        starts.insert(0, 0)
    return sorted(set(starts))


def _detect_docx_header_row(rows: list[list[str]]) -> int | None:
    lookup = _table_alias_lookup()
    best_idx: int | None = None
    best_score = 0
    for idx, row in enumerate(rows[:5]):
        matched_fields = {
            lookup.get(_normalize_label(cell))
            for cell in row
            if lookup.get(_normalize_label(cell))
        }
        score = len(matched_fields)
        if score > best_score:
            best_score = score
            best_idx = idx
    if best_score >= 2:
        return best_idx
    return None


def _build_docx_table_provenance(
    path: Path,
    table_name: str,
    row_index: int,
    headers: list[str],
    row_payload: dict[str, Any],
) -> dict[str, Any]:
    timestamp = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    if timestamp.endswith("+00:00"):
        timestamp = timestamp[:-6] + "Z"
    return {
        "file_path": str(path),
        "workbook": path.name,
        "sheet": table_name,
        "row_index": row_index,
        "original_headers": headers,
        "original_row": row_payload,
        "import_timestamp": timestamp,
        "converter_version": __version__,
        "extraction_method": "docx_table",
    }


class TextImporter:
    name = "text"

    def detect(self, path: Path) -> float:
        """
        Returns confidence that this is a text file we can handle.
        """
        suffix = path.suffix.lower()
        if suffix in {'.txt', '.md', '.markdown'}:
            return 0.9
        if suffix == '.docx' and docx is not None:
            return 0.95
        if suffix == '.doc':
            # Low confidence for legacy doc, likely to fail or be treated as text junk
            return 0.1
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        """
        Analyzes the text file to determine structure (single vs multi-recipe).
        Reuses WorkbookInspection for consistency, treating the file as one 'sheet'.
        """
        try:
            if path.suffix.lower() == ".docx" and docx is not None:
                doc = docx.Document(path)
                table_rows = self._extract_docx_tables(doc)
                if table_rows:
                    recipe_rows = 0
                    tables_with_headers = 0
                    for rows in table_rows:
                        header_idx = _detect_docx_header_row(rows)
                        if header_idx is None:
                            continue
                        tables_with_headers += 1
                        recipe_rows += sum(
                            1
                            for row in rows[header_idx + 1 :]
                            if any(cell.strip() for cell in row)
                        )
                    if recipe_rows:
                        return WorkbookInspection(
                            path=str(path),
                            sheets=[
                                SheetInspection(
                                    name=path.name,
                                    layout="docx-table",
                                    headerRow=None,
                                    confidence=0.85,
                                    warnings=[
                                        f"Detected {recipe_rows} recipe row(s) across {tables_with_headers} table(s)."
                                    ],
                                )
                            ],
                            mappingStub=MappingConfig(),
                        )

            text = self._extract_text(path)
        except Exception as e:
            return WorkbookInspection(
                path=str(path),
                sheets=[],
                mappingStub=MappingConfig(),
                warnings=[f"Failed to read file: {e}"]
            )

        normalized = cleaning.normalize_text(text)
        
        candidates = self._split_recipes(normalized)
        recipe_count = len(candidates)
        
        # We'll treat the file as having one "sheet" named after the file
        sheet_name = path.name
        
        # Heuristic layout detection
        layout = "single-recipe" if recipe_count == 1 else "multi-recipe"
        
        return WorkbookInspection(
            path=str(path),
            sheets=[
                SheetInspection(
                    name=sheet_name,
                    layout=layout,
                    headerRow=None,
                    confidence=0.8,  # Arbitrary high confidence
                    warnings=[f"Detected {recipe_count} recipe candidate(s)."],
                )
            ],
            mappingStub=MappingConfig(),
        )

    def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
        """
        Converts the text file into RecipeCandidates.
        """
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        
        try:
            if path.suffix.lower() == ".docx" and docx is not None:
                table_recipes, table_report = self._convert_docx_tables(path, mapping)
                if table_recipes:
                    tips: list[Any] = []
                    for recipe in table_recipes:
                        tips.extend(extract_tips_from_candidate(recipe))
                    table_report.total_tips = len(tips)
                    if tips:
                        table_report.tip_samples = [
                            {"text": tip.text[:80]} for tip in tips[:3]
                        ]
                    return ConversionResult(
                        recipes=table_recipes,
                        tips=tips,
                        report=table_report,
                        workbook=path.stem,
                        workbookPath=str(path),
                    )

            raw_text = self._extract_text(path)
            file_hash = compute_file_hash(path)
            normalized = cleaning.normalize_text(raw_text)
            
            # 1. Split
            chunks = self._split_recipes(normalized)
            
            # 2. Parse each chunk
            for i, (chunk_text, line_range) in enumerate(chunks):
                try:
                    candidate = self._parse_chunk(chunk_text)
                    
                    # Add provenance
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method="heuristic_text",
                    )
                    
                    provenance = provenance_builder.build(
                        confidence_score=0.8, # TODO: Calculate based on signal strength
                        location={
                            "start_line": line_range[0],
                            "end_line": line_range[1],
                            "chunk_index": i
                        }
                    )
                    candidate.provenance = provenance
                    
                    # Add generic ID if none
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "text", file_hash, f"chunk_{i}"
                        )
                        
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to parse chunk {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse chunk {i}: {e}")
            
            tips: list[Any] = []
            for recipe in recipes:
                tips.extend(extract_tips_from_candidate(recipe))

            report.total_recipes = len(recipes)
            report.total_tips = len(tips)
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]
            if tips:
                report.tip_samples = [{"text": tip.text[:80]} for tip in tips[:3]]
                
            return ConversionResult(
                recipes=recipes,
                tips=tips,
                report=report,
                workbook=path.stem, # Using stem as "workbook" name
                workbookPath=str(path),
            )
            
        except Exception as e:
            logger.error(f"Fatal error converting {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                tips=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

    def _extract_text(self, path: Path) -> str:
        """
        Extracts text content from the file, handling .docx and fallback for .doc.
        """
        suffix = path.suffix.lower()
        
        if suffix == '.docx':
            if docx is None:
                raise ImportError("python-docx is required for .docx files. Install it with 'pip install python-docx'.")
            try:
                doc = docx.Document(path)
                return "\n".join([p.text for p in doc.paragraphs])
            except Exception as e:
                raise ValueError(f"Failed to read .docx file: {e}")
                
        elif suffix == '.doc':
            # Attempt basic text read, but likely to fail for binary
            try:
                # Try reading as text (some .doc are actually text/rtf)
                return path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                # If that fails or produces binary garbage, we might need a better heuristic
                # For now, just warn/fail.
                # Check for binary signature maybe?
                raise ValueError("Legacy .doc files (binary) are not fully supported. Please convert to .docx or text.")
        
        # Default text read
        return path.read_text(encoding="utf-8", errors="replace")

    def _extract_docx_tables(self, doc) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []
        for table in doc.tables:
            rows: list[list[str]] = []
            for row in table.rows:
                cells = [cleaning.normalize_text(cell.text) for cell in row.cells]
                if any(cell.strip() for cell in cells):
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables

    def _convert_docx_tables(
        self,
        path: Path,
        mapping: MappingConfig | None,
    ) -> tuple[list[RecipeCandidate], ConversionReport]:
        report = ConversionReport()
        if docx is None:
            return [], report

        try:
            doc = docx.Document(path)
        except Exception as e:
            report.errors.append(f"Failed to read .docx file: {e}")
            return [], report

        tables = self._extract_docx_tables(doc)
        if not tables:
            return [], report

        file_hash = compute_file_hash(path)
        recipes: list[RecipeCandidate] = []

        for table_idx, rows in enumerate(tables):
            header_idx = _detect_docx_header_row(rows)
            table_name = f"table_{table_idx + 1}"
            if header_idx is None:
                report.warnings.append(f"No header row detected for {table_name}.")
                continue

            headers = rows[header_idx]
            lookup = _table_alias_lookup()
            field_by_col: dict[int, str] = {}
            for idx, header in enumerate(headers):
                field = lookup.get(_normalize_label(header))
                if field:
                    field_by_col[idx] = field

            if not field_by_col:
                report.warnings.append(f"No recognizable headers found for {table_name}.")
                continue

            table_recipe_count = 0
            for row_idx, row in enumerate(rows[header_idx + 1 :], start=header_idx + 1):
                if not any(cell.strip() for cell in row):
                    continue

                row_payload: dict[str, Any] = {}
                for idx, header in enumerate(headers):
                    if idx < len(row) and header:
                        row_payload[header] = row[idx]

                fields: dict[str, Any] = {}
                all_tags: list[str] = []
                for idx, field in field_by_col.items():
                    if idx < len(row):
                        val = row[idx]
                        if field == "tags":
                            all_tags.extend(_normalize_tags(val))
                        else:
                            fields[field] = val
                if all_tags:
                    fields["tags"] = all_tags

                name = fields.get("name")
                raw_ingredients = fields.get("ingredients")
                raw_instructions = fields.get("instructions")

                if raw_ingredients and not raw_instructions:
                    sections = _extract_sections_from_blob(str(raw_ingredients))
                    if sections.get("instructions"):
                        ingredients = sections["ingredients"]
                        instructions = sections["instructions"]
                        notes_text = "\n".join(sections.get("notes", []))
                    else:
                        ingredients = _split_ingredients(raw_ingredients, mapping)
                        instructions = []
                        notes_text = ""
                else:
                    ingredients = _split_ingredients(raw_ingredients, mapping)
                    instructions = _split_instructions(raw_instructions, mapping)
                    notes_text = ""

                description = (
                    cleaning.normalize_text(str(fields.get("description")))
                    if fields.get("description")
                    else None
                )
                if notes_text:
                    if description:
                        description = f"{description}\n\n{notes_text}"
                    else:
                        description = notes_text
                recipe_yield = (
                    cleaning.normalize_text(str(fields.get("recipeYield")))
                    if fields.get("recipeYield")
                    else None
                )
                source_url = (
                    cleaning.normalize_text(str(fields.get("sourceUrl")))
                    if fields.get("sourceUrl")
                    else None
                )
                tags = _normalize_tags(fields.get("tags"))

                if not name or not str(name).strip():
                    report.skipped_rows.append(
                        SkippedRow(sheet=table_name, rowIndex=row_idx, reason="Missing name.")
                    )
                    report.missing_field_counts["name"] = (
                        report.missing_field_counts.get("name", 0) + 1
                    )
                    continue

                if not ingredients:
                    report.missing_field_counts["ingredients"] = (
                        report.missing_field_counts.get("ingredients", 0) + 1
                    )
                if not instructions:
                    report.missing_field_counts["instructions"] = (
                        report.missing_field_counts.get("instructions", 0) + 1
                    )

                provenance = _build_docx_table_provenance(
                    path,
                    table_name,
                    row_idx,
                    headers,
                    row_payload,
                )

                recipe = RecipeCandidate(
                    name=str(name),
                    ingredients=ingredients,
                    instructions=instructions,
                    description=description,
                    recipeYield=recipe_yield,
                    sourceUrl=source_url,
                    tags=tags,
                    provenance=provenance,
                )
                if not recipe.identifier:
                    recipe.identifier = generate_recipe_id(
                        "docx_table",
                        file_hash,
                        f"{table_name}_r{row_idx}",
                    )
                recipes.append(recipe)
                table_recipe_count += 1

            report.per_sheet_counts[table_name] = report.per_sheet_counts.get(
                table_name, 0
            ) + table_recipe_count

        report.total_recipes = len(recipes)
        if recipes:
            report.samples = [{"name": r.name} for r in recipes[:3]]

        return recipes, report

    def _split_recipes(self, text: str) -> List[Tuple[str, Tuple[int, int]]]:
        """
        Splits text into recipe chunks.
        Returns list of (text_chunk, (start_line, end_line)).
        """
        lines = text.splitlines()
        yield_starts = _find_recipe_starts_by_yield(lines)
        if len(yield_starts) > 1:
            return self._split_by_line_indices(text, yield_starts)

        # Strategy 1: Explicit delimiters
        if _SPLIT_DELIMITER_RE.search(text):
            return self._split_by_regex(text, _SPLIT_DELIMITER_RE)
            
        # Strategy 2: Markdown Headers (if multiple H1s are present)
        h1_matches = list(_MARKDOWN_HEADER_RE.finditer(text))
        if len(h1_matches) > 1:
            # Check if they look like recipe titles (not too long)
            # This is a simplification; we might assume top-level headers are recipes
            return self._split_by_positions(text, [m.start() for m in h1_matches])

        # Strategy 3: Numbered List of Titles (e.g. "1. Recipe Name")
        # Heuristic: If we see multiple numbered items, and NO ingredients headers,
        # it's likely a list of recipes/ideas.
        numbered_matches = list(_NUMBERED_TITLE_RE.finditer(text))
        has_ingredients = re.search(r"^Ingredients\b", text, re.IGNORECASE | re.MULTILINE)
        
        if len(numbered_matches) > 1 and not has_ingredients:
            return self._split_by_positions(text, [m.start() for m in numbered_matches])
            
        # Strategy 4: Default to single recipe
        return [(text, (1, len(text.splitlines())))]

    def _split_by_regex(self, text: str, pattern: re.Pattern) -> List[Tuple[str, Tuple[int, int]]]:
        chunks = []
        last_end = 0
        lines = text.splitlines(keepends=True)
        # Mapping char index to line number is expensive, so we'll approximate or do it if needed.
        # For now, let's just split string and estimate lines.
        
        # Actually, let's use re.split logic but keep offsets
        matches = list(pattern.finditer(text))
        if not matches:
             return [(text, (1, len(lines)))]
             
        current_start = 0
        for match in matches:
            chunk = text[current_start:match.start()].strip()
            if chunk:
                 # TODO: Calculate accurate line numbers
                 chunks.append((chunk, (0, 0))) 
            current_start = match.end()
            
        last_chunk = text[current_start:].strip()
        if last_chunk:
            chunks.append((last_chunk, (0, 0)))
            
        return chunks

    def _split_by_positions(self, text: str, positions: List[int]) -> List[Tuple[str, Tuple[int, int]]]:
        chunks = []
        for i in range(len(positions)):
            start = positions[i]
            end = positions[i+1] if i + 1 < len(positions) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append((chunk, (0, 0)))
        return chunks

    def _split_by_line_indices(
        self,
        text: str,
        start_lines: list[int],
    ) -> List[Tuple[str, Tuple[int, int]]]:
        lines = text.splitlines(keepends=True)
        if not lines:
            return []
        line_starts: list[int] = []
        pos = 0
        for line in lines:
            line_starts.append(pos)
            pos += len(line)

        chunks: list[tuple[str, tuple[int, int]]] = []
        starts = sorted(set(start_lines))
        for idx, start_line in enumerate(starts):
            if start_line < 0 or start_line >= len(lines):
                continue
            end_line = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            start_char = line_starts[start_line]
            end_char = line_starts[end_line] if end_line < len(lines) else len(text)
            chunk = text[start_char:end_char].strip()
            if chunk:
                chunks.append((chunk, (start_line + 1, end_line)))
        return chunks

    def _parse_chunk(self, text: str) -> RecipeCandidate:
        """
        Parses a single recipe chunk into a candidate.
        """
        lines = text.splitlines()
        
        # 1. Frontmatter
        frontmatter = {}
        content_lines = lines
        if text.startswith("---"):
            try:
                # Find end of frontmatter
                end_idx = -1
                for i in range(1, len(lines)):
                    if lines[i].strip() == "---":
                        end_idx = i
                        break
                if end_idx > 0:
                    fm_text = "\n".join(lines[1:end_idx])
                    frontmatter = yaml.safe_load(fm_text) or {}
                    content_lines = lines[end_idx+1:]
            except Exception as e:
                logger.warning(f"Failed to parse frontmatter: {e}")

        # 2. Identify Sections
        name = frontmatter.get("title")
        ingredients: List[str] = []
        instructions: List[str] = []
        description_lines: List[str] = []
        tags = frontmatter.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]

        current_section = "description" # Default start
        recipe_yield = (
            str(frontmatter.get("servings") or frontmatter.get("yield") or "")
            if frontmatter.get("servings") or frontmatter.get("yield")
            else None
        )
        
        # Heuristic: First line is title if not in frontmatter
        start_idx = 0
        if not name:
            for i, line in enumerate(content_lines):
                stripped = line.strip()
                if stripped:
                    # Cleanup title candidates
                    name = re.sub(r"^#+\s*", "", stripped) # Remove markdown headers
                    name = re.sub(r"^\d+\.\s*", "", name)  # Remove leading numbering "1. "
                    name = re.sub(r"^Title:\s*", "", name, flags=re.IGNORECASE) # Remove "Title:" prefix
                    start_idx = i + 1
                    break

        remaining_lines = [line.strip() for line in content_lines[start_idx:] if line.strip()]
        if remaining_lines:
            has_headers = False
            cleaned_lines: list[str] = []
            for line in remaining_lines:
                block_feats = signals.classify_block(line)
                if block_feats["is_ingredient_header"] or block_feats["is_instruction_header"]:
                    has_headers = True
                if recipe_yield is None:
                    extracted = _extract_yield_phrase(line)
                    if extracted is not None:
                        recipe_yield = extracted
                        continue
                cleaned_lines.append(line)

            if has_headers:
                for line in cleaned_lines:
                    block_feats = signals.classify_block(line)

                    if block_feats["is_ingredient_header"]:
                        current_section = "ingredients"
                        continue
                    if block_feats["is_instruction_header"]:
                        current_section = "instructions"
                        continue
                    if block_feats["is_header_likely"] and "notes" in line.lower():
                        current_section = "description"
                        continue

                    if current_section == "ingredients":
                        clean_line = re.sub(r"^\s*[-*•]\s*", "", line.strip())
                        ingredients.append(clean_line)
                    elif current_section == "instructions":
                        clean_line = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", line.strip())
                        instructions.append(clean_line)
                    else:
                        description_lines.append(line.strip())
            else:
                feats_list = [signals.classify_block(line) for line in cleaned_lines]
                ingredient_indices = [
                    i for i, line in enumerate(cleaned_lines)
                    if _is_ingredient_like(line, feats_list[i])
                ]
                instruction_indices = [
                    i for i, line in enumerate(cleaned_lines)
                    if _is_instruction_like(line, feats_list[i])
                ]

                ingredient_start = ingredient_indices[0] if ingredient_indices else None
                instruction_start = None
                if ingredient_start is not None:
                    for idx in instruction_indices:
                        if idx > ingredient_start:
                            instruction_start = idx
                            break

                if ingredient_start is not None:
                    description_lines.extend(cleaned_lines[:ingredient_start])
                    ingredient_block = cleaned_lines[
                        ingredient_start:instruction_start or len(cleaned_lines)
                    ]
                    instruction_block = (
                        cleaned_lines[instruction_start:] if instruction_start is not None else []
                    )
                elif instruction_indices:
                    instruction_start = instruction_indices[0]
                    description_lines.extend(cleaned_lines[:instruction_start])
                    ingredient_block = []
                    instruction_block = cleaned_lines[instruction_start:]
                else:
                    description_lines.extend(cleaned_lines)
                    ingredient_block = []
                    instruction_block = []

                for idx, line in enumerate(ingredient_block):
                    feats = signals.classify_block(line)
                    if _is_instruction_like(line, feats) and not _is_ingredient_like(line, feats):
                        instruction_block = ingredient_block[idx:] + instruction_block
                        ingredient_block = ingredient_block[:idx]
                        break

                for line in ingredient_block:
                    feats = signals.classify_block(line)
                    clean_line = re.sub(r"^\s*[-*•]\s*", "", line.strip())
                    if clean_line:
                        ingredients.append(clean_line)

                for line in instruction_block:
                    clean_line = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", line.strip())
                    if clean_line:
                        instructions.append(clean_line)

        return RecipeCandidate(
            name=name or "Untitled Recipe",
            ingredients=ingredients,
            instructions=instructions,
            description="\n".join(description_lines) if description_lines else None,
            recipeYield=recipe_yield or "",
            sourceUrl=frontmatter.get("source"),
            tags=tags
        )

registry.register(TextImporter())
