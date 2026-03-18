from __future__ import annotations

import json
import logging
import os
import re
import warnings
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Callable, List, Tuple

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
from cookimport.core.progress_messages import format_task_counter
from cookimport.core.scoring import (
    build_recipe_scoring_debug_row,
    recipe_gate_action,
    score_recipe_likeness,
    summarize_recipe_likeness,
)
from cookimport.core.blocks import Block, BlockType
from cookimport.epub_extractor_names import (
    EPUB_EXTRACTOR_CANONICAL_SET,
    EPUB_EXTRACTOR_DEFAULT,
    normalize_epub_extractor_name,
)
from cookimport.parsing import cleaning, signals
from cookimport.parsing.epub_extractors import (
    BeautifulSoupEpubExtractor,
    EpubExtractor,
    MarkdownEpubExtractor,
    UnstructuredEpubExtractor,
)
from cookimport.parsing.epub_health import compute_epub_extraction_health
from cookimport.parsing.epub_postprocess import postprocess_epub_blocks
from cookimport.parsing.epub_table_rows import (
    build_structured_epub_row_block,
    structured_epub_row_from_tag,
)
from cookimport.parsing.markitdown_adapter import convert_path_to_markdown
from cookimport.parsing.block_roles import assign_block_roles
from cookimport.parsing.multi_recipe_splitter import (
    MultiRecipeSplitConfig,
    split_candidate_blocks,
)
from cookimport.parsing.pattern_flags import (
    OverlapCandidate,
    apply_candidate_start_trims,
    detect_deterministic_patterns,
    normalize_title_for_pattern,
    pattern_warning_lines,
    resolve_overlap_duplicate_candidates,
)
from cookimport.parsing.section_detector import (
    SectionKind,
    detect_sections_from_blocks,
)
from cookimport.parsing.atoms import Atom, contextualize_atoms, split_text_to_atoms
from cookimport.parsing.tips import (
    build_topic_candidate,
    classify_standalone_topic_filter_reason,
    extract_tip_candidates,
    extract_tip_candidates_from_candidate,
    chunk_standalone_blocks,
    partition_tip_candidates,
)
from cookimport.plugins import registry

# ---------------------------------------------------------------------------
# Extractor switch: C3IMP_EPUB_EXTRACTOR = beautifulsoup | unstructured | markdown | markitdown
# Default: unstructured
# Read at call time (not import time) so interactive settings take effect.
# ---------------------------------------------------------------------------
_EPUB_EXTRACTOR_DEFAULT = EPUB_EXTRACTOR_DEFAULT
_EPUB_EXTRACTOR_CHOICES = set(EPUB_EXTRACTOR_CANONICAL_SET)
_UNSTRUCTURED_HTML_PARSER_VERSION_DEFAULT = "v1"
_UNSTRUCTURED_HTML_PARSER_VERSION_CHOICES = {"v1", "v2"}
_UNSTRUCTURED_PREPROCESS_MODE_DEFAULT = "br_split_v1"
_UNSTRUCTURED_PREPROCESS_MODE_CHOICES = {"none", "br_split_v1", "semantic_v1"}
_STANDALONE_ANALYSIS_WORKERS_DEFAULT = 4
_STANDALONE_ANALYSIS_WORKERS_ENV = "C3IMP_STANDALONE_ANALYSIS_WORKERS"
_LONG_STANDALONE_BLOCK_CHAR_THRESHOLD = 420
_LONG_STANDALONE_BLOCK_WORD_THRESHOLD = 70
_STANDALONE_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_SINGLETON_INGREDIENT_WORDS = {
    "butter",
    "cheese",
    "cream",
    "egg",
    "eggs",
    "flour",
    "garlic",
    "milk",
    "oil",
    "onion",
    "onions",
    "pepper",
    "salt",
    "stock",
    "sugar",
    "vinegar",
    "water",
}


def _get_epub_extractor() -> str:
    selected = normalize_epub_extractor_name(
        os.environ.get("C3IMP_EPUB_EXTRACTOR", _EPUB_EXTRACTOR_DEFAULT).strip().lower()
    )
    if selected in _EPUB_EXTRACTOR_CHOICES:
        return selected
    if selected:
        logging.getLogger(__name__).warning(
            "Unknown C3IMP_EPUB_EXTRACTOR=%r. Falling back to %s.",
            selected,
            _EPUB_EXTRACTOR_DEFAULT,
        )
    return _EPUB_EXTRACTOR_DEFAULT


def _get_unstructured_html_parser_version() -> str:
    selected = os.environ.get(
        "C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION",
        _UNSTRUCTURED_HTML_PARSER_VERSION_DEFAULT,
    ).strip().lower()
    if selected in _UNSTRUCTURED_HTML_PARSER_VERSION_CHOICES:
        return selected
    if selected:
        logger.warning(
            "Unknown C3IMP_EPUB_UNSTRUCTURED_HTML_PARSER_VERSION=%r. Falling back to %s.",
            selected,
            _UNSTRUCTURED_HTML_PARSER_VERSION_DEFAULT,
        )
    return _UNSTRUCTURED_HTML_PARSER_VERSION_DEFAULT


