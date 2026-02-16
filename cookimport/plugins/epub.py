from __future__ import annotations

import json
import logging
import os
import re
import warnings
import zipfile
import xml.etree.ElementTree as ET
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePosixPath
from typing import Any, Callable, List, Tuple

try:
    import ebooklib
    from ebooklib import epub
except ModuleNotFoundError:
    ebooklib = None
    epub = None

from bs4 import BeautifulSoup, FeatureNotFound, Tag, XMLParsedAsHTMLWarning

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    RawArtifact,
    RecipeCandidate,
    WorkbookInspection,
    SheetInspection,
)
from cookimport.core.reporting import (
    ProvenanceBuilder,
    compute_file_hash,
    generate_recipe_id,
)
from cookimport.core.scoring import score_recipe_candidate
from cookimport.core.blocks import Block, BlockType
from cookimport.parsing import cleaning, signals
from cookimport.parsing.block_roles import assign_block_roles
from cookimport.parsing.atoms import Atom, contextualize_atoms, split_text_to_atoms
from cookimport.parsing.tips import (
    build_topic_candidate,
    extract_tip_candidates,
    extract_tip_candidates_from_candidate,
    chunk_standalone_blocks,
    partition_tip_candidates,
)
from cookimport.plugins import registry

# ---------------------------------------------------------------------------
# Extractor switch: C3IMP_EPUB_EXTRACTOR = legacy | unstructured
# Default: unstructured
# Read at call time (not import time) so interactive settings take effect.
# ---------------------------------------------------------------------------
def _get_epub_extractor() -> str:
    return os.environ.get("C3IMP_EPUB_EXTRACTOR", "unstructured").strip().lower()

# Suppress ebooklib warnings about future/deprecations if any
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)


def _block_to_raw(block: Block, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "text": block.text,
        "html": block.html,
        "type": str(block.type),
        "font_weight": block.font_weight,
        "features": block.features,
    }


