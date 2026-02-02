from __future__ import annotations

import logging
import re
import statistics
from pathlib import Path
from typing import Any, Callable, List, Literal, Tuple

import fitz  # type: ignore

from cookimport.core.models import (
    ConversionReport,
    ConversionResult,
    MappingConfig,
    ParsingOverrides,
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
from cookimport.parsing.atoms import Atom, contextualize_atoms, split_text_to_atoms
from cookimport.parsing.tips import (
    build_topic_candidate,
    extract_tip_candidates,
    extract_tip_candidates_from_candidate,
    chunk_standalone_blocks,
    partition_tip_candidates,
)
from cookimport.plugins import registry

logger = logging.getLogger(__name__)


def _ocr_available() -> bool:
    """Check if OCR is available."""
    try:
        from cookimport.ocr.doctr_engine import ocr_available

        return ocr_available()
    except ImportError:
        return False


def _block_to_raw(block: Block, index: int) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "index": index,
        "text": block.text,
        "page": block.page,
        "bbox": block.bbox,
        "type": str(block.type),
        "font_size": block.font_size,
        "font_weight": block.font_weight,
        "alignment": block.alignment,
        "features": block.features,
    }
    # Include OCR-specific info if present
    if block.features.get("ocr_source"):
        raw["ocr_source"] = block.features["ocr_source"]
        if "ocr_confidence" in block.features:
            raw["ocr_confidence"] = block.features["ocr_confidence"]
    return raw

_INSTRUCTION_LEAD_RE = re.compile(
    r"^\s*(preheat|heat|bring|make|mix|stir|whisk|crush|cook|bake|roast|fry|grill|"
    r"blanch|season|serve|add|melt|place|put|pour|combine|fold|return|remove|drain|"
    r"peel|chop|slice|cut|toss|leave|cool|refrigerate|strain|set|beat|whip|simmer|"
    r"boil|reduce|cover|unwrap|sear|saute)\b",
    re.IGNORECASE,
)

