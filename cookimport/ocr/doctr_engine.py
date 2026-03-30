"""DocTR-based OCR engine for scanned PDF processing.

This module provides OCR capabilities using the docTR library for extracting
text with bounding boxes from scanned PDFs.
"""

from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doctr.models import OCRPredictor

logger = logging.getLogger(__name__)

_CACHE_FALLBACK = Path("/tmp/cookimport-cache")

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


# Lazy-loaded model singleton
_model: "OCRPredictor | None" = None
_current_device: str | None = None


def _suppress_doctr_import_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r"defusedxml\.cElementTree is deprecated, import from defusedxml\.ElementTree instead\.",
        category=DeprecationWarning,
    )


def resolve_ocr_device(device: str = "auto") -> str:
    """Resolve 'auto' or validate explicit device selection."""
    import torch
    if device == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
        return "cpu"
    
    if device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but not available.")
    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS requested but not available.")
    if device not in ("cpu", "cuda", "mps"):
        raise ValueError(f"Unsupported OCR device: {device}. Use auto, cpu, cuda, or mps.")
    
    return device


def warm_ocr_model(device: str = "auto") -> None:
    """Proactively load the OCR model into memory."""
    _get_model(device=device)


def _get_model(device: str = "auto") -> "OCRPredictor":
    """Lazy-load the docTR model on first use for a given device."""
    global _model, _current_device

    _configure_cache_dirs()
    _configure_doctr_multiprocessing()
    
    resolved_device = resolve_ocr_device(device)
    
    if _model is None or _current_device != resolved_device:
        logger.info(f"Loading docTR OCR model on {resolved_device}...")
        try:
            with warnings.catch_warnings():
                _suppress_doctr_import_warnings()
                from doctr.models import ocr_predictor

            _model = ocr_predictor(
                det_arch="db_resnet50",
                reco_arch="crnn_vgg16_bn",
                pretrained=True
            )
            if resolved_device != "cpu":
                _model = _model.to(resolved_device)
            
            _current_device = resolved_device
            logger.info(f"docTR model loaded successfully on {resolved_device}")
        except ImportError as e:
            logger.error(f"Failed to import docTR: {e}")
            raise ImportError(
                "docTR is required for OCR. Install with: pip install python-doctr[torch]"
            ) from e
        except Exception as e:
            logger.error(f"Failed to load docTR model on {resolved_device}: {e}")
            raise
    return _model


def _configure_cache_dirs() -> None:
    cache_root = _resolve_cache_root()
    if not _ensure_writable_dir(cache_root):
        cache_root = _CACHE_FALLBACK
        _ensure_writable_dir(cache_root)

    _set_cache_env("XDG_CACHE_HOME", cache_root)
    _set_cache_env("TORCH_HOME", cache_root / "torch")
    _set_cache_env("HF_HOME", cache_root / "huggingface")
    _set_cache_env("DOCTR_CACHE_DIR", cache_root / "doctr")


def _configure_doctr_multiprocessing() -> None:
    if os.environ.get("DOCTR_MULTIPROCESSING_DISABLE"):
        return
    try:
        import multiprocessing as mp

        lock = mp.Lock()
        lock.acquire()
        lock.release()
    except PermissionError:
        os.environ["DOCTR_MULTIPROCESSING_DISABLE"] = "TRUE"
        return
    except Exception:
        return
    shm_path = Path("/dev/shm")
    if not shm_path.exists() or not os.access(shm_path, os.W_OK):
        os.environ["DOCTR_MULTIPROCESSING_DISABLE"] = "TRUE"


def _resolve_cache_root() -> Path:
    explicit = os.getenv("COOKIMPORT_CACHE_DIR")
    if explicit:
        return Path(explicit)
    xdg = os.getenv("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".cache"


def _set_cache_env(key: str, path: Path) -> None:
    existing = os.getenv(key)
    if existing:
        if _ensure_writable_dir(Path(existing)):
            return
    os.environ[key] = str(path)
    _ensure_writable_dir(path)


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


def ocr_pdf(
    path: Path,
    device: str = "auto",
    batch_size: int = 1,
    start_page: int = 0,
    end_page: int | None = None,
) -> list[OcrPage]:
    """Run OCR on a PDF file, returning text with bounding boxes.

    Args:
        path: Path to the PDF file to process.
        device: Device to use for OCR ('auto', 'cpu', 'cuda', 'mps').
        batch_size: Number of pages to process per model call.
        start_page: Index of the first page to process (0-based).
        end_page: Index of the last page to process (exclusive). If None, process to end.

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

    logger.info(
        f"Starting OCR on {path} (pages {start_page}-{end_page or 'end'}) "
        f"using {device} (batch_size={batch_size})"
    )

    try:
        with warnings.catch_warnings():
            _suppress_doctr_import_warnings()
            from doctr.io import DocumentFile
        import numpy as np
    except ImportError as e:
        raise ImportError(
            "docTR is required for OCR. Install with: pip install python-doctr[torch]"
        ) from e

    model = _get_model(device=device)

    # Load content
    # If a specific range is requested, use fitz to render only those pages to save memory
    doc_images = []
    
    try:
        import fitz
        with fitz.open(path) as pdf:
            total_pages = len(pdf)
            actual_end = end_page if end_page is not None else total_pages
            actual_end = min(actual_end, total_pages)
            
            if start_page >= actual_end:
                return []

            # Efficiently render just the requested pages
            for i in range(start_page, actual_end):
                page = pdf[i]
                # Render at 300 DPI for OCR quality
                pix = page.get_pixmap(dpi=300)
                # Convert to numpy (Height, Width, Channels)
                # Note: pix.samples is a bytes object
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    (pix.h, pix.w, pix.n)
                )
                # Ensure RGB
                if pix.n == 4:  # RGBA
                    img = img[..., :3]
                elif pix.n == 1:  # Gray
                    img = np.stack([img.squeeze()] * 3, axis=-1)
                
                doc_images.append(img)
                
    except ImportError:
        # Fallback if fitz not available (though it is a project dep)
        logger.warning("PyMuPDF (fitz) not found, falling back to full load for OCR.")
        try:
            full_doc = DocumentFile.from_pdf(str(path))
            actual_end = end_page if end_page is not None else len(full_doc)
            doc_images = full_doc[start_page:actual_end]
        except Exception as e:
            raise ValueError(f"Failed to load PDF for OCR: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to extract pages for OCR: {e}") from e

    # Run OCR in batches
    result_pages = []
    for i in range(0, len(doc_images), batch_size):
        batch = doc_images[i : i + batch_size]
        batch_res = model(batch)
        result_pages.extend(batch_res.pages)

    # Convert to our data structures
    pages: list[OcrPage] = []

    for idx, page in enumerate(result_pages):
        # Calculate actual page number (1-based) including offset
        current_page_num = start_page + idx + 1
        
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
                page_num=current_page_num,
                lines=ocr_lines,
                width=page_width,
                height=page_height,
            )
        )

    logger.info(f"OCR complete: {len(pages)} pages processed.")
    return pages


def ocr_available() -> bool:
    """Check if docTR is available for OCR."""
    try:
        with warnings.catch_warnings():
            _suppress_doctr_import_warnings()
            import doctr  # noqa: F401

        return True
    except ImportError:
        return False
