# Resource Usage and Performance Report: cookimport

This report provides an analysis of how `cookimport` utilizes system resources and outlines strategies for increasing its share of available compute to accelerate processing.

## 1. Current Resource Usage Profile

### CPU (Central Processing Unit)
*   **Status**: Underutilized (Single-threaded).
*   **Behavior**: The program currently processes files sequentially in a single loop within `cookimport/cli.py`. This means only one CPU core is primarily active at any given time.
*   **Load Type**: High-intensity "burst" loads occur during text extraction (OCR) and NLP parsing (ingredient/instruction analysis). The CPU is responsible for coordinating model execution and managing data structures.

### RAM (Random Access Memory)
*   **Status**: Moderate to High.
*   **Behavior**: Loading deep learning models for OCR (`docTR`) and NLP (`spacy`, `ingredient-parser-nlp`) requires significant memory overhead (typically 1GB–4GB+ depending on the models).
*   **Peak Load**: Memory usage peaks when large PDF files are converted to images for OCR processing.

### GPU (Graphics Processing Unit)
*   **Status**: Potentially utilized but unmanaged.
*   **Behavior**: `docTR` uses PyTorch as a backend. If a CUDA-enabled (NVIDIA) or MPS-enabled (Apple Silicon) GPU is present, PyTorch may use it for OCR detection and recognition, but the codebase does not explicitly configure or optimize this device allocation.

### Disk I/O
*   **Status**: Low.
*   **Behavior**: Reading source files (PDF, EPUB, Excel) and writing JSON-LD drafts is generally fast and not a bottleneck compared to the compute-heavy parsing stages.

---

## 2. Strategies for Increasing Compute Share

To allow `cookimport` to process recipes significantly faster, the following architectural changes are recommended:

### A. Parallel File Processing (Multiprocessing)
The most effective way to utilize a modern multi-core CPU is to process multiple files simultaneously.
*   **Implementation**: Replace the sequential `for` loop in `cookimport/cli.py:stage()` with a `concurrent.futures.ProcessPoolExecutor`.
*   **Benefit**: On an 8-core machine, processing 4–8 files in parallel could theoretically result in a 3x–6x speedup for bulk imports.
*   **Note**: This will multiply RAM usage, so the number of workers should be tuned to the available memory.

### B. Explicit GPU Acceleration
Explicitly directing the OCR engine to use the GPU will offload the heaviest computations from the CPU.
*   **Implementation**: Modify `cookimport/ocr/doctr_engine.py` to detect and pass the `device` (e.g., `cuda` or `mps`) to the `ocr_predictor`.
*   **Benefit**: GPU-accelerated OCR is often 10x–50x faster than CPU-based OCR.

### C. Batch OCR Processing
`docTR` is designed to handle batches of images efficiently.
*   **Implementation**: Instead of processing one page at a time, group pages into batches (e.g., 8 pages) and pass them to the model in a single call.
*   **Benefit**: Reduces the overhead of transferring data between the CPU and GPU/RAM.

### D. Model Warming and Caching
Currently, models are lazy-loaded on the first call.
*   **Implementation**: For high-performance runs, "warm" the models by loading them during application startup or keeping them resident in a separate worker process.
*   **Benefit**: Eliminates the 5–10 second delay encountered the first time a file is processed in a session.

---

## 3. Recommended Configuration for High-Performance Hardware
If you have a high-end workstation, the ideal configuration for this tool would be:
1.  **Workers**: Set a concurrency limit equal to `Total RAM / 3GB`.
2.  **Backend**: Ensure `torch` is installed with proper hardware acceleration support (CUDA for PC, MPS for Mac).
3.  **IO**: Run from an SSD to minimize latency when reading large PDF/EPUB sources.