class PdfImporter:
    name = "pdf"

    def detect(self, path: Path) -> float:
        if path.suffix.lower() == ".pdf":
            return 0.95
        return 0.0

    def inspect(self, path: Path) -> WorkbookInspection:
        try:
            doc = fitz.open(path)
            page_count = len(doc)
            title = doc.metadata.get("title") or path.stem

            # Check if PDF needs OCR by examining first few pages
            layout = "unknown"
            needs_ocr = False
            text_pages = 0
            image_pages = 0
            pages_to_check = min(page_count, 5)

            for i in range(pages_to_check):
                page = doc[i]
                text = page.get_text()
                if text.strip():
                    text_pages += 1
                else:
                    image_pages += 1

            if text_pages > 0 and image_pages == 0:
                layout = "text-pdf"
            elif image_pages > 0 and text_pages == 0:
                layout = "image-pdf"
                needs_ocr = True
            elif image_pages > text_pages:
                layout = "mixed-pdf"
                needs_ocr = True
            else:
                layout = "text-pdf"

            doc.close()

            warnings = [f"Found {page_count} pages."]
            ocr_engine: Literal["doctr", "none"] = "none"

            if needs_ocr:
                if _ocr_available():
                    warnings.append("Scanned PDF detected. OCR will be used (docTR).")
                    ocr_engine = "doctr"
                else:
                    warnings.append(
                        "Scanned PDF detected but OCR not available. "
                        "Install python-doctr[torch] for OCR support."
                    )

            return WorkbookInspection(
                path=str(path),
                sheets=[
                    SheetInspection(
                        name=title,
                        layout=layout,
                        pageCount=page_count,
                        confidence=0.8 if not needs_ocr else 0.6,
                        warnings=warnings,
                    )
                ],
                mappingStub=MappingConfig(
                    parsing_overrides=ParsingOverrides(name=f"ocr_engine:{ocr_engine}")
                    if needs_ocr
                    else None
                ),
            )
        except Exception as e:
            logger.warning(f"Failed to inspect PDF {path}: {e}")
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
        start_page: int | None = None,
        end_page: int | None = None,
    ) -> ConversionResult:
        report = ConversionReport()
        recipes: List[RecipeCandidate] = []
        tip_candidates: List[Any] = []
        topic_candidates: List[Any] = []
        raw_artifacts: list[RawArtifact] = []
        overrides = mapping.parsing_overrides if mapping else None
        self._overrides = overrides
        ocr_used = False

        try:
            if progress_callback:
                progress_callback("Computing hash...")
            file_hash = compute_file_hash(path)
            doc = fitz.open(path)
            total_pages = len(doc)

            slice_start = 0 if start_page is None else max(start_page, 0)
            slice_end = total_pages if end_page is None else min(end_page, total_pages)

            if slice_start >= slice_end:
                report.warnings.append(
                    f"Requested page range is empty (start_page={slice_start}, end_page={slice_end})."
                )
                doc.close()
                return ConversionResult(
                    recipes=[],
                    tips=[],
                    tipCandidates=[],
                    topicCandidates=[],
                    rawArtifacts=[],
                    report=report,
                    workbook=path.stem,
                    workbookPath=str(path),
                )

            # Check if PDF needs OCR
            needs_ocr = self._needs_ocr(doc)

            # 1. Extract Blocks (Linear Stream)
            all_blocks: List[Block] = []

            if needs_ocr and _ocr_available():
                # Use OCR for scanned PDFs
                if progress_callback:
                    progress_callback("Running OCR (this may take a while)...")
                doc.close()
                ocr_device = mapping.ocr_device if mapping else "auto"
                ocr_batch_size = mapping.ocr_batch_size if mapping else 1
                all_blocks = self._extract_blocks_via_ocr(
                    path,
                    device=ocr_device,
                    batch_size=ocr_batch_size,
                    start_page=slice_start,
                    end_page=slice_end,
                )
                ocr_used = True
                logger.info(f"Extracted {len(all_blocks)} blocks via OCR from {path} (device={ocr_device}, batch_size={ocr_batch_size})")
            else:
                # Use standard text extraction
                slice_total = slice_end - slice_start
                for page_num, abs_page in enumerate(range(slice_start, slice_end)):
                    page = doc[abs_page]
                    if progress_callback and page_num % 5 == 0:
                        progress_callback(
                            f"Extracting text from page {page_num + 1}/{slice_total}..."
                        )
                    page_blocks = self._extract_blocks_from_page(page, abs_page)
                    all_blocks.extend(page_blocks)
                doc.close()
                if needs_ocr and not _ocr_available():
                    report.warnings.append(
                        "Scanned PDF detected but OCR not available. "
                        "Text extraction may be incomplete."
                    )

            artifact_metadata: dict[str, Any] = {"artifact_type": "extracted_blocks"}
            if ocr_used:
                artifact_metadata["ocr_engine"] = "doctr"

            raw_artifacts.append(
                RawArtifact(
                    importer="pdf",
                    sourceHash=file_hash,
                    locationId="full_text",
                    extension="json",
                    content={
                        "blocks": [
                            _block_to_raw(block, idx)
                            for idx, block in enumerate(all_blocks)
                        ],
                        "block_count": len(all_blocks),
                        "ocr_used": ocr_used,
                    },
                    metadata=artifact_metadata,
                )
            )
            
            # 2. Segment into Candidates
            if progress_callback:
                progress_callback(f"Segmenting {len(all_blocks)} blocks...")
            candidates_ranges = self._detect_candidates(all_blocks)
            
            # 3. Extract Fields
            total_candidates = len(candidates_ranges)
            for i, (start, end, segmentation_score) in enumerate(candidates_ranges):
                if progress_callback:
                    progress_callback(f"Extracting candidate {i + 1}/{total_candidates}...")
                try:
                    candidate_blocks = all_blocks[start:end]
                    candidate = self._extract_fields(candidate_blocks)
                    candidate.confidence = score_recipe_candidate(candidate)
                    
                    # Provenance
                    extraction_method = "heuristic_pdf_ocr" if ocr_used else "heuristic_pdf"
                    provenance_builder = ProvenanceBuilder(
                        source_file=path.name,
                        source_hash=file_hash,
                        extraction_method=extraction_method,
                    )

                    # Determine page range
                    start_page = candidate_blocks[0].page if candidate_blocks else 0
                    end_page = candidate_blocks[-1].page if candidate_blocks else 0

                    # Collect OCR confidence for blocks in this candidate
                    ocr_confidences = [
                        b.features.get("ocr_confidence")
                        for b in candidate_blocks
                        if b.features.get("ocr_confidence") is not None
                    ]
                    avg_ocr_confidence = (
                        sum(ocr_confidences) / len(ocr_confidences)
                        if ocr_confidences
                        else None
                    )

                    location_info: dict[str, Any] = {
                        "start_block": start,
                        "end_block": end,
                        "start_page": start_page,
                        "end_page": end_page,
                        "chunk_index": i,
                        "segmentation_score": segmentation_score,
                    }
                    if ocr_used:
                        location_info["ocr_engine"] = "doctr"
                        if avg_ocr_confidence is not None:
                            location_info["ocr_confidence"] = round(avg_ocr_confidence, 3)

                    provenance = provenance_builder.build(
                        confidence_score=candidate.confidence,
                        location=location_info,
                    )
                    candidate.provenance = provenance
                    
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "pdf", file_hash, f"c{i}"
                        )

                    recipes.append(candidate)
                    raw_artifacts.append(
                        RawArtifact(
                            importer="pdf",
                            sourceHash=file_hash,
                            locationId=f"c{i}",
                            extension="json",
                            content={
                                "start_block": start,
                                "end_block": end,
                                "start_page": start_page,
                                "end_page": end_page,
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

            standalone_tips, standalone_topics = self._extract_standalone_tips(
                all_blocks, candidates_ranges, path, file_hash
            )
            tip_candidates.extend(standalone_tips)
            topic_candidates.extend(standalone_topics)

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

            return ConversionResult(
                recipes=recipes,
                tips=tips,
                tipCandidates=tip_candidates,
                topicCandidates=topic_candidates,
                rawArtifacts=raw_artifacts,
                report=report,
                workbook=path.stem,
                workbookPath=str(path),
            )

        except Exception as e:
            logger.error(f"Fatal error converting PDF {path}: {e}")
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
    ) -> tuple[List[Any], List[Any]]:
        covered: set[int] = set()
        for start, end, _ in candidate_ranges:
            covered.update(range(start, end))

        tip_candidates: List[Any] = []
        topic_candidates: List[Any] = []
        provenance_builder = ProvenanceBuilder(
            source_file=path.name,
            source_hash=file_hash,
            extraction_method="heuristic_pdf_tip",
        )

        standalone_blocks: list[tuple[int, str]] = []
        page_lookup: dict[int, int | None] = {}
        bbox_lookup: dict[int, list[float]] = {}
        for idx, block in enumerate(blocks):
            if idx in covered:
                continue
            text = block.text.strip()
            if not text:
                continue
            standalone_blocks.append((idx, text))
            page_lookup[idx] = block.page
            if block.bbox:
                bbox_lookup[idx] = block.bbox

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
            page = page_lookup.get(start_block)
            if page is not None:
                base_location["page"] = page
            bbox = bbox_lookup.get(start_block)
            if bbox:
                base_location["bbox"] = bbox

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

        return tip_candidates, topic_candidates

    def _needs_ocr(self, doc: fitz.Document) -> bool:
        """Check if the PDF needs OCR by examining first few pages."""
        pages_to_check = min(len(doc), 3)
        text_found = 0
        for i in range(pages_to_check):
            page = doc[i]
            text = page.get_text()
            if text.strip():
                text_found += 1

        # If less than half the pages have text, assume OCR is needed
        return text_found < pages_to_check / 2

    def _extract_blocks_via_ocr(
        self,
        path: Path,
        device: str = "auto",
        batch_size: int = 1,
        start_page: int = 0,
        end_page: int | None = None,
    ) -> List[Block]:
        """Extract blocks from a scanned PDF using OCR."""
        from cookimport.ocr.doctr_engine import ocr_pdf

        ocr_pages = ocr_pdf(
            path,
            device=device,
            batch_size=batch_size,
            start_page=start_page,
            end_page=end_page,
        )
        blocks: List[Block] = []

        for page in ocr_pages:
            for line in page.lines:
                text = cleaning.normalize_text(line.text)
                if not text:
                    continue

                # Convert relative bbox (0-1) to absolute-ish coords for consistency
                # The bbox is stored in relative coords (0-1), we'll keep it that way
                # but mark it as relative in features
                bbox_list = [
                    line.bbox[0],
                    line.bbox[1],
                    line.bbox[2],
                    line.bbox[3],
                ]

                block = Block(
                    text=text,
                    type=BlockType.TEXT,
                    bbox=bbox_list,
                    page=page.page_num,
                    font_size=None,  # OCR doesn't provide font info
                    font_weight="normal",
                    alignment=self._infer_ocr_alignment(line.bbox),
                )

                # Mark as OCR'd and store confidence
                block.add_feature("ocr_source", "doctr")
                block.add_feature("ocr_confidence", line.confidence)
                block.add_feature("bbox_relative", True)

                signals.enrich_block(block, overrides=self._overrides)
                blocks.append(block)

        # Since we don't have accurate column info from OCR, do simple sort by y then x
        blocks.sort(key=lambda b: (b.page or 0, b.bbox[1] if b.bbox else 0, b.bbox[0] if b.bbox else 0))

        return blocks

    def _infer_ocr_alignment(self, bbox: tuple[float, float, float, float]) -> str:
        """Infer alignment from OCR bounding box (relative coords 0-1)."""
        x0, _, x1, _ = bbox
        center = (x0 + x1) / 2
        width = x1 - x0

        # If the text spans most of the width, it's likely full-width (left aligned)
        if width > 0.7:
            return "left"
        # If center is near middle, it's centered
        if abs(center - 0.5) < 0.1:
            return "center"
        # If starts near left edge, left aligned
        if x0 < 0.15:
            return "left"
        # If ends near right edge, right aligned
        if x1 > 0.85:
            return "right"
        return "left"

    def _extract_blocks_from_page(self, page: fitz.Page, page_num: int) -> List[Block]:
        """
        Extracts blocks from a PDF page using PyMuPDF.
        Attempts to reconstruct reading order (columns).
        """
        blocks = self._extract_line_blocks(page, page_num)
        if not blocks:
            return []

        self._annotate_heading_features(blocks)

        filtered = [b for b in blocks if not self._is_noise_block(b, page)]
        if not filtered:
            return []

        return self._order_blocks_by_columns(filtered, page.rect.width)

    def _extract_line_blocks(self, page: fitz.Page, page_num: int) -> List[Block]:
        blocks: List[Block] = []
        page_width = page.rect.width
        data = page.get_text("dict")

        for raw_block in data.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            for line in raw_block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans)
                clean_text = cleaning.normalize_text(text)
                if not clean_text:
                    continue

                bbox = line.get("bbox")
                font_size = None
                font_weight = "normal"
                if spans:
                    sizes = [span.get("size") for span in spans if span.get("size")]
                    if sizes:
                        font_size = max(sizes)
                    if any("bold" in str(span.get("font", "")).lower() for span in spans):
                        font_weight = "bold"

                alignment = self._infer_alignment(bbox, page_width) if bbox else None

                block = Block(
                    text=clean_text,
                    type=BlockType.TEXT,
                    bbox=list(bbox) if bbox else None,
                    page=page_num + 1,
                    font_size=font_size,
                    font_weight=font_weight,
                    alignment=alignment,
                )

                signals.enrich_block(block, overrides=self._overrides)
                blocks.append(block)

        return blocks

    def _annotate_heading_features(self, blocks: List[Block]) -> None:
        sizes = [b.font_size for b in blocks if b.font_size]
        if not sizes:
            return

        sizes_sorted = sorted(sizes)
        upper_half = sizes_sorted[len(sizes_sorted) // 2 :]
        median_size = statistics.median(upper_half)
        heading_threshold = max(median_size * 1.25, median_size + 2.0)
        strong_heading = max(median_size * 1.5, median_size + 4.0)

        for block in blocks:
            if block.font_size and block.font_size >= heading_threshold:
                block.add_feature("is_heading", True)
                block.add_feature(
                    "heading_level",
                    1 if block.font_size >= strong_heading else 2,
                )
            if block.font_weight == "bold" and len(block.text) <= 80:
                block.add_feature("is_heading", True)
            if block.alignment == "center" and block.text.isupper() and len(block.text) <= 30:
                block.add_feature("is_section_header", True)

    def _infer_alignment(self, bbox: List[float], page_width: float) -> str | None:
        if not bbox or page_width <= 0:
            return None
        x0, _, x1, _ = bbox
        center = (x0 + x1) / 2
        if abs(center - page_width / 2) <= page_width * 0.08:
            return "center"
        if x0 <= page_width * 0.15:
            return "left"
        if x1 >= page_width * 0.85:
            return "right"
        return "left"

    def _is_noise_block(self, block: Block, page: fitz.Page) -> bool:
        text = block.text.strip()
        if not text:
            return True
        if not block.bbox:
            return False
        _, y0, _, y1 = block.bbox
        page_height = page.rect.height
        if text.isdigit() and (y0 <= page_height * 0.06 or y1 >= page_height * 0.94):
            return True
        return False

    def _order_blocks_by_columns(self, blocks: List[Block], page_width: float) -> List[Block]:
        boundaries = self._derive_column_boundaries(blocks, page_width)

        for block in blocks:
            column_id = 0
            if block.bbox:
                x0, _, x1, _ = block.bbox
                width = x1 - x0
                if block.alignment == "center" or width >= page_width * 0.7:
                    column_id = 0
                    block.add_feature("full_width", True)
                else:
                    column_id = sum(1 for boundary in boundaries if x0 >= boundary)
            block.add_feature("column_id", column_id)

        def sort_key(b: Block) -> tuple[int, int, float, float]:
            page_num = b.page or 0
            column_id = int(b.features.get("column_id", 0))
            y0 = b.bbox[1] if b.bbox else 0.0
            x0 = b.bbox[0] if b.bbox else 0.0
            return (page_num, column_id, y0, x0)

        return sorted(blocks, key=sort_key)

    def _derive_column_boundaries(self, blocks: List[Block], page_width: float) -> List[float]:
        x0s: List[float] = []
        for block in blocks:
            if not block.bbox:
                continue
            x0, _, x1, _ = block.bbox
            width = x1 - x0
            if width >= page_width * 0.7:
                continue
            x0s.append(x0)

        if len(x0s) < 4:
            return []

        x0s.sort()
        gaps: List[tuple[float, int]] = []
        for idx in range(len(x0s) - 1):
            gaps.append((x0s[idx + 1] - x0s[idx], idx))

        threshold = page_width * 0.12
        boundaries = [
            (x0s[idx] + x0s[idx + 1]) / 2
            for gap, idx in gaps
            if gap >= threshold
        ]
        return sorted(boundaries)

    def _detect_candidates(self, blocks: List[Block]) -> List[Tuple[int, int, float]]:
        """
        Segments blocks into recipes. 
        Reusing logic similar to EPUB but adapted for PDF flow.
        """
        candidates: List[Tuple[int, int, float]] = []

        i = 0
        while i < len(blocks):
            if self._is_recipe_anchor(blocks, i):
                start_idx = self._backtrack_for_title(blocks, i)
                if start_idx == -1:
                    start_idx = i

                end_idx = self._find_recipe_end(blocks, start_idx, i)
                score = 6.0
                candidates.append((start_idx, end_idx, score))

                i = end_idx
                continue

            i += 1

        return candidates

    def _backtrack_for_title(self, blocks: List[Block], ingredient_idx: int) -> int:
        limit = 20
        best_idx = -1
        anchor_col = blocks[ingredient_idx].features.get("column_id")

        for i in range(ingredient_idx - 1, max(-1, ingredient_idx - limit), -1):
            b = blocks[i]

            if b.features.get("column_id") != anchor_col:
                continue

            if b.features.get("is_ingredient_header"):
                break

            if self._is_title_candidate(b):
                start_idx = i
                while (
                    start_idx - 1 >= 0
                    and self._is_title_candidate(blocks[start_idx - 1])
                    and self._title_continuation(blocks[start_idx - 1], blocks[start_idx])
                ):
                    start_idx -= 1
                return start_idx

        return best_idx

    def _find_recipe_end(self, blocks: List[Block], start_idx: int, anchor_idx: int) -> int:
        anchor_col = blocks[start_idx].features.get("column_id")
        seen_ingredient = False
        seen_instruction = False
        for i in range(anchor_idx + 1, len(blocks)):
            b = blocks[i]
            if self._is_ingredient_like(b):
                seen_ingredient = True
            if self._is_instruction_like(b):
                seen_instruction = True
            if b.features.get("column_id") != anchor_col:
                if (
                    seen_ingredient
                    and not seen_instruction
                    and self._looks_like_continuation(blocks, i)
                ):
                    anchor_col = b.features.get("column_id")
                    continue
                return i
            if b.features.get("is_section_header") and b.features.get("heading_level") == 1:
                return i
            if self._is_title_candidate(b) and self._has_ingredient_run(blocks, i):
                return i

        return len(blocks)

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

        # If explicit headers exist, use them.
        has_header = any(b.features.get("is_ingredient_header") for b in content_blocks)
        if has_header:
            current_section = "description"
            for b in content_blocks:
                if b.features.get("is_ingredient_header"):
                    current_section = "ingredients"
                    continue
                if b.features.get("is_instruction_header"):
                    current_section = "instructions"
                    continue
                if b.features.get("is_yield") and recipe_yield is None:
                    recipe_yield = b.text.strip()
                    continue

                if current_section == "ingredients":
                    clean = re.sub(r"^\s*[-*•]\s*", "", b.text)
                    ingredients.append(clean)
                elif current_section == "instructions":
                    clean = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", b.text)
                    instructions.append(clean)
                elif current_section == "description":
                    description.append(b.text)
        else:
            lines: List[tuple[str, Block]] = []
            for block in content_blocks:
                text = block.text.strip()
                if not text:
                    continue
                lines.append((text, block))
                if block.features.get("is_yield"):
                    remainder = self._yield_remainder(text)
                    if remainder:
                        remainder_block = block.model_copy(deep=True)
                        remainder_block.text = remainder
                        remainder_block.add_feature("is_yield", False)
                        lines.append((remainder, remainder_block))

            yield_idx: int | None = None
            for idx, (text, block) in enumerate(lines):
                if block.features.get("is_yield") and recipe_yield is None:
                    recipe_yield = text
                    yield_idx = idx

            ingredient_start = self._find_ingredient_start(
                lines,
                start_at=(yield_idx + 1 if yield_idx is not None else 0),
            )
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

    def _is_recipe_anchor(self, blocks: List[Block], idx: int) -> bool:
        block = blocks[idx]
        if block.features.get("is_ingredient_header"):
            return True
        if self._is_ingredient_like(block) and self._has_ingredient_run(blocks, idx):
            return True
        if block.features.get("is_yield") and self._has_ingredient_run(blocks, idx):
            return True
        return False

    def _is_title_candidate(self, block: Block) -> bool:
        text = block.text.strip()
        if not text or len(text) > 80:
            return False
        if block.features.get("is_section_header"):
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

    def _title_continuation(self, previous: Block, current: Block) -> bool:
        if previous.features.get("column_id") != current.features.get("column_id"):
            return False
        if not previous.bbox or not current.bbox:
            return False
        gap = current.bbox[1] - previous.bbox[3]
        if gap > 12:
            return False
        if previous.font_size and current.font_size:
            if abs(previous.font_size - current.font_size) > 2.5:
                return False
        return True

    def _has_ingredient_run(
        self,
        blocks: List[Block],
        start_idx: int,
        window: int = 8,
    ) -> bool:
        if not blocks:
            return False
        anchor_col = blocks[start_idx].features.get("column_id")
        count = 0
        for idx in range(start_idx, min(len(blocks), start_idx + window)):
            block = blocks[idx]
            if block.features.get("column_id") != anchor_col:
                continue
            if self._is_ingredient_like(block):
                count += 1
            if count >= 2:
                return True
        return False

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
        if _INSTRUCTION_LEAD_RE.match(block.text):
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
        start_at: int = 0,
    ) -> int | None:
        blocks_only = [block for _, block in lines]
        for idx in range(start_at, len(blocks_only)):
            block = blocks_only[idx]
            if self._is_ingredient_like(block):
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

    def _extract_title(self, blocks: List[Block]) -> tuple[str, int]:
        if not blocks:
            return ("Untitled Recipe", 0)
        title_parts: List[str] = []
        idx = 0
        while idx < len(blocks):
            block = blocks[idx]
            if not self._is_title_candidate(block):
                break
            if title_parts and not self._title_continuation(blocks[idx - 1], block):
                break
            title_parts.append(block.text.strip())
            idx += 1
            if len(title_parts) >= 3:
                break
        if title_parts:
            return (" ".join(title_parts), idx)
        return (blocks[0].text.strip(), 1)

    def _yield_remainder(self, text: str) -> str | None:
        match = re.match(r"^\s*(serves|yield|makes)\b", text, re.IGNORECASE)
        if not match:
            return None
        remainder = text[match.end():].strip(" :-")
        if not remainder:
            return None
        parts = remainder.split()
        if parts and re.match(r"^\d", parts[0]) and len(parts) > 1:
            remainder = " ".join(parts[1:])
        if not remainder:
            return None
        feats = signals.classify_block(remainder, overrides=self._overrides)
        if feats.get("has_unit"):
            return remainder
        if feats.get("starts_with_quantity") and len(remainder.split()) >= 3:
            return remainder
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

    def _looks_like_continuation(
        self,
        blocks: List[Block],
        start_idx: int,
        window: int = 6,
    ) -> bool:
        for idx in range(start_idx, min(len(blocks), start_idx + window)):
            block = blocks[idx]
            if self._is_title_candidate(block):
                return False
            if self._is_instruction_like(block):
                return True
            text = block.text.strip()
            if text and text[0].islower() and len(text.split()) >= 8:
                return True
        return False

registry.register(PdfImporter())