def _resolve_unstructured_version() -> str:
    try:
        return importlib_metadata.version("unstructured")
    except importlib_metadata.PackageNotFoundError:
        pass
    except Exception:
        pass

    try:
        import unstructured as _unstructured_pkg
    except Exception:
        return "unknown"

    version_value = getattr(_unstructured_pkg, "__version__", None)
    if isinstance(version_value, str) and version_value:
        return version_value

    nested_version = getattr(version_value, "__version__", None)
    if isinstance(nested_version, str) and nested_version:
        return nested_version

    if version_value is None:
        return "unknown"
    return str(version_value)


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
        if epub is not None:
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
                            spine_count=spine_count,
                            warnings=[f"Found {spine_count} spine items."],
                        )
                    ],
                    mappingStub=MappingConfig(),
                )
            except Exception as e:
                logger.warning(f"Ebooklib inspect failed for EPUB {path}: {e}")

        try:
            title, spine_items = self._read_epub_spine(path)
            title_str = title or path.stem
            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=title_str,
                        layout="epub-book",
                        confidence=0.8,
                        spine_count=len(spine_items),
                        warnings=[f"Found {len(spine_items)} spine items (zip fallback)."],
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

    def convert(
        self,
        path: Path,
        mapping: MappingConfig | None,
        progress_callback: Callable[[str], None] | None = None,
        start_spine: int | None = None,
        end_spine: int | None = None,
    ) -> ConversionResult:
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        tip_candidates: List[Any] = []
        topic_candidates: List[Any] = []
        raw_artifacts: list[RawArtifact] = []
        overrides = mapping.parsing_overrides if mapping else None
        self._overrides = overrides
        
        try:
            if progress_callback:
                progress_callback("Computing hash...")
            file_hash = compute_file_hash(path)
            
            # 1. Extract Blocks (DocPack)
            if progress_callback:
                progress_callback("Extracting blocks from EPUB...")
            blocks = self._extract_docpack(path, start_spine=start_spine, end_spine=end_spine)
            
            raw_artifacts.append(
                RawArtifact(
                    importer="epub",
                    sourceHash=file_hash,
                    locationId="full_text",
                    extension="json",
                    content={
                        "blocks": [
                            _block_to_raw(block, idx)
                            for idx, block in enumerate(blocks)
                        ],
                        "block_count": len(blocks),
                    },
                    metadata={"artifact_type": "extracted_blocks"},
                )
            )

            # Assign deterministic block roles for chunk lane selection
            assign_block_roles(blocks)

            # Emit Unstructured diagnostics JSONL when using the Unstructured extractor
            if _get_epub_extractor() == "unstructured" and self._unstructured_diagnostics:
                unstructured_version = _resolve_unstructured_version()
                jsonl_lines = "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in self._unstructured_diagnostics
                )
                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId="unstructured_elements",
                        extension="jsonl",
                        content=jsonl_lines,
                        metadata={
                            "artifact_type": "unstructured_diagnostics",
                            "extractor": "unstructured",
                            "unstructured_version": unstructured_version,
                            "element_count": len(self._unstructured_diagnostics),
                        },
                    )
                )

            # 2. Segment into Candidates
            if progress_callback:
                progress_callback(f"Segmenting {len(blocks)} blocks...")
            candidates_ranges = self._detect_candidates(blocks)
            
            # 3. Extract Fields
            total_candidates = len(candidates_ranges)
            for i, (start, end, segmentation_score) in enumerate(candidates_ranges):
                if progress_callback:
                    progress_callback(f"Extracting candidate {i + 1}/{total_candidates}...")
                try:
                    candidate_blocks = blocks[start:end]
                    candidate = self._extract_fields(candidate_blocks)
                    candidate.confidence = score_recipe_candidate(candidate)
                    
                    # Provenance
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method="heuristic_epub",
                    )
                    spine_values = [
                        b.features.get("spine_index")
                        for b in candidate_blocks
                        if isinstance(b.features, dict)
                        and b.features.get("spine_index") is not None
                    ]
                    location_info: dict[str, Any] = {
                        "start_block": start,
                        "end_block": end,
                        "chunk_index": i,
                        "segmentation_score": segmentation_score,
                    }
                    if spine_values:
                        location_info["start_spine"] = min(spine_values)
                        location_info["end_spine"] = max(spine_values)
                    provenance = provenance_builder.build(
                        confidence_score=candidate.confidence,
                        location=location_info,
                    )
                    candidate.provenance = provenance
                    
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "epub", file_hash, f"c{i}"
                        )
                    
                    recipes.append(candidate)
                    raw_artifacts.append(
                        RawArtifact(
                            importer="epub",
                            sourceHash=file_hash,
                            locationId=f"c{i}",
                            extension="json",
                            content={
                                "start_block": start,
                                "end_block": end,
                                "blocks": [
                                    _block_to_raw(block, idx)
                                    for idx, block in enumerate(candidate_blocks, start=start)
                                ],
                            },
                        )
                    )
                    tip_candidates.extend(
                        extract_tip_candidates_from_candidate(candidate, overrides=overrides)
                    )
                    
                except Exception as e:
                    logger.warning(f"Failed to extract candidate {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse candidate {i}: {e}")

            (
                standalone_tips,
                standalone_topics,
                standalone_block_count,
                topic_block_count,
            ) = self._extract_standalone_tips(blocks, candidates_ranges, path, file_hash)
            tip_candidates.extend(standalone_tips)
            topic_candidates.extend(standalone_topics)

            # Collect non-recipe blocks for knowledge chunking
            covered: set[int] = set()
            for start, end, _ in candidates_ranges:
                covered.update(range(start, end))
            non_recipe_blocks = [
                {"index": idx, "text": block.text, "features": block.features}
                for idx, block in enumerate(blocks)
                if idx not in covered and block.text.strip()
            ]

            tips, recipe_specific, not_tips = partition_tip_candidates(tip_candidates)

            report.total_recipes = len(recipes)
            report.total_tips = len(tips)
            report.total_tip_candidates = len(tip_candidates)
            report.total_topic_candidates = len(topic_candidates)
            report.total_general_tips = len(tips)
            report.total_recipe_specific_tips = len(recipe_specific)
            report.total_not_tips = len(not_tips)
            if recipes:
                report.samples = [{"name": r.name} for r in recipes[:3]]
            if tips:
                report.tip_samples = [{"text": tip.text[:80]} for tip in tips[:3]]
            if topic_candidates:
                report.topic_samples = [
                    {"text": topic.text[:80]} for topic in topic_candidates[:3]
                ]
            report.total_standalone_blocks = standalone_block_count
            report.total_standalone_topic_blocks = topic_block_count
            if standalone_block_count:
                standalone_coverage = topic_block_count / standalone_block_count
                report.standalone_topic_coverage = standalone_coverage
                if standalone_coverage < 0.9:
                    report.warnings.append(
                        "Standalone topic coverage low: "
                        f"{topic_block_count} of {standalone_block_count} blocks "
                        f"represented ({standalone_coverage:.0%})."
                    )

            return ConversionResult(
                recipes=recipes,
                tips=tips,
                tipCandidates=tip_candidates,
                topicCandidates=topic_candidates,
                nonRecipeBlocks=non_recipe_blocks,
                rawArtifacts=raw_artifacts,
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

        except Exception as e:
            logger.error(f"Fatal error converting EPUB {path}: {e}")
            report.errors.append(str(e))
            return ConversionResult(
                recipes=[],
                tips=[],
                topicCandidates=[],
                rawArtifacts=[],
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )
        finally:
            self._overrides = None

    def _extract_standalone_tips(
        self,
        blocks: List[Block],
        candidate_ranges: List[Tuple[int, int, float]],
        path: Path,
        file_hash: str,
    ) -> tuple[List[Any], List[Any], int, int]:
        covered: set[int] = set()
        for start, end, _ in candidate_ranges:
            covered.update(range(start, end))

        tip_candidates: List[Any] = []
        topic_candidates: List[Any] = []
        provenance_builder = ProvenanceBuilder(
            source_file=path.name,
            source_hash=file_hash,
            extraction_method="heuristic_epub_tip",
        )

        standalone_blocks: list[tuple[int, str]] = []
        for idx, block in enumerate(blocks):
            if idx in covered:
                continue
            text = block.text.strip()
            if not text:
                continue
            standalone_blocks.append((idx, text))

        topic_block_indices: set[int] = set()
        for container in chunk_standalone_blocks(
            standalone_blocks, overrides=self._overrides
        ):
            if not container.indices:
                continue
            start_block = min(container.indices)
            end_block = max(container.indices)
            base_location: dict[str, Any] = {
                "start_block": start_block,
                "end_block": end_block,
                "chunk_index": start_block,
            }

            atoms: list[Atom] = []
            sequence_offset = 0
            header_block_index: int | None = None
            if container.header:
                for idx, text in container.blocks:
                    if text == container.header:
                        header_block_index = idx
                        break
                if header_block_index is None and container.blocks:
                    header_block_index = container.blocks[0][0]
                atoms.append(
                    Atom(
                        text=container.header,
                        kind="header",
                        source_block_index=(
                            header_block_index if header_block_index is not None else start_block
                        ),
                        sequence=sequence_offset,
                        container_start=start_block,
                        container_end=end_block,
                        container_header=container.header,
                    )
                )
                sequence_offset += 1

            for idx, text in container.blocks:
                if container.header and text == container.header:
                    continue
                block_atoms = split_text_to_atoms(
                    text,
                    idx,
                    sequence_offset=sequence_offset,
                    container_start=start_block,
                    container_end=end_block,
                    container_header=container.header,
                )
                atoms.extend(block_atoms)
                sequence_offset = len(atoms)

            contextualize_atoms(atoms)

            container_tip_index = 0
            for atom in atoms:
                location = dict(base_location)
                location["block_index"] = atom.source_block_index
                location["atom_index"] = atom.sequence
                location["atom_kind"] = atom.kind

                provenance = provenance_builder.build(
                    confidence_score=0.6,
                    location=location,
                )
                if container.header:
                    provenance["topic_header"] = container.header
                provenance["atom"] = {
                    "index": atom.sequence,
                    "kind": atom.kind,
                    "block_index": atom.source_block_index,
                    "context_prev": atom.context_prev,
                    "context_next": atom.context_next,
                }

                topic_candidates.append(
                    build_topic_candidate(
                        atom.text,
                        provenance=provenance,
                        source_section="standalone_topic",
                        header=container.header,
                        overrides=self._overrides,
                    )
                )
                topic_block_indices.add(atom.source_block_index)

                if atom.kind == "header":
                    continue
                atom_tips = extract_tip_candidates(
                    atom.text,
                    provenance=provenance,
                    source_section="standalone_topic",
                    overrides=self._overrides,
                    tip_index_start=container_tip_index,
                    header_hint=container.header,
                )
                tip_candidates.extend(atom_tips)
                container_tip_index += len(atom_tips)

        return (
            tip_candidates,
            topic_candidates,
            len(standalone_blocks),
            len(topic_block_indices),
        )

    def _extract_docpack(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
    ) -> List[Block]:
        """
        Reads EPUB and converts spine items to a linear list of Blocks.

        When C3IMP_EPUB_EXTRACTOR=unstructured, uses Unstructured's HTML
        partitioner for richer semantic extraction with traceability.
        Diagnostics rows are accumulated in self._unstructured_diagnostics.
        """
        self._unstructured_diagnostics: list[dict[str, Any]] = []

        if epub is not None:
            try:
                return self._extract_docpack_with_ebooklib(
                    path,
                    start_spine=start_spine,
                    end_spine=end_spine,
                )
            except Exception as e:
                logger.warning(f"Ebooklib extraction failed for EPUB {path}: {e}")

        return self._extract_docpack_with_zip(
            path,
            start_spine=start_spine,
            end_spine=end_spine,
        )

    def _extract_docpack_with_ebooklib(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
    ) -> List[Block]:
        blocks: List[Block] = []
        if epub is None:
            raise RuntimeError("ebooklib is not available")

        use_unstructured = _get_epub_extractor() == "unstructured"
        if use_unstructured:
            from cookimport.parsing.unstructured_adapter import partition_html_to_blocks

        source_location_id = path.stem

        book = epub.read_epub(str(path), options={"ignore_ncx": True})
        for spine_index, (item_id, _linear) in enumerate(book.spine):
            if start_spine is not None and spine_index < start_spine:
                continue
            if end_spine is not None and spine_index >= end_spine:
                continue
            item = book.get_item_with_id(item_id)
            if not item:
                continue
            if ebooklib is not None and item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            content = item.get_content()

            if use_unstructured:
                html_str = content.decode("utf-8", errors="replace")
                spine_blocks, diag_rows = partition_html_to_blocks(
                    html_str,
                    spine_index=spine_index,
                    source_location_id=source_location_id,
                )
                # Enrich with shared signals (ingredient/instruction detection)
                for b in spine_blocks:
                    signals.enrich_block(b, overrides=self._overrides)
                blocks.extend(spine_blocks)
                self._unstructured_diagnostics.extend(diag_rows)
            else:
                soup = self._soup_from_bytes(content)
                blocks.extend(self._parse_soup_to_blocks(soup, spine_index=spine_index))
        return blocks

    def _extract_docpack_with_zip(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
    ) -> List[Block]:
        blocks: List[Block] = []
        _title, spine_items = self._read_epub_spine(path)
        if not spine_items:
            raise ValueError("No spine items found in EPUB")

        use_unstructured = _get_epub_extractor() == "unstructured"
        if use_unstructured:
            from cookimport.parsing.unstructured_adapter import partition_html_to_blocks

        source_location_id = path.stem

        with zipfile.ZipFile(path) as zip_handle:
            for spine_index, (spine_path, media_type) in enumerate(spine_items):
                if start_spine is not None and spine_index < start_spine:
                    continue
                if end_spine is not None and spine_index >= end_spine:
                    continue
                if not spine_path:
                    continue
                if media_type and "html" not in media_type:
                    continue
                try:
                    content = zip_handle.read(spine_path)
                except KeyError:
                    logger.warning(f"Missing spine item in EPUB: {spine_path}")
                    continue

                if use_unstructured:
                    html_str = content.decode("utf-8", errors="replace")
                    spine_blocks, diag_rows = partition_html_to_blocks(
                        html_str,
                        spine_index=spine_index,
                        source_location_id=source_location_id,
                    )
                    for b in spine_blocks:
                        signals.enrich_block(b, overrides=self._overrides)
                    blocks.extend(spine_blocks)
                    self._unstructured_diagnostics.extend(diag_rows)
                else:
                    soup = self._soup_from_bytes(content)
                    blocks.extend(self._parse_soup_to_blocks(soup, spine_index=spine_index))
        return blocks

    def _soup_from_bytes(self, content: bytes) -> BeautifulSoup:
        try:
            return BeautifulSoup(content, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(content, "html.parser")

    def _read_epub_spine(self, path: Path) -> tuple[str | None, List[tuple[str, str]]]:
        with zipfile.ZipFile(path) as zip_handle:
            opf_path = self._find_opf_path(zip_handle)
            opf_bytes = zip_handle.read(opf_path)

        title = self._extract_opf_title(opf_bytes)
        spine_items = self._extract_spine_items(opf_path, opf_bytes)
        return title, spine_items

    def _find_opf_path(self, zip_handle: zipfile.ZipFile) -> str:
        try:
            container_bytes = zip_handle.read("META-INF/container.xml")
        except KeyError:
            container_bytes = b""

        if container_bytes:
            root = ET.fromstring(container_bytes)
            rootfile = root.find(".//{*}rootfile")
            if rootfile is not None:
                opf_path = rootfile.attrib.get("full-path")
                if opf_path:
                    return opf_path

        for name in zip_handle.namelist():
            if name.lower().endswith(".opf"):
                return name

        raise ValueError("EPUB is missing content.opf")

    def _extract_opf_title(self, opf_bytes: bytes) -> str | None:
        root = ET.fromstring(opf_bytes)
        title_node = root.find(".//{*}metadata/{*}title")
        if title_node is None:
            title_node = root.find(".//{*}title")
        if title_node is not None and title_node.text:
            return title_node.text.strip()
        return None

    def _extract_spine_items(self, opf_path: str, opf_bytes: bytes) -> List[tuple[str, str]]:
        root = ET.fromstring(opf_bytes)
        manifest: dict[str, tuple[str, str]] = {}

        for item in root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id")
            href = item.attrib.get("href")
            if not item_id or not href:
                continue
            media_type = item.attrib.get("media-type", "")
            clean_href = href.split("#", 1)[0]
            manifest[item_id] = (clean_href, media_type)

        base_dir = PurePosixPath(opf_path).parent
        spine_items: List[tuple[str, str]] = []
        for itemref in root.findall(".//{*}spine/{*}itemref"):
            idref = itemref.attrib.get("idref")
            if not idref:
                continue
            manifest_entry = manifest.get(idref)
            if not manifest_entry:
                continue
            href, media_type = manifest_entry
            if not href:
                continue
            full_path = str((base_dir / href).as_posix())
            spine_items.append((full_path, media_type))

        return spine_items

    def _parse_soup_to_blocks(
        self,
        soup: BeautifulSoup,
        spine_index: int | None = None,
    ) -> List[Block]:
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

            if spine_index is not None:
                block.add_feature("spine_index", spine_index)
            
            # Signals
            signals.enrich_block(block, overrides=self._overrides)
            
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
        if not blocks:
            return []

        yield_indices = [i for i, b in enumerate(blocks) if b.features.get("is_yield")]
        if yield_indices:
            starts: List[Tuple[int, int]] = []
            seen_starts: set[int] = set()
            for idx in yield_indices:
                title_idx = self._backtrack_for_title(blocks, idx, limit=8)
                start_idx = title_idx if title_idx != -1 else idx
                if start_idx in seen_starts:
                    continue
                seen_starts.add(start_idx)
                starts.append((start_idx, idx))
            starts.sort()

            candidates: List[Tuple[int, int, float]] = []
            last_end = 0
            for start_idx, anchor_idx in starts:
                if start_idx < last_end:
                    continue
                end_idx = self._find_recipe_end(blocks, start_idx, anchor_idx)
                score = self._score_candidate(blocks[start_idx:end_idx])
                candidates.append((start_idx, end_idx, score))
                last_end = end_idx
            return candidates

        candidates: List[Tuple[int, int, float]] = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            if block.features.get("is_ingredient_header") or self._is_recipe_anchor(blocks, i):
                title_idx = self._backtrack_for_title(blocks, i)
                start_idx = title_idx if title_idx != -1 else i
                end_idx = self._find_recipe_end(blocks, start_idx, i)
                score = self._score_candidate(blocks[start_idx:end_idx])
                candidates.append((start_idx, end_idx, score))
                i = end_idx
                continue
            i += 1

        return candidates

    def _backtrack_for_title(self, blocks: List[Block], anchor_idx: int, limit: int = 20) -> int:
        """
        Look backwards from an anchor to find a likely title.
        """
        best_idx = -1
        min_idx = max(-1, anchor_idx - limit)
        for i in range(anchor_idx - 1, min_idx, -1):
            b = blocks[i]
            if b.features.get("is_ingredient_header"):
                break
            if b.features.get("is_yield") or b.features.get("is_time"):
                continue
            if self._is_title_candidate(b):
                start_idx = i
                j = i - 1
                while j > min_idx:
                    prev = blocks[j]
                    if prev.features.get("is_ingredient_header"):
                        break
                    if prev.features.get("is_yield") or prev.features.get("is_time"):
                        break
                    if not self._is_title_candidate(prev):
                        break
                    start_idx = j
                    j -= 1
                return start_idx
            if best_idx == -1 and len(b.text.strip()) <= 80:
                if not self._is_ingredient_like(b) and not self._is_instruction_like(b):
                    best_idx = i
        return best_idx

    def _find_recipe_end(self, blocks: List[Block], start_idx: int, anchor_idx: int) -> int:
        """
        Scan forward to find end of recipe.
        Stop at next ingredient header (start of next recipe) or new chapter/major heading.
        Include trailing Variation/Variant sections as part of the recipe.
        """
        for i in range(anchor_idx + 1, len(blocks)):
            b = blocks[i]
            next_block = blocks[i + 1] if i + 1 < len(blocks) else None

            # Check if this is a variation header - if so, continue (don't stop)
            if self._is_variation_header(b):
                continue

            if self._is_section_heading(b, next_block):
                return i
            
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
                     if next_title != -1 and next_title > anchor_idx:
                         return next_title
                     return i
            
            # Stop at huge headings that look like Chapter titles (h1)
            if b.features.get("is_heading") and b.features.get("heading_level") == 1:
                return i

            if self._looks_like_section_intro(b):
                return i

            # Skip sub-section headers like "For the Frangipane" - they're part of this recipe
            if self._is_subsection_header(b):
                continue

            if self._is_title_candidate(b) and self._has_ingredient_run(blocks, i):
                return i

        return len(blocks)

    def _is_variation_header(self, block: Block) -> bool:
        """Check if block is a Variation/Variant header that should stay with the recipe."""
        text = block.text.strip().lower().rstrip(":")
        return text in ("variation", "variations", "variant", "variants")

    def _is_subsection_header(self, block: Block) -> bool:
        """Check if block is a sub-section header like 'For the Frangipane' that stays with the recipe.

        These headers indicate ingredient groupings within a single recipe, not new recipes.
        Common patterns:
        - "For the X" (e.g., "For the Frangipane", "For the Tart", "For the Sauce")
        - "X:" where X is a component name (e.g., "Frangipane:", "Crust:")
        """
        text = block.text.strip()
        if not text or len(text) > 60:
            return False
        # Avoid treating actual sentences as sub-headers
        if text.endswith("."):
            return False
        lower = text.lower()
        # "For the X" pattern
        if lower.startswith("for the ") and len(text.split()) <= 6:
            return True
        # "For X" pattern (without "the")
        if lower.startswith("for ") and len(text.split()) <= 4:
            # Make sure it's not an instruction like "For best results..."
            rest = lower[4:].strip()
            # Check if it looks like a component name (short, no verb patterns)
            if rest and not any(word in rest for word in ("best", "better", "optimal", "this", "that", "each")):
                return True
        return False

    def _is_section_heading(self, block: Block, next_block: Block | None) -> bool:
        if not block.features.get("is_heading"):
            return False
        text = block.text.strip()
        if len(text) < 5 or not text.isupper():
            return False
        if block.features.get("is_ingredient_header") or block.features.get("is_instruction_header"):
            return False
        if self._is_variation_header(block):
            return False
        heading_level = block.features.get("heading_level")
        if heading_level in (1, 2):
            return True
        if next_block and next_block.features.get("is_heading"):
            return True
        if next_block and not self._is_ingredient_like(next_block) and not self._is_instruction_like(next_block):
            return True
        return False

    def _looks_like_section_intro(self, block: Block) -> bool:
        text = block.text.strip()
        if len(text) < 30:
            return False

        prefix_tokens, remainder = self._extract_all_caps_prefix(text)
        if not prefix_tokens or not remainder:
            return False

        connectors = {"AND", "OR", "OF", "THE", "&"}
        if len(prefix_tokens) == 1:
            if len(prefix_tokens[0]) < 9:
                return False
        elif len(prefix_tokens) < 3 and not any(tok in connectors for tok in prefix_tokens):
            return False

        prefix_text = " ".join(prefix_tokens)
        if len(prefix_text) < 12 and len(prefix_tokens) > 1:
            return False

        if len(remainder) < 20 or not re.search(r"[a-z]", remainder):
            return False

        first_word = remainder.split()[0]
        if len(first_word) < 2 or not first_word[0].isupper() or not first_word[1:].islower():
            return False

        return True

    def _extract_all_caps_prefix(self, text: str) -> tuple[List[str], str]:
        tokens = text.split()
        prefix_tokens: List[str] = []
        idx = 0
        for token in tokens:
            cleaned = re.sub(r"[^A-Za-z&]", "", token)
            if len(cleaned) < 2:
                break
            if cleaned.isupper():
                prefix_tokens.append(cleaned)
                idx += 1
                continue
            break

        if not prefix_tokens:
            return ([], "")
        remainder = " ".join(tokens[idx:]).lstrip(" :.-")
        return (prefix_tokens, remainder)

    def _extract_fields(self, blocks: List[Block]) -> RecipeCandidate:
        name = "Untitled Recipe"
        ingredients: List[str] = []
        instructions: List[str] = []
        description: List[str] = []
        recipe_yield: str | None = None

        if not blocks:
            return RecipeCandidate(
                name=name,
                ingredients=ingredients,
                instructions=instructions,
                description=None,
            )

        name, consumed = self._extract_title(blocks)
        content_blocks = blocks[consumed:]

        has_ingredient_header = any(
            b.features.get("is_ingredient_header") for b in content_blocks
        )
        has_instruction_header = any(
            b.features.get("is_instruction_header") for b in content_blocks
        )

        if has_ingredient_header or has_instruction_header:
            current_section = "description"
            for b in content_blocks:
                if b.features.get("is_yield") and recipe_yield is None:
                    recipe_yield = self._yield_phrase(b.text)
                    continue
                if b.features.get("is_ingredient_header"):
                    current_section = "ingredients"
                    header_text = b.text.strip()
                    if header_text.lower().rstrip(":") not in ("ingredients", "ingredient"):
                        ingredients.append(header_text)
                    continue
                if b.features.get("is_instruction_header"):
                    current_section = "instructions"
                    continue

                if current_section == "ingredients":
                    if not has_instruction_header and self._is_instruction_like(b):
                        current_section = "instructions"
                        clean = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", b.text)
                        instructions.append(clean)
                        continue
                    clean = re.sub(r"^\s*[-*•]\s*", "", b.text)
                    ingredients.append(clean)
                elif current_section == "instructions":
                    clean = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", b.text)
                    instructions.append(clean)
                else:
                    description.append(b.text)
        else:
            lines: List[tuple[str, Block]] = []
            for block in content_blocks:
                text = block.text.strip()
                if not text:
                    continue
                if block.features.get("is_yield") and recipe_yield is None:
                    recipe_yield = self._yield_phrase(text)
                lines.append((text, block))

            ingredient_start = self._find_ingredient_start(lines)
            instruction_start = self._find_instruction_start(lines, ingredient_start)
            instruction_fallback = instruction_start is None and ingredient_start is not None

            for idx, (text, block) in enumerate(lines):
                if ingredient_start is not None and idx < ingredient_start:
                    if not block.features.get("is_yield"):
                        description.append(text)
                    continue

                if ingredient_start is None:
                    if block.features.get("is_yield"):
                        continue
                    if self._is_instruction_like(block):
                        instructions.append(text)
                    else:
                        description.append(text)
                    continue

                if instruction_start is not None and idx >= instruction_start:
                    instructions.append(text)
                    continue

                if block.features.get("is_yield"):
                    continue
                if self._is_ingredient_like(block):
                    ingredients.append(text)
                elif not self._is_instruction_like(block) and len(text.split()) <= 6:
                    ingredients.append(text)
                elif instruction_fallback:
                    instructions.append(text)
                else:
                    description.append(text)

        instructions = self._merge_wrapped_lines(instructions)

        return RecipeCandidate(
            name=name,
            ingredients=ingredients,
            instructions=instructions,
            description="\n".join(description) if description else None,
            recipe_yield=recipe_yield,
        )

    def _build_candidates_from_starts(
        self,
        blocks: List[Block],
        starts: List[int],
    ) -> List[Tuple[int, int, float]]:
        candidates: List[Tuple[int, int, float]] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(blocks)
            score = self._score_candidate(blocks[start:end])
            candidates.append((start, end, score))
        return candidates

    def _score_candidate(self, blocks: List[Block]) -> float:
        if not blocks:
            return 0.0
        ingredient_count = sum(1 for b in blocks if self._is_ingredient_like(b))
        instruction_count = sum(1 for b in blocks if self._is_instruction_like(b))
        score = 0.0
        if ingredient_count >= 3:
            score += 3.0
        if instruction_count >= 2:
            score += 3.0
        if any(b.features.get("is_yield") for b in blocks):
            score += 1.0
        return score

    def _is_recipe_anchor(self, blocks: List[Block], idx: int) -> bool:
        block = blocks[idx]
        if block.features.get("is_ingredient_header"):
            return True
        if self._is_title_candidate(block) and self._has_ingredient_run(blocks, idx):
            if self._has_ingredient_header_ahead(blocks, idx):
                return False
            return True
        if block.features.get("is_yield") and self._has_ingredient_run(blocks, idx):
            return True
        return False

    def _has_ingredient_run(
        self,
        blocks: List[Block],
        start_idx: int,
        window: int = 8,
    ) -> bool:
        count = 0
        for idx in range(start_idx, min(len(blocks), start_idx + window)):
            if self._is_ingredient_like(blocks[idx]):
                count += 1
            if count >= 2:
                return True
        return False

    def _has_ingredient_header_ahead(
        self,
        blocks: List[Block],
        start_idx: int,
        window: int = 12,
    ) -> bool:
        for idx in range(start_idx, min(len(blocks), start_idx + window)):
            if blocks[idx].features.get("is_ingredient_header"):
                return True
        return False

    def _is_title_candidate(self, block: Block) -> bool:
        text = block.text.strip()
        if not text or len(text) > 80:
            return False
        if block.features.get("is_instruction_header"):
            return False
        if block.features.get("is_ingredient_header"):
            if text.lower() in ("ingredients", "ingredient"):
                return False
            if block.features.get("is_heading") and text.isupper():
                return True
            return False
        if block.features.get("is_ingredient_likely") or block.features.get("is_instruction_likely"):
            return False
        if block.features.get("is_yield") or block.features.get("is_time"):
            return False
        if text.endswith("."):
            return False
        if block.features.get("is_heading"):
            return True
        if block.font_weight == "bold" and len(text) <= 60:
            return True
        if text.isupper() or text.istitle():
            return True
        return False

    def _extract_title(self, blocks: List[Block]) -> tuple[str, int]:
        if not blocks:
            return ("Untitled Recipe", 0)
        title_parts: List[str] = []
        idx = 0
        while idx < len(blocks):
            block = blocks[idx]
            if not self._is_title_candidate(block):
                break
            title_parts.append(block.text.strip())
            idx += 1
            if len(title_parts) >= 3:
                break
        if title_parts:
            return (" ".join(title_parts), idx)
        return (blocks[0].text.strip(), 1)

    def _is_ingredient_like(self, block: Block) -> bool:
        text = block.text.strip()
        if block.features.get("starts_with_quantity"):
            return True
        if block.features.get("has_unit") and re.match(r"^\s*[lI]\s+\w", text):
            return True
        if block.features.get("has_unit") and re.search(r"^\s*\d", text):
            return True
        if re.match(r"^\s*[-*•]\s+", text):
            return True
        return False

    def _is_instruction_like(self, block: Block) -> bool:
        if block.features.get("is_instruction_likely"):
            return True
        if block.features.get("is_ingredient_likely"):
            return False
        if re.match(
            r"^\s*(preheat|heat|bring|make|mix|stir|whisk|crush|cook|bake|roast|fry|"
            r"grill|blanch|season|serve|add|melt|place|put|pour|combine|fold|return|"
            r"remove|drain|peel|chop|slice|cut|toss|leave|cool|refrigerate|strain|"
            r"set|beat|whip|simmer|boil|reduce|cover|unwrap|sear|saute)\b",
            block.text,
            re.IGNORECASE,
        ):
            return True
        word_count = len(block.text.split())
        if word_count >= 8 and re.search(r"[.!?]$", block.text.strip()):
            return True
        if word_count >= 10 and "," in block.text:
            return True
        return False

    def _find_ingredient_start(
        self,
        lines: List[tuple[str, Block]],
    ) -> int | None:
        blocks_only = [block for _, block in lines]
        for idx in range(len(blocks_only)):
            if self._is_ingredient_like(blocks_only[idx]):
                if self._has_ingredient_run(blocks_only, idx):
                    return idx
        return None

    def _find_instruction_start(
        self,
        lines: List[tuple[str, Block]],
        ingredient_start: int | None,
    ) -> int | None:
        if ingredient_start is None:
            return None
        for idx in range(ingredient_start + 1, len(lines)):
            _, block = lines[idx]
            if self._is_instruction_like(block):
                return idx
        return None

    def _merge_wrapped_lines(self, lines: List[str]) -> List[str]:
        merged: List[str] = []
        for line in lines:
            cleaned = line.strip()
            if not cleaned:
                continue
            if not merged:
                merged.append(cleaned)
                continue
            if re.match(r"^\s*(\d+[.)]|[-*•])\s+", cleaned):
                merged.append(cleaned)
                continue
            if re.search(r"[.!?]$", merged[-1]):
                merged.append(cleaned)
                continue
            merged[-1] = f"{merged[-1]} {cleaned}"
        return merged

    def _yield_phrase(self, text: str) -> str | None:
        match = re.match(r"^\s*(serves|yield|yields|makes)\b", text, re.IGNORECASE)
        if not match:
            return None
        remainder = text[match.end():].strip(" :-")
        return remainder or text.strip()

registry.register(EpubImporter())
