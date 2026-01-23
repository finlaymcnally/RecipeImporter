from __future__ import annotations

import logging
import re
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString, Tag, XMLParsedAsHTMLWarning

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RecipeCandidate,
    WorkbookInspection,
    SheetInspection,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
    generate_recipe_id,
)
from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning, signals
from cookimport.plugins import registry

# Suppress ebooklib warnings about future/deprecations if any
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

class EpubImporter:
    name = "epub"

    def detect(self, path: Path) -> float:
        if path.suffix.lower() == ".epub":
            return 0.95
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        """
        Quickly inspect the EPUB structure.
        """
        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
            spine_count = len(book.spine)
            title = book.get_metadata("DC", "title")
            title_str = title[0][0] if title else path.stem
            
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=title_str,
                        layout="epub-book",
                        confidence=0.9,
                        warnings=[f"Found {spine_count} spine items."],
                    )
                ],
                mappingStub=MappingConfig(),
            )
        except Exception as e:
            logger.warning(f"Failed to inspect EPUB {path}: {e}")
            return WorkbookInspection(
                path=str(path),
                sheets=[],
                mappingStub=MappingConfig(),
            )

    def convert(self, path: Path, mapping: MappingConfig | None) -> ConversionResult:
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        
        try:
            file_hash = compute_file_hash(path)
            
            # 1. Extract Blocks (DocPack)
            blocks = self._extract_docpack(path)
            
            # 2. Segment into Candidates
            candidates_ranges = self._detect_candidates(blocks)
            
            # 3. Extract Fields
            for i, (start, end, score) in enumerate(candidates_ranges):
                try:
                    candidate_blocks = blocks[start:end]
                    candidate = self._extract_fields(candidate_blocks)
                    
                    # Provenance
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method="heuristic_epub",
                    )
                    provenance = provenance_builder.build(
                        confidence_score=score / 10.0, # Normalize roughly
                        location={
                            "start_block": start,
                            "end_block": end,
                            "chunk_index": i
                        }
                    )
                    candidate.provenance = provenance
                    
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "epub", file_hash, f"c{i}"
                        )
                    
                    recipes.append(candidate)
                    
                except Exception as e:
                    logger.warning(f"Failed to extract candidate {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse candidate {i}: {e}")

            report.total_recipes = len(recipes)
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]

            return ConversionResult(
                recipes=recipes,
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

        except Exception as e:
            logger.error(f"Fatal error converting EPUB {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

    def _extract_docpack(self, path: Path) -> List[Block]:
        """
        Reads EPUB and converts spine items to a linear list of Blocks.
        """
        blocks: List[Block] = []
        try:
            book = epub.read_epub(str(path))
            
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                # Check if item is in spine (reading order)
                # ebooklib doesn't make this super easy efficiently, but we can iterate spine
                # Actually, get_items_of_type returns all.
                # Better to iterate spine.
                pass

            # Iterate spine
            for item_id, linear in book.spine:
                item = book.get_item_with_id(item_id)
                if not item:
                    continue
                    
                content = item.get_content()
                soup = BeautifulSoup(content, "lxml")
                
                # Simple DOM walk
                for elem in soup.body.descendants if soup.body else []:
                    if isinstance(elem, Tag):
                        text = cleaning.normalize_text(elem.get_text())
                        if not text:
                            continue
                            
                        # Determine type
                        btype = BlockType.TEXT
                        font_weight = "normal"
                        
                        if elem.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                            # Heading
                            # We treat it as text but maybe add feature
                            font_weight = "bold"
                        elif elem.name == "li":
                            # List item
                            pass
                        elif elem.name == "p":
                            pass
                        elif elem.name in ["strong", "b"]:
                             font_weight = "bold"
                        
                        # Avoid duplicates: descendants visits children too.
                        # Strategy: Only emit leaf nodes or block-level elements that contain text directly?
                        # Better strategy: soup.strings or stripped_strings but we lose tags.
                        # Alternative: Recursively parse functions.
                        pass
                
                # Let's use a simpler recursive extractor for the DOM
                item_blocks = self._parse_soup_to_blocks(soup)
                blocks.extend(item_blocks)
                
        except Exception as e:
            logger.error(f"DocPack extraction failed: {e}")
            raise
            
        return blocks

    def _parse_soup_to_blocks(self, soup: BeautifulSoup) -> List[Block]:
        blocks = []
        
        # We want to capture block-level elements
        # h1-h6, p, div, li, td
        
        # Helper to decide if we should emit a block
        def is_block_tag(tag):
            return tag.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'blockquote']

        # Flatten the structure
        # We iterate over all tags. If it's a block tag and has text, we emit.
        # But we must avoid double counting children.
        # So we only take text from DIRECT children or if it's a leaf block.
        
        for elem in soup.find_all(is_block_tag):
            # Get text, but be careful of nested block tags?
            # Actually, standard soup.get_text() gets all descendant text.
            # If we have <div><p>Text</p></div>, we get "Text" for p and "Text" for div.
            # We want the most specific block.
            
            # Check if this element contains other block tags
            has_block_children = any(child.name in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'blockquote'] 
                                     for child in elem.children if isinstance(child, Tag))
            
            if has_block_children:
                continue # Skip container, let children be handled
            
            text = cleaning.normalize_text(elem.get_text())
            if not text:
                continue
            
            block = Block(
                text=text,
                type=BlockType.TEXT,
                html=str(elem),
                font_weight="bold" if elem.name.startswith("h") or elem.find("strong") or elem.find("b") else "normal"
            )
            
            # Signals
            signals.enrich_block(block)
            
            # Extra EPUB specific signals
            if elem.name.startswith("h"):
                block.add_feature("is_heading", True)
                block.add_feature("heading_level", int(elem.name[1]))
            if elem.name == "li":
                block.add_feature("is_list_item", True)
                
            blocks.append(block)
            
        return blocks

    def _detect_candidates(self, blocks: List[Block]) -> List[Tuple[int, int, float]]:
        """
        Segments blocks into recipes. Returns (start_idx, end_idx, score).
        """
        candidates = []
        current_start = -1
        
        # State machine
        # LOOKING_FOR_START -> IN_RECIPE -> FINALIZE
        
        # Heuristics for Start:
        # - Title-ish block (heading, short, bold)
        # - Followed shortly by Ingredients header
        
        i = 0
        while i < len(blocks):
            block = blocks[i]
            
            # Check for recipe start signal
            # Strongest signal: Ingredient Header
            # If we find Ingredient Header, the recipe probably started earlier (at the Title).
            
            if block.features.get("is_ingredient_header"):
                # Backtrack to find Title
                title_idx = self._backtrack_for_title(blocks, i)
                start_idx = title_idx if title_idx != -1 else i
                
                # Now scan forward for end
                end_idx = self._find_recipe_end(blocks, i)
                
                score = 5.0 # High confidence
                candidates.append((start_idx, end_idx, score))
                
                i = end_idx
                continue
                
            i += 1
            
        return candidates

    def _backtrack_for_title(self, blocks: List[Block], ingredient_idx: int) -> int:
        """
        Look backwards from ingredients for a likely title.
        Limit: 20 blocks.
        """
        limit = 20
        best_idx = -1
        
        for i in range(ingredient_idx - 1, max(-1, ingredient_idx - limit), -1):
            b = blocks[i]
            
            # Stop if we hit end of previous recipe (e.g. another ingredient header? maybe not reliable if interleaved)
            if b.features.get("is_ingredient_header"):
                break

            # Check for title characteristics
            # - Heading tag (h1-h3)
            # - Short text
            # - Title Case
            
            is_heading = b.features.get("is_heading")
            is_short = len(b.text) < 100
            
            if is_heading and is_short:
                return i
            
            # Fallback: Short bold line
            if b.font_weight == "bold" and is_short:
                best_idx = i # Keep looking for a better one (heading)
                
            # Fallback: Just short title case line
            if is_short and b.text.istitle() and best_idx == -1:
                best_idx = i
                
        return best_idx

    def _find_recipe_end(self, blocks: List[Block], ingredient_idx: int) -> int:
        """
        Scan forward to find end of recipe.
        Stop at next ingredient header (start of next recipe) or new chapter/major heading.
        """
        for i in range(ingredient_idx + 1, len(blocks)):
            b = blocks[i]
            
            if b.features.get("is_ingredient_header"):
                # Likely start of next recipe.
                # But check if it's a sub-header ("For the sauce")
                # Heuristic: If we haven't seen instructions yet, it might be a sub-header.
                # If we HAVE seen instructions, it's likely a new recipe.
                # For now, simplistic: Assume it's new recipe if it matches standard "Ingredients" exactly.
                if b.text.lower().rstrip(":") in ["ingredients", "ingredient"]:
                     # But we need to check if we are splitting a single recipe with multiple parts.
                     # Let's assume start of next recipe for now to be safe.
                     # But we might consume the title of the next recipe if we are not careful.
                     
                     # Refined strategy: Stop if we see a clear "Ingredients" header. 
                     # The previous blocks (Title) will be captured by the next iteration's backtrack?
                     # Yes, if we don't consume them.
                     
                     # Let's return i, but maybe subtract a few if they look like a title?
                     # Backtrack from i to find title of NEXT recipe, and end THIS recipe before that title.
                     
                     next_title = self._backtrack_for_title(blocks, i)
                     if next_title != -1 and next_title > ingredient_idx:
                         return next_title
                     return i
            
            # Stop at huge headings that look like Chapter titles (h1)
            if b.features.get("is_heading") and b.features.get("heading_level") == 1:
                return i
                
        return len(blocks)

    def _extract_fields(self, blocks: List[Block]) -> RecipeCandidate:
        name = "Untitled Recipe"
        ingredients = []
        instructions = []
        description = []
        
        # 1. Title (First block usually)
        if blocks:
            name = blocks[0].text
            
        # 2. Sections
        current_section = "description"
        if blocks and blocks[0].features.get("is_heading"):
             # First block is title, skip it for content
             content_blocks = blocks[1:]
        else:
             content_blocks = blocks
             
        for b in content_blocks:
            if b.features.get("is_ingredient_header"):
                current_section = "ingredients"
                continue
            if b.features.get("is_instruction_header"):
                current_section = "instructions"
                continue
                
            if current_section == "ingredients":
                # Cleaning
                text = re.sub(r"^\s*[-*•]\s*", "", b.text)
                ingredients.append(text)
            elif current_section == "instructions":
                # Cleaning
                text = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", b.text)
                instructions.append(text)
            elif current_section == "description":
                description.append(b.text)
                
        return RecipeCandidate(
            name=name,
            ingredients=ingredients,
            instructions=instructions,
            description="\n".join(description) if description else None
        )

registry.register(EpubImporter())
