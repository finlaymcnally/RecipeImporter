"""DocTR-based OCR engine for scanned PDF processing.

This module provides OCR capabilities using the docTR library for extracting
text with bounding boxes from scanned PDFs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doctr.models import OCRPredictor

logger = logging.getLogger(__name__)

# Lazy-loaded model singleton
_model: "OCRPredictor | None" = None


@dataclass
class OcrLine:
    """A line of OCR'd text with position and confidence."""

    text: str
    confidence: float
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 (relative 0-1)


@dataclass
class OcrPage:
    """OCR results for a single page."""

    page_num: int
    lines: list[OcrLine] = field(default_factory=list)
    width: int | None = None
    height: int | None = None


def _get_model() -> "OCRPredictor":
    """Lazy-load the docTR model on first use."""
    global _model
    if _model is None:
        logger.info("Loading docTR OCR model (first use)...")
        try:
            from doctr.models import ocr_predictor

            _model = ocr_predictor(
                det_arch="db_resnet50",
                reco_arch="crnn_vgg16_bn",
                pretrained=True,
            )
            logger.info("docTR model loaded successfully")
        except ImportError as e:
            logger.error(f"Failed to import docTR: {e}")
            raise ImportError(
                "docTR is required for OCR. Install with: pip install python-doctr[torch]"
            ) from e
    return _model


def ocr_pdf(path: Path) -> list[OcrPage]:
    """Run OCR on a PDF file, returning text with bounding boxes.

    Args:
        path: Path to the PDF file to process.

    Returns:
        List of OcrPage objects, one per page, containing recognized text lines
        with confidence scores and bounding boxes in relative coordinates (0-1).

    Raises:
        ImportError: If docTR is not installed.
        FileNotFoundError: If the PDF file doesn't exist.
        ValueError: If the file is not a valid PDF.
    """
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")

    logger.info(f"Starting OCR on {path}")

    try:
        from doctr.io import DocumentFile
    except ImportError as e:
        raise ImportError(
            "docTR is required for OCR. Install with: pip install python-doctr[torch]"
        ) from e

    model = _get_model()

    # Load PDF as images
    try:
        doc = DocumentFile.from_pdf(str(path))
    except Exception as e:
        raise ValueError(f"Failed to load PDF for OCR: {e}") from e

    # Run OCR
    result = model(doc)

    # Convert to our data structures
    pages: list[OcrPage] = []

    for page_idx, page in enumerate(result.pages):
        ocr_lines: list[OcrLine] = []

        for block in page.blocks:
            for line in block.lines:
                # Combine words in the line
                line_text = " ".join(word.value for word in line.words)
                if not line_text.strip():
                    continue

                # Average confidence across words
                word_confidences = [word.confidence for word in line.words]
                avg_confidence = (
                    sum(word_confidences) / len(word_confidences)
                    if word_confidences
                    else 0.0
                )

                # Get line bounding box (relative coordinates 0-1)
                # docTR provides geometry as ((x_min, y_min), (x_max, y_max))
                geom = line.geometry
                bbox = (geom[0][0], geom[0][1], geom[1][0], geom[1][1])

                ocr_lines.append(
                    OcrLine(
                        text=line_text.strip(),
                        confidence=avg_confidence,
                        bbox=bbox,
                    )
                )

        # Sort lines by vertical position (top to bottom), then horizontal (left to right)
        ocr_lines.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))

        # docTR page.dimensions is a tuple (height, width)
        page_height = None
        page_width = None
        if hasattr(page, "dimensions") and page.dimensions:
            dims = page.dimensions
            if isinstance(dims, tuple) and len(dims) >= 2:
                page_height, page_width = dims[0], dims[1]
            elif isinstance(dims, dict):
                page_height = dims.get("height")
                page_width = dims.get("width")

        pages.append(
            OcrPage(
                page_num=page_idx + 1,  # 1-indexed to match PyMuPDF convention
                lines=ocr_lines,
                width=page_width,
                height=page_height,
            )
        )

    logger.info(f"OCR complete: {len(pages)} pages, {sum(len(p.lines) for p in pages)} lines")
    return pages


def ocr_available() -> bool:
    """Check if docTR is available for OCR."""
    try:
        import doctr  # noqa: F401

        return True
    except ImportError:
        return False