def _get_unstructured_skip_headers_footers() -> bool:
    raw_value = os.environ.get("C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS")
    if raw_value is None:
        return False
    normalized = str(raw_value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    logger.warning(
        "Unknown C3IMP_EPUB_UNSTRUCTURED_SKIP_HEADERS_FOOTERS=%r. Falling back to false.",
        raw_value,
    )
    return False


def _get_unstructured_preprocess_mode() -> str:
    selected = os.environ.get(
        "C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE",
        _UNSTRUCTURED_PREPROCESS_MODE_DEFAULT,
    ).strip().lower()
    if selected in _UNSTRUCTURED_PREPROCESS_MODE_CHOICES:
        return selected
    if selected:
        logger.warning(
            "Unknown C3IMP_EPUB_UNSTRUCTURED_PREPROCESS_MODE=%r. Falling back to %s.",
            selected,
            _UNSTRUCTURED_PREPROCESS_MODE_DEFAULT,
        )
    return _UNSTRUCTURED_PREPROCESS_MODE_DEFAULT


def _get_standalone_analysis_workers() -> int:
    raw_value = os.environ.get(
        _STANDALONE_ANALYSIS_WORKERS_ENV,
        str(_STANDALONE_ANALYSIS_WORKERS_DEFAULT),
    )
    try:
        parsed = int(str(raw_value).strip())
    except (TypeError, ValueError):
        logger.warning(
            "Invalid %s=%r. Falling back to %s.",
            _STANDALONE_ANALYSIS_WORKERS_ENV,
            raw_value,
            _STANDALONE_ANALYSIS_WORKERS_DEFAULT,
        )
        return _STANDALONE_ANALYSIS_WORKERS_DEFAULT
    return max(1, parsed)

# Suppress ebooklib warnings about future/deprecations if any
warnings.filterwarnings("ignore", category=UserWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=FutureWarning, module="ebooklib")
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cookimport.config.run_settings import RunSettings


@dataclass(frozen=True)
class EpubSpineItem:
    path: str
    media_type: str
    item_id: str
    properties: tuple[str, ...] = ()


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


def _split_long_standalone_block_text(text: str) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    words = cleaned.split()
    if (
        len(cleaned) < _LONG_STANDALONE_BLOCK_CHAR_THRESHOLD
        and len(words) < _LONG_STANDALONE_BLOCK_WORD_THRESHOLD
    ):
        return [cleaned]
    sentences = [
        sentence.strip()
        for sentence in _STANDALONE_SENTENCE_SPLIT_RE.split(cleaned)
        if sentence.strip()
    ]
    if len(sentences) <= 1:
        return [cleaned]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not current:
            current = sentence
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= 260:
            current = candidate
            continue
        chunks.append(current)
        current = sentence
    if current:
        chunks.append(current)
    return chunks or [cleaned]


class EpubImporter:
    name = "epub"

    def __init__(self) -> None:
        # Auto-extractor probing calls _extract_docpack() directly without convert().
        # Keep defaults initialized so probe paths share the same runtime contract.
        self._overrides = None
        self._section_detector_backend = "shared_v1"
        self._standalone_filter_diagnostics: dict[str, Any] = {}

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
        run_settings: RunSettings | None = None,
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
        self._section_detector_backend = str(
            getattr(getattr(run_settings, "section_detector_backend", None), "value", "shared_v1")
        )

        def _notify(message: str) -> None:
            if progress_callback:
                progress_callback(message)
        
        try:
            _notify("Computing hash...")
            file_hash = compute_file_hash(path)
            selected_extractor = _get_epub_extractor()
            report.epub_backend = selected_extractor
            
            # 1. Extract Blocks (DocPack)
            _notify("Extracting blocks from EPUB...")
            blocks = self._extract_docpack(
                path,
                start_spine=start_spine,
                end_spine=end_spine,
                extractor=selected_extractor,
            )
            
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

            if selected_extractor == "unstructured" and self._unstructured_spine_xhtml:
                for entry in self._unstructured_spine_xhtml:
                    spine_index = int(entry["spine_index"])
                    raw_artifacts.append(
                        RawArtifact(
                            importer="epub",
                            sourceHash=file_hash,
                            locationId=f"raw_spine_xhtml_{spine_index:04d}",
                            extension="xhtml",
                            content=str(entry["raw_html"]),
                            metadata={
                                "artifact_type": "unstructured_raw_spine_xhtml",
                                "extractor": "unstructured",
                                "spine_index": spine_index,
                            },
                        )
                    )
                    raw_artifacts.append(
                        RawArtifact(
                            importer="epub",
                            sourceHash=file_hash,
                            locationId=f"norm_spine_xhtml_{spine_index:04d}",
                            extension="xhtml",
                            content=str(entry["normalized_html"]),
                            metadata={
                                "artifact_type": "unstructured_norm_spine_xhtml",
                                "extractor": "unstructured",
                                "spine_index": spine_index,
                                "unstructured_preprocess_mode": self._unstructured_preprocess_mode,
                            },
                        )
                    )

            if selected_extractor == "markitdown" and self._markitdown_markdown is not None:
                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId="markitdown_markdown",
                        extension="md",
                        content=self._markitdown_markdown,
                        metadata={
                            "artifact_type": "markitdown_markdown",
                            "extractor": "markitdown",
                            "line_count": len(self._markitdown_markdown.splitlines()),
                        },
                    )
                )

            # Assign deterministic block roles for chunk lane selection
            assign_block_roles(blocks)

            health = compute_epub_extraction_health(blocks)
            raw_artifacts.append(
                RawArtifact(
                    importer="epub",
                    sourceHash=file_hash,
                    locationId="epub_extraction_health",
                    extension="json",
                    content=health,
                    metadata={"artifact_type": "epub_extraction_health"},
                )
            )
            report.warnings.extend(health.get("warnings", []))

            extractor_diagnostics = self._extractor_diagnostics.get(selected_extractor, [])
            if extractor_diagnostics:
                location_ids = {
                    "unstructured": "unstructured_elements",
                    "beautifulsoup": "beautifulsoup_elements",
                    "markdown": "markdown_blocks",
                }
                artifact_ids = {
                    "unstructured": "unstructured_diagnostics",
                    "beautifulsoup": "beautifulsoup_diagnostics",
                    "markdown": "markdown_diagnostics",
                }
                jsonl_lines = "\n".join(
                    json.dumps(row, ensure_ascii=False)
                    for row in extractor_diagnostics
                )
                metadata: dict[str, Any] = {
                    "artifact_type": artifact_ids.get(
                        selected_extractor, "epub_extractor_diagnostics"
                    ),
                    "extractor": selected_extractor,
                    "element_count": len(extractor_diagnostics),
                }
                metadata.update(self._extractor_meta.get(selected_extractor, {}))

                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId=location_ids.get(
                            selected_extractor,
                            f"{selected_extractor}_elements",
                        ),
                        extension="jsonl",
                        content=jsonl_lines,
                        metadata=metadata,
                    )
                )

            pattern_diagnostics = detect_deterministic_patterns(blocks)
            for idx, flags in pattern_diagnostics.block_flags.items():
                if not (0 <= idx < len(blocks)):
                    continue
                for flag in sorted(flags):
                    blocks[idx].add_feature(flag, True)
            for idx in pattern_diagnostics.excluded_indices:
                if 0 <= idx < len(blocks):
                    blocks[idx].add_feature("exclude_from_candidate_detection", True)

            # 2. Segment into Candidates
            _notify(f"Segmenting {len(blocks)} blocks...")
            candidates_ranges = self._detect_candidates(blocks)
            (
                candidates_ranges,
                candidate_multi_recipe_meta,
                split_trace_payload,
            ) = self._apply_multi_recipe_splitter(
                blocks,
                candidates_ranges,
                run_settings=run_settings,
            )
            if split_trace_payload is not None:
                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId="multi_recipe_split_trace",
                        extension="json",
                        content=split_trace_payload,
                        metadata={
                            "artifact_type": "multi_recipe_split_trace",
                            "backend": split_trace_payload.get("backend", "rules_v1"),
                        },
                    )
                )
            candidates_ranges, pattern_trim_actions = apply_candidate_start_trims(
                candidates_ranges,
                pattern_diagnostics,
            )
            pattern_trim_actions_by_candidate = {
                int(action.get("candidate_index", -1)): dict(action)
                for action in pattern_trim_actions
            }
            accepted_candidate_ranges: list[tuple[int, int, float]] = []
            rejected_block_details: dict[int, dict[str, Any]] = {}
            recipe_likeness_results = []
            recipe_scoring_debug_rows: list[dict[str, Any]] = []
            rejected_candidate_count = 0
            candidate_records: list[dict[str, Any]] = []
            
            # 3. Extract Fields
            total_candidates = len(candidates_ranges)
            for i, (start, end, segmentation_score) in enumerate(candidates_ranges):
                _notify(f"Extracting candidate {i + 1}/{total_candidates}...")
                try:
                    candidate_blocks = blocks[start:end]
                    candidate = self._extract_fields(candidate_blocks)
                    multi_recipe_meta = (
                        candidate_multi_recipe_meta[i]
                        if i < len(candidate_multi_recipe_meta)
                        else None
                    )
                    
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
                        "pattern_detector_version": pattern_diagnostics.version,
                    }
                    candidate_pattern_flags = pattern_diagnostics.flags_for_span(start, end)
                    candidate_pattern_actions: list[dict[str, Any]] = []
                    trim_action = pattern_trim_actions_by_candidate.get(i)
                    if trim_action is not None:
                        candidate_pattern_actions.append(dict(trim_action))
                        if "duplicate_title_intro" not in candidate_pattern_flags:
                            candidate_pattern_flags.append("duplicate_title_intro")
                    if candidate_pattern_flags:
                        location_info["pattern_flags"] = sorted(set(candidate_pattern_flags))
                    if candidate_pattern_actions:
                        location_info["pattern_actions"] = list(candidate_pattern_actions)
                    if multi_recipe_meta is not None:
                        location_info["multi_recipe"] = multi_recipe_meta
                    if spine_values:
                        location_info["start_spine"] = min(spine_values)
                        location_info["end_spine"] = max(spine_values)
                    location_for_debug = dict(location_info)
                    provenance = provenance_builder.build(
                        confidence_score=0.0,
                        location=location_info,
                    )
                    candidate.provenance = provenance
                    if multi_recipe_meta is not None and isinstance(candidate.provenance, dict):
                        candidate.provenance["multi_recipe"] = dict(multi_recipe_meta)
                    
                    if not candidate.identifier:
                        candidate.identifier = generate_recipe_id(
                            "epub", file_hash, f"c{i}"
                        )

                    likeness = score_recipe_likeness(candidate, settings=run_settings)
                    gate_action = recipe_gate_action(likeness, settings=run_settings)

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

                    candidate_records.append(
                        {
                            "candidate": candidate,
                            "candidate_blocks": candidate_blocks,
                            "start": start,
                            "end": end,
                            "segmentation_score": segmentation_score,
                            "location_info": location_info,
                            "location_for_debug": location_for_debug,
                            "likeness": likeness,
                            "gate_action": gate_action,
                            "candidate_index": i,
                        }
                    )
                    
                except Exception as e:
                    logger.warning(f"Failed to extract candidate {i} in {path}: {e}")
                    report.warnings.append(f"Failed to parse candidate {i}: {e}")

            overlap_decisions = resolve_overlap_duplicate_candidates(
                [
                    OverlapCandidate(
                        candidate_index=int(record["candidate_index"]),
                        start_block=int(record["start"]),
                        end_block=int(record["end"]),
                        normalized_title=normalize_title_for_pattern(
                            str(getattr(record["candidate"], "name", "") or "")
                        ),
                        score=float(record["likeness"].score),
                    )
                    for record in candidate_records
                ]
            )
            overlap_decisions_by_loser = {
                int(decision.get("loser_candidate_index", -1)): decision
                for decision in overlap_decisions
            }

            for record in candidate_records:
                candidate = record["candidate"]
                start = int(record["start"])
                end = int(record["end"])
                segmentation_score = float(record["segmentation_score"])
                candidate_blocks = record["candidate_blocks"]
                location_info = dict(record["location_info"])
                location_for_debug = dict(record["location_for_debug"])
                candidate_index = int(record["candidate_index"])
                likeness = record["likeness"]
                gate_action = str(record["gate_action"])

                overlap_decision = overlap_decisions_by_loser.get(candidate_index)
                if overlap_decision is not None:
                    pattern_flags = set(
                        str(flag).strip()
                        for flag in location_info.get("pattern_flags", [])
                        if str(flag).strip()
                    )
                    pattern_flags.add("overlap_duplicate_candidate")
                    pattern_actions = [
                        dict(action)
                        for action in location_info.get("pattern_actions", [])
                        if isinstance(action, dict)
                    ]
                    pattern_actions.append(dict(overlap_decision))
                    location_info["pattern_flags"] = sorted(pattern_flags)
                    location_info["pattern_actions"] = pattern_actions
                    location_for_debug["pattern_flags"] = sorted(pattern_flags)
                    location_for_debug["pattern_actions"] = pattern_actions
                    if isinstance(candidate.provenance, dict):
                        location_payload = candidate.provenance.get("location")
                        if not isinstance(location_payload, dict):
                            location_payload = {}
                        location_payload.update(
                            {
                                "pattern_detector_version": pattern_diagnostics.version,
                                "pattern_flags": sorted(pattern_flags),
                                "pattern_actions": pattern_actions,
                            }
                        )
                        candidate.provenance["location"] = location_payload
                    likeness = score_recipe_likeness(candidate, settings=run_settings)
                    forced_features = dict(likeness.features)
                    forced_features["forced_overlap_duplicate_reject"] = True
                    forced_reasons = list(likeness.reasons)
                    if "pattern_overlap_duplicate_reject" not in forced_reasons:
                        forced_reasons.append("pattern_overlap_duplicate_reject")
                    likeness = likeness.model_copy(
                        update={"features": forced_features, "reasons": forced_reasons}
                    )
                    gate_action = "reject"

                candidate.recipe_likeness = likeness
                candidate.confidence = likeness.score
                if isinstance(candidate.provenance, dict):
                    candidate.provenance["confidence_score"] = candidate.confidence
                recipe_likeness_results.append(likeness)
                recipe_scoring_debug_rows.append(
                    build_recipe_scoring_debug_row(
                        candidate=candidate,
                        result=likeness,
                        gate_action=gate_action,
                        candidate_index=candidate_index,
                        location=location_for_debug,
                        importer="epub",
                        source_hash=file_hash,
                    )
                )

                if gate_action == "reject":
                    rejected_candidate_count += 1
                    for block_idx, block in enumerate(candidate_blocks, start=start):
                        text = block.text.strip()
                        if not text:
                            continue
                        features = dict(block.features) if isinstance(block.features, dict) else {}
                        features.update(
                            {
                                "source": "rejected_recipe_candidate",
                                "gate_action": gate_action,
                                "score": likeness.score,
                                "tier": likeness.tier.value,
                            }
                        )
                        if location_info.get("pattern_flags"):
                            features["pattern_flags"] = list(location_info.get("pattern_flags", []))
                        if location_info.get("pattern_actions"):
                            features["pattern_actions"] = list(
                                location_info.get("pattern_actions", [])
                            )
                        rejected_block_details[block_idx] = {
                            "location": {
                                "start_block": start,
                                "end_block": end,
                                "chunk_index": candidate_index,
                            },
                            "features": features,
                        }
                    continue

                accepted_candidate_ranges.append((start, end, segmentation_score))
                recipes.append(candidate)
                tip_candidates.extend(
                    extract_tip_candidates_from_candidate(candidate, overrides=overrides)
                )

            if recipe_scoring_debug_rows:
                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId="recipe_scoring_debug",
                        extension="jsonl",
                        content="\n".join(
                            json.dumps(row, sort_keys=True)
                            for row in recipe_scoring_debug_rows
                        ),
                        metadata={"artifact_type": "recipe_scoring_debug"},
                    )
                )
            raw_artifacts.append(
                RawArtifact(
                    importer="epub",
                    sourceHash=file_hash,
                    locationId="pattern_diagnostics",
                    extension="json",
                    content={
                        **pattern_diagnostics.to_artifact_content(total_blocks=len(blocks)),
                        "candidate_start_trim_actions": pattern_trim_actions,
                        "overlap_duplicate_resolutions": overlap_decisions,
                    },
                    metadata={
                        "artifact_type": "pattern_diagnostics",
                        "detector_version": pattern_diagnostics.version,
                    },
                )
            )
            for warning in pattern_warning_lines(
                pattern_diagnostics,
                overlap_dropped_count=len(overlap_decisions),
            ):
                if warning not in report.warnings:
                    report.warnings.append(warning)

            _notify("Analyzing standalone knowledge blocks...")
            (
                standalone_tips,
                standalone_topics,
                standalone_block_count,
                topic_block_count,
            ) = self._extract_standalone_tips(
                blocks,
                accepted_candidate_ranges,
                path,
                file_hash,
                accepted_recipe_titles=[recipe.name for recipe in recipes],
                progress_callback=_notify,
            )
            tip_candidates.extend(standalone_tips)
            topic_candidates.extend(standalone_topics)
            standalone_filter_diagnostics = (
                dict(self._standalone_filter_diagnostics)
                if isinstance(self._standalone_filter_diagnostics, dict)
                else {}
            )
            if standalone_filter_diagnostics:
                raw_artifacts.append(
                    RawArtifact(
                        importer="epub",
                        sourceHash=file_hash,
                        locationId="standalone_tip_filter_diagnostics",
                        extension="json",
                        content=standalone_filter_diagnostics,
                        metadata={
                            "artifact_type": "standalone_tip_filter_diagnostics",
                        },
                    )
                )
                reason_counts = standalone_filter_diagnostics.get(
                    "filter_reason_counts"
                )
                if isinstance(reason_counts, dict) and reason_counts:
                    reason_summary = ", ".join(
                        f"{key}={int(value or 0)}"
                        for key, value in sorted(reason_counts.items())
                        if int(value or 0) > 0
                    )
                    if reason_summary:
                        report.warnings.append(
                            "standalone_tip_filtering_applied: " + reason_summary
                        )

            # Collect non-recipe blocks for knowledge chunking
            covered: set[int] = set()
            for start, end, _ in accepted_candidate_ranges:
                covered.update(range(start, end))
            non_recipe_blocks: list[dict[str, Any]] = []
            for idx, block in enumerate(blocks):
                if idx in covered or not block.text.strip():
                    continue
                base_features = dict(block.features) if isinstance(block.features, dict) else {}
                payload: dict[str, Any] = {
                    "index": idx,
                    "text": block.text,
                    "features": base_features,
                }
                rejected_detail = rejected_block_details.get(idx)
                if rejected_detail:
                    payload["features"] = dict(rejected_detail.get("features") or {})
                    location = rejected_detail.get("location")
                    if isinstance(location, dict):
                        payload["location"] = location
                non_recipe_blocks.append(payload)

            _notify("Finalizing EPUB extraction results...")
            tips, recipe_specific, not_tips = partition_tip_candidates(tip_candidates)

            report.total_recipes = len(recipes)
            report.total_tips = len(tips)
            report.total_tip_candidates = len(tip_candidates)
            report.total_topic_candidates = len(topic_candidates)
            report.total_general_tips = len(tips)
            report.total_recipe_specific_tips = len(recipe_specific)
            report.total_not_tips = len(not_tips)
            report.recipe_likeness = summarize_recipe_likeness(
                recipe_likeness_results,
                rejected_candidate_count,
                settings=run_settings,
            )
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

            _notify("EPUB conversion complete.")
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
            self._section_detector_backend = "shared_v1"
            self._standalone_filter_diagnostics = {}

    def _extract_standalone_tips(
        self,
        blocks: List[Block],
        candidate_ranges: List[Tuple[int, int, float]],
        path: Path,
        file_hash: str,
        accepted_recipe_titles: list[str] | None = None,
        progress_callback: Callable[[str], None] | None = None,
    ) -> tuple[List[Any], List[Any], int, int]:
        def _notify(message: str) -> None:
            if progress_callback is not None:
                progress_callback(message)

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
        normalized_recipe_titles = {
            normalize_title_for_pattern(str(title or ""))
            for title in (accepted_recipe_titles or [])
            if str(title or "").strip()
        }
        normalized_recipe_titles.discard("")
        filter_reason_counts: dict[str, int] = {}
        long_split_source_blocks = 0
        long_split_segments_added = 0

        candidate_standalone_block_count = 0
        standalone_blocks: list[tuple[int, str]] = []
        for idx, block in enumerate(blocks):
            if idx in covered:
                continue
            text = block.text.strip()
            if not text:
                continue
            candidate_standalone_block_count += 1
            filter_reason = classify_standalone_topic_filter_reason(text)
            if filter_reason is None:
                normalized_text = normalize_title_for_pattern(text)
                if normalized_text and normalized_text in normalized_recipe_titles:
                    filter_reason = "duplicate_title_carryover"
            if filter_reason is not None:
                filter_reason_counts[filter_reason] = (
                    int(filter_reason_counts.get(filter_reason) or 0) + 1
                )
                continue
            split_parts = _split_long_standalone_block_text(text)
            if len(split_parts) > 1:
                long_split_source_blocks += 1
                long_split_segments_added += len(split_parts) - 1
            for split_text in split_parts:
                standalone_blocks.append((idx, split_text))

        def _analyze_container(
            container_index: int,
            container: Any,
        ) -> tuple[int, list[Any], list[Any], set[int]]:
            if not container.indices:
                return (container_index, [], [], set())
            container_tip_candidates: list[Any] = []
            container_topic_candidates: list[Any] = []
            container_topic_block_indices: set[int] = set()
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

                container_topic_candidates.append(
                    build_topic_candidate(
                        atom.text,
                        provenance=provenance,
                        source_section="standalone_topic",
                        header=container.header,
                        overrides=self._overrides,
                    )
                )
                container_topic_block_indices.add(atom.source_block_index)

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
                container_tip_candidates.extend(atom_tips)
                container_tip_index += len(atom_tips)
            return (
                container_index,
                container_tip_candidates,
                container_topic_candidates,
                container_topic_block_indices,
            )

        containers = list(
            chunk_standalone_blocks(standalone_blocks, overrides=self._overrides)
        )
        total_containers = len(containers)
        topic_block_indices: set[int] = set()
        if total_containers:
            _notify(
                format_task_counter(
                    "Analyzing standalone knowledge blocks...",
                    0,
                    total_containers,
                    noun="task",
                )
            )

        container_results: list[tuple[int, list[Any], list[Any], set[int]]] = []
        workers = min(total_containers, _get_standalone_analysis_workers())
        if workers <= 1:
            for container_index, container in enumerate(containers):
                container_results.append(_analyze_container(container_index, container))
                _notify(
                    format_task_counter(
                        "Analyzing standalone knowledge blocks...",
                        container_index + 1,
                        total_containers,
                        noun="task",
                    )
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_analyze_container, container_index, container): container_index
                    for container_index, container in enumerate(containers)
                }
                completed = 0
                for future in as_completed(futures):
                    container_results.append(future.result())
                    completed += 1
                    _notify(
                        format_task_counter(
                            "Analyzing standalone knowledge blocks...",
                            completed,
                            total_containers,
                            noun="task",
                        )
                    )

        container_results.sort(key=lambda row: row[0])
        for _, container_tips, container_topics, container_topic_indices in container_results:
            tip_candidates.extend(container_tips)
            topic_candidates.extend(container_topics)
            topic_block_indices.update(container_topic_indices)

        self._standalone_filter_diagnostics = {
            "schema_version": "standalone_tip_filtering.v1",
            "candidate_standalone_block_count": candidate_standalone_block_count,
            "analyzed_standalone_block_count": len(standalone_blocks),
            "filtered_block_count": max(
                0, candidate_standalone_block_count - len(standalone_blocks)
            ),
            "filter_reason_counts": dict(sorted(filter_reason_counts.items())),
            "long_split_source_blocks": long_split_source_blocks,
            "long_split_segments_added": long_split_segments_added,
            "topic_block_count": len(topic_block_indices),
            "tip_candidate_count": len(tip_candidates),
            "topic_candidate_count": len(topic_candidates),
        }

        return (
            tip_candidates,
            topic_candidates,
            candidate_standalone_block_count,
            len(topic_block_indices),
        )

    def _extract_docpack(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
        extractor: str | None = None,
    ) -> List[Block]:
        """
        Reads EPUB and converts spine items to a linear list of Blocks.

        Extractors:
        - unstructured: semantic HTML partitioning with diagnostics rows.
        - beautifulsoup: BeautifulSoup tag parser across spine docs.
        - markdown: spine-by-spine HTML->Markdown conversion with markdown diagnostics.
        - markitdown: whole-book EPUB->markdown conversion with markdown-line provenance.
        """
        selected_extractor = normalize_epub_extractor_name(extractor or _get_epub_extractor())
        if selected_extractor == "auto":
            raise ValueError(
                "EPUB extractor 'auto' is no longer supported. "
                "Choose an explicit extractor: unstructured, beautifulsoup, markdown, "
                "or markitdown."
            )
        if selected_extractor not in _EPUB_EXTRACTOR_CHOICES:
            raise ValueError(
                f"Unsupported EPUB extractor: {selected_extractor!r}."
            )

        self._extractor_diagnostics: dict[str, list[dict[str, Any]]] = {
            "beautifulsoup": [],
            "unstructured": [],
            "markdown": [],
        }
        self._extractor_meta: dict[str, dict[str, Any]] = {
            "beautifulsoup": {},
            "unstructured": {},
            "markdown": {},
        }
        self._unstructured_diagnostics: list[dict[str, Any]] = []
        self._unstructured_spine_xhtml: list[dict[str, Any]] = []
        self._unstructured_html_parser_version = _get_unstructured_html_parser_version()
        self._unstructured_skip_headers_footers = _get_unstructured_skip_headers_footers()
        self._unstructured_preprocess_mode = _get_unstructured_preprocess_mode()
        self._markitdown_markdown: str | None = None

        if selected_extractor == "markitdown":
            if start_spine is not None or end_spine is not None:
                raise ValueError(
                    "EPUB extractor 'markitdown' does not support split spine ranges. "
                    "Set --epub-split-workers 1 or choose unstructured/beautifulsoup/markdown."
                )
            blocks = self._extract_docpack_markitdown(path)
        elif epub is not None:
            try:
                blocks = self._extract_docpack_with_ebooklib(
                    path,
                    start_spine=start_spine,
                    end_spine=end_spine,
                    extractor=selected_extractor,
                )
            except Exception as e:
                logger.warning(f"Ebooklib extraction failed for EPUB {path}: {e}")
                blocks = self._extract_docpack_with_zip(
                    path,
                    start_spine=start_spine,
                    end_spine=end_spine,
                    extractor=selected_extractor,
                )
        else:
            blocks = self._extract_docpack_with_zip(
                path,
                start_spine=start_spine,
                end_spine=end_spine,
                extractor=selected_extractor,
            )

        if selected_extractor in {"beautifulsoup", "unstructured", "markdown"}:
            blocks = postprocess_epub_blocks(blocks)

        for block in blocks:
            signals.enrich_block(block, overrides=self._overrides)
        return blocks

    def _extract_docpack_markitdown(self, path: Path) -> List[Block]:
        from cookimport.parsing.markdown_blocks import markdown_to_blocks

        markdown_text = convert_path_to_markdown(path)
        self._markitdown_markdown = markdown_text
        return markdown_to_blocks(
            markdown_text,
            source_path=path,
            extraction_backend="markitdown",
        )

    def _extract_docpack_with_ebooklib(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
        extractor: str = _EPUB_EXTRACTOR_DEFAULT,
    ) -> List[Block]:
        blocks: List[Block] = []
        if epub is None:
            raise RuntimeError("ebooklib is not available")

        backend = self._build_extractor(extractor)

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
            item_path = str(getattr(item, "file_name", "") or "")
            media_type = str(getattr(item, "media_type", "") or "")
            item_properties = tuple(str(value) for value in (getattr(item, "properties", None) or []))
            if self._should_skip_spine_document(
                item_id=item_id,
                spine_path=item_path,
                media_type=media_type,
                properties=item_properties,
            ):
                continue
            content = item.get_content()
            if self._should_skip_spine_document(
                item_id=item_id,
                spine_path=item_path,
                media_type=media_type,
                properties=item_properties,
                content=content,
            ):
                continue

            html_str = content.decode("utf-8", errors="replace")
            extraction = backend.extract_spine_html(
                html_str,
                spine_index=spine_index,
                source_location_id=source_location_id,
            )
            blocks.extend(extraction.blocks)
            self._extractor_diagnostics.setdefault(extractor, []).extend(
                extraction.diagnostics_rows
            )
            self._update_extractor_meta(extractor, extraction.meta)
            if extractor == "unstructured":
                self._unstructured_spine_xhtml.append(
                    {
                        "spine_index": spine_index,
                        "raw_html": extraction.meta.get("raw_html", html_str),
                        "normalized_html": extraction.meta.get("normalized_html", html_str),
                    }
                )
        return blocks

    def _extract_docpack_with_zip(
        self,
        path: Path,
        start_spine: int | None = None,
        end_spine: int | None = None,
        extractor: str = _EPUB_EXTRACTOR_DEFAULT,
    ) -> List[Block]:
        blocks: List[Block] = []
        _title, spine_items = self._read_epub_spine(path)
        if not spine_items:
            raise ValueError("No spine items found in EPUB")

        backend = self._build_extractor(extractor)

        source_location_id = path.stem

        with zipfile.ZipFile(path) as zip_handle:
            for spine_index, spine_item in enumerate(spine_items):
                if start_spine is not None and spine_index < start_spine:
                    continue
                if end_spine is not None and spine_index >= end_spine:
                    continue
                spine_path = spine_item.path
                media_type = spine_item.media_type
                if not spine_path:
                    continue
                if media_type and "html" not in media_type:
                    continue
                try:
                    content = zip_handle.read(spine_path)
                except KeyError:
                    logger.warning(f"Missing spine item in EPUB: {spine_path}")
                    continue
                if self._should_skip_spine_document(
                    item_id=spine_item.item_id,
                    spine_path=spine_path,
                    media_type=media_type,
                    properties=spine_item.properties,
                    content=content,
                ):
                    continue

                html_str = content.decode("utf-8", errors="replace")
                extraction = backend.extract_spine_html(
                    html_str,
                    spine_index=spine_index,
                    source_location_id=source_location_id,
                )
                blocks.extend(extraction.blocks)
                self._extractor_diagnostics.setdefault(extractor, []).extend(
                    extraction.diagnostics_rows
                )
                self._update_extractor_meta(extractor, extraction.meta)
                if extractor == "unstructured":
                    self._unstructured_spine_xhtml.append(
                        {
                            "spine_index": spine_index,
                            "raw_html": extraction.meta.get("raw_html", html_str),
                            "normalized_html": extraction.meta.get("normalized_html", html_str),
                        }
                    )
        return blocks

    def _build_extractor(self, extractor: str) -> EpubExtractor:
        if extractor == "beautifulsoup":
            return BeautifulSoupEpubExtractor()
        if extractor == "unstructured":
            return UnstructuredEpubExtractor(
                html_parser_version=self._unstructured_html_parser_version,
                skip_headers_and_footers=self._unstructured_skip_headers_footers,
                preprocess_mode=self._unstructured_preprocess_mode,
            )
        if extractor == "markdown":
            return MarkdownEpubExtractor()
        raise ValueError(f"Unsupported EPUB extractor backend: {extractor!r}")

    def _update_extractor_meta(self, extractor: str, meta: dict[str, Any]) -> None:
        if not meta:
            return
        current = self._extractor_meta.setdefault(extractor, {})
        for key, value in meta.items():
            if key in {"raw_html", "normalized_html"}:
                continue
            current[key] = value
        if extractor == "unstructured":
            self._unstructured_diagnostics = list(
                self._extractor_diagnostics.get("unstructured", [])
            )

    def _soup_from_bytes(self, content: bytes) -> BeautifulSoup:
        try:
            return BeautifulSoup(content, "lxml")
        except FeatureNotFound:
            return BeautifulSoup(content, "html.parser")

    def _read_epub_spine(self, path: Path) -> tuple[str | None, list[EpubSpineItem]]:
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

    def _extract_spine_items(self, opf_path: str, opf_bytes: bytes) -> list[EpubSpineItem]:
        root = ET.fromstring(opf_bytes)
        manifest: dict[str, tuple[str, str, tuple[str, ...]]] = {}

        for item in root.findall(".//{*}manifest/{*}item"):
            item_id = item.attrib.get("id")
            href = item.attrib.get("href")
            if not item_id or not href:
                continue
            media_type = item.attrib.get("media-type", "")
            properties_raw = item.attrib.get("properties", "")
            properties = tuple(
                token.strip().lower()
                for token in properties_raw.split()
                if token.strip()
            )
            clean_href = href.split("#", 1)[0]
            manifest[item_id] = (clean_href, media_type, properties)

        base_dir = PurePosixPath(opf_path).parent
        spine_items: list[EpubSpineItem] = []
        for itemref in root.findall(".//{*}spine/{*}itemref"):
            idref = itemref.attrib.get("idref")
            if not idref:
                continue
            manifest_entry = manifest.get(idref)
            if not manifest_entry:
                continue
            href, media_type, properties = manifest_entry
            if not href:
                continue
            full_path = str((base_dir / href).as_posix())
            spine_items.append(
                EpubSpineItem(
                    path=full_path,
                    media_type=media_type,
                    item_id=idref,
                    properties=properties,
                )
            )

        return spine_items

    def _should_skip_spine_document(
        self,
        *,
        item_id: str,
        spine_path: str,
        media_type: str,
        properties: tuple[str, ...] | list[str] | None = None,
        content: bytes | None = None,
    ) -> bool:
        media_type_lower = media_type.strip().lower()
        if media_type_lower and "html" not in media_type_lower:
            return True

        properties_set = {
            str(value).strip().lower()
            for value in (properties or ())
            if str(value).strip()
        }
        if "nav" in properties_set:
            return True

        item_id_lower = item_id.strip().lower()
        basename = PurePosixPath(spine_path).name.lower()
        if item_id_lower in {"nav", "toc"}:
            return True
        if basename in {"nav.xhtml", "nav.html", "toc.xhtml", "toc.html", "contents.xhtml"}:
            return True

        if not content:
            return False

        soup = self._soup_from_bytes(content)
        return self._document_has_toc_nav(soup)

    def _document_has_toc_nav(self, soup: BeautifulSoup) -> bool:
        for nav in soup.find_all("nav"):
            if not isinstance(nav, Tag):
                continue
            type_tokens = self._tag_attr_tokens(nav, "epub:type") + self._tag_attr_tokens(nav, "type")
            role_tokens = self._tag_attr_tokens(nav, "role")
            if any(token in {"toc", "doc-toc", "navigation"} for token in type_tokens + role_tokens):
                return True
        return False

    def _tag_attr_tokens(self, tag: Tag, key: str) -> list[str]:
        raw = tag.attrs.get(key)
        if raw is None:
            return []
        if isinstance(raw, (list, tuple)):
            values = raw
        else:
            values = [raw]
        tokens: list[str] = []
        for value in values:
            text = str(value).strip().lower()
            if not text:
                continue
            tokens.extend(part for part in text.split() if part)
        return tokens

    def _is_pagebreak_tag(self, tag: Tag) -> bool:
        type_tokens = self._tag_attr_tokens(tag, "epub:type") + self._tag_attr_tokens(tag, "type")
        role_tokens = self._tag_attr_tokens(tag, "role")
        class_tokens = [token.lower() for token in tag.get("class", [])]
        if any("pagebreak" in token for token in type_tokens):
            return True
        if any("doc-pagebreak" in token for token in role_tokens):
            return True
        if any("pagebreak" in token for token in class_tokens):
            return True
        return False

    def _is_table_cell_tag(self, tag: Tag) -> bool:
        return tag.name in {"td", "th"}

    def _is_block_tag(self, tag: Tag) -> bool:
        return tag.name in {
            "p",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "blockquote",
            "td",
            "th",
            "tr",
        }

    def _has_block_children(self, tag: Tag) -> bool:
        for child in tag.children:
            if isinstance(child, Tag) and self._is_block_tag(child):
                return True
        return False

    def _build_table_row_block(
        self,
        row: Tag,
        *,
        spine_index: int | None,
        extraction_backend: str,
    ) -> Block | None:
        structured_row = structured_epub_row_from_tag(row)
        if structured_row is None:
            return None

        block = build_structured_epub_row_block(
            structured_row,
            structure_source=f"{extraction_backend}_html_tr",
        )
        block.add_feature("extraction_backend", extraction_backend)
        if spine_index is not None:
            block.add_feature("spine_index", spine_index)
        return block

    def _parse_soup_to_blocks(
        self,
        soup: BeautifulSoup,
        spine_index: int | None = None,
        extraction_backend: str = "beautifulsoup",
    ) -> List[Block]:
        blocks: list[Block] = []
        emitted_table_nodes: set[int] = set()

        for row in soup.find_all("tr"):
            if not isinstance(row, Tag):
                continue
            if self._is_pagebreak_tag(row):
                continue
            if row.find_parent("nav"):
                continue
            row_block = self._build_table_row_block(
                row,
                spine_index=spine_index,
                extraction_backend=extraction_backend,
            )
            if row_block is None:
                continue
            blocks.append(row_block)
            emitted_table_nodes.add(id(row))
            for cell in row.find_all(self._is_table_cell_tag):
                emitted_table_nodes.add(id(cell))

        for elem in soup.find_all(self._is_block_tag):
            if not isinstance(elem, Tag):
                continue
            if elem.name == "tr":
                continue
            if id(elem) in emitted_table_nodes:
                continue
            if self._is_pagebreak_tag(elem):
                continue
            nav_parent = elem.find_parent("nav")
            if isinstance(nav_parent, Tag):
                nav_tokens = (
                    self._tag_attr_tokens(nav_parent, "epub:type")
                    + self._tag_attr_tokens(nav_parent, "type")
                    + self._tag_attr_tokens(nav_parent, "role")
                )
                if any(token in {"toc", "doc-toc", "navigation"} for token in nav_tokens):
                    continue
            if self._has_block_children(elem):
                continue

            text = cleaning.normalize_epub_text(elem.get_text("\n"))
            if not text:
                continue

            block_type = BlockType.TABLE if elem.name in {"td", "th"} else BlockType.TEXT
            block = Block(
                text=text,
                type=block_type,
                html=str(elem),
                font_weight=(
                    "bold"
                    if elem.name.startswith("h") or elem.find("strong") or elem.find("b")
                    else "normal"
                ),
            )
            block.add_feature("extraction_backend", extraction_backend)
            if spine_index is not None:
                block.add_feature("spine_index", spine_index)
            if elem.name.startswith("h"):
                block.add_feature("is_heading", True)
                block.add_feature("heading_level", int(elem.name[1]))
            if elem.name == "li":
                block.add_feature("is_list_item", True)
            if elem.name in {"td", "th"}:
                block.add_feature("epub_table_cell", True)

            blocks.append(block)

        return blocks

    def _detect_candidates(self, blocks: List[Block]) -> List[Tuple[int, int, float]]:
        """
        Segments blocks into recipes. Returns (start_idx, end_idx, score).
        """
        if not blocks:
            return []

        yield_indices = [
            i
            for i, b in enumerate(blocks)
            if b.features.get("is_yield")
            and not b.features.get("exclude_from_candidate_detection")
        ]
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
            if block.features.get("exclude_from_candidate_detection"):
                i += 1
                continue
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

    def _resolve_multi_recipe_splitter_backend(
        self,
        run_settings: RunSettings | None,
    ) -> str:
        raw_backend = getattr(
            getattr(run_settings, "multi_recipe_splitter", None),
            "value",
            None,
        )
        if raw_backend is None and run_settings is not None:
            raw_backend = getattr(run_settings, "multi_recipe_splitter", None)
        normalized = str(raw_backend or "rules_v1").strip().lower().replace("-", "_")
        if normalized in {"off", "rules_v1"}:
            return normalized
        return "rules_v1"

    def _build_multi_recipe_split_config(
        self,
        run_settings: RunSettings | None,
        *,
        backend: str,
    ) -> MultiRecipeSplitConfig:
        min_ingredient_lines = getattr(
            run_settings, "multi_recipe_min_ingredient_lines", 1
        )
        min_instruction_lines = getattr(
            run_settings, "multi_recipe_min_instruction_lines", 1
        )
        for_the_guardrail = getattr(
            run_settings, "multi_recipe_for_the_guardrail", True
        )
        trace = getattr(run_settings, "multi_recipe_trace", False)
        return MultiRecipeSplitConfig(
            backend=backend,
            min_ingredient_lines=max(0, int(min_ingredient_lines or 0)),
            min_instruction_lines=max(0, int(min_instruction_lines or 0)),
            enable_for_the_guardrail=bool(for_the_guardrail),
            trace=bool(trace),
        )

    def _apply_multi_recipe_splitter(
        self,
        blocks: List[Block],
        candidates: List[Tuple[int, int, float]],
        *,
        run_settings: RunSettings | None,
    ) -> tuple[
        list[tuple[int, int, float]],
        list[dict[str, Any] | None],
        dict[str, Any] | None,
    ]:
        backend = self._resolve_multi_recipe_splitter_backend(run_settings)
        passthrough_meta: list[dict[str, Any] | None] = [None] * len(candidates)
        if backend == "off":
            return list(candidates), passthrough_meta, None

        config = self._build_multi_recipe_split_config(run_settings, backend=backend)
        rewritten: list[tuple[int, int, float]] = []
        rewritten_meta: list[dict[str, Any] | None] = []
        trace_candidates: list[dict[str, Any]] = []

        for parent_index, (start, end, score) in enumerate(candidates):
            if end <= start:
                continue
            split_result = split_candidate_blocks(
                blocks[start:end],
                config=config,
                overrides=self._overrides,
            )
            spans = [span for span in split_result.spans if span.end > span.start]
            if len(spans) <= 1:
                rewritten.append((start, end, score))
                rewritten_meta.append(None)
            else:
                split_count = len(spans)
                for split_index, span in enumerate(spans):
                    rewritten.append((start + span.start, start + span.end, score))
                    rewritten_meta.append(
                        {
                            "backend": backend,
                            "split_parent": f"c{parent_index}",
                            "split_index": split_index,
                            "split_count": split_count,
                            "split_reason": list(span.reasons),
                        }
                    )
            if split_result.trace is not None:
                trace_candidates.append(
                    {
                        "parent_index": parent_index,
                        "parent_start": start,
                        "parent_end": end,
                        "parent_score": score,
                        "split_count": len(spans),
                        "trace": split_result.trace,
                    }
                )

        trace_payload: dict[str, Any] | None = None
        if trace_candidates:
            trace_payload = {
                "backend": backend,
                "candidate_count_before": len(candidates),
                "candidate_count_after": len(rewritten),
                "candidates": trace_candidates,
            }
        return rewritten, rewritten_meta, trace_payload

    def _backtrack_for_title(self, blocks: List[Block], anchor_idx: int, limit: int = 20) -> int:
        """
        Look backwards from an anchor to find a likely title.
        """
        best_idx = -1
        min_idx = max(-1, anchor_idx - limit)
        for i in range(anchor_idx - 1, min_idx, -1):
            b = blocks[i]
            if b.features.get("exclude_from_candidate_detection"):
                break
            if b.features.get("is_ingredient_header"):
                break
            if b.features.get("is_yield") or b.features.get("is_time"):
                continue
            if self._is_title_candidate(b):
                start_idx = i
                j = i - 1
                while j > min_idx:
                    prev = blocks[j]
                    if prev.features.get("exclude_from_candidate_detection"):
                        break
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
            if b.features.get("exclude_from_candidate_detection"):
                return i
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
        if self._section_detector_backend == "shared_v1":
            return self._extract_fields_shared_v1(blocks)

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

    def _extract_fields_shared_v1(self, blocks: List[Block]) -> RecipeCandidate:
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
        detected = detect_sections_from_blocks(
            content_blocks,
            overrides=self._overrides,
        )

        span_by_line_index: dict[int, Any] = {}
        span_by_header_index: dict[int, Any] = {}
        for span in detected.spans:
            if span.header_index is not None and span.header_index not in span_by_header_index:
                span_by_header_index[span.header_index] = span
            if span.end_index <= span.start_index:
                continue
            for line_index in range(span.start_index, span.end_index):
                span_by_line_index[line_index] = span

        for index, block in enumerate(content_blocks):
            text = block.text.strip()
            if not text:
                continue
            if block.features.get("is_yield") and recipe_yield is None:
                recipe_yield = self._yield_phrase(text)
                continue

            header_span = span_by_header_index.get(index)
            if header_span is not None:
                if header_span.kind == SectionKind.INGREDIENTS and header_span.key != "main":
                    ingredients.append(header_span.name)
                elif (
                    header_span.kind == SectionKind.INSTRUCTIONS
                    and header_span.key != "main"
                ):
                    instructions.append(header_span.name)
                elif header_span.kind == SectionKind.NOTES and header_span.key != "main":
                    description.append(header_span.name)
                continue

            span = span_by_line_index.get(index)
            kind = span.kind if span is not None else SectionKind.OTHER
            if kind == SectionKind.INGREDIENTS:
                clean = re.sub(r"^\s*[-*•]\s*", "", text)
                if clean:
                    ingredients.append(clean)
            elif kind == SectionKind.INSTRUCTIONS:
                clean = re.sub(r"^\s*(?:\d+[.)]|\*|-)\s*", "", text)
                if clean:
                    instructions.append(clean)
            else:
                description.append(text)

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
        if self._looks_like_singleton_ingredient_line(text):
            return False
        if block.features.get("is_heading"):
            return True
        if block.font_weight == "bold" and len(text) <= 60:
            return True
        if text.isupper() or text.istitle():
            return True
        return False

    def _looks_like_singleton_ingredient_line(self, text: str) -> bool:
        normalized = re.sub(r"[^a-z\s]", " ", text.lower())
        words = [word for word in normalized.split() if word]
        if not words or len(words) > 2:
            return False
        return all(word in _SINGLETON_INGREDIENT_WORDS for word in words)

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
