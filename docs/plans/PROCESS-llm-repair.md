---
summary: "ExecPlan for the shared LLM escalation and repair strategy."
read_when:
  - When implementing LLM-based fallback or repair logic for any importer
---

# LLM Escalation and Repair ExecPlan

This ExecPlan defines how and when to use Large Language Models (LLMs) within the import pipeline. The strategy is "Deterministic First, LLM Surgical," meaning we only pay for intelligence when heuristics fail.

## Purpose / Big Picture

To handle ambiguous, messy, or unstructured data that simpler code cannot parse, without blowing the budget or slowing down the pipeline. This module provides a standard interface for "ask an LLM to fix this specific thing" that all importers can use.

## Core Principles

1.  **Surgical Use:** Do not feed the whole book to the LLM. Feed only the specific candidate or text block that is ambiguous.
2.  **Schema-Constrained:** Never ask for "free text". Always ask for JSON that matches a Pydantic model.
3.  **Repair, Don't Create:** The LLM's job is to structure existing text, not hallucinate new recipes. Provide the raw text and ask for structure.
4.  **Idempotence:** Cache every LLM response (keyed by model + prompt hash + input hash) to allow cheap re-runs.

## Core Modules

### 1. The Repair Interface (`cookimport.llm.repair`)

**Goal:** A high-level function that importers call when they are stuck.

*   `repair_candidate(text_block: str, hints: dict) -> RecipeCandidate`
    *   Takes raw text (e.g., a messy OCR page).
    *   Takes hints (e.g., "This likely contains 2 recipes" or "Title is missing").
    *   Returns a structured `RecipeCandidate` (or list of them).
*   `segment_text(text: str) -> List[Section]`
    *   Takes a stream of text.
    *   Returns start/end indices for "Ingredients", "Instructions", "Headnote".

### 2. Prompt Engineering & Templates (`cookimport.llm.prompts`)

**Goal:** Centralized, versioned prompts.

*   **Structure:**
    *   `system`: "You are a data extraction assistant. You output strict JSON..."
    *   `context`: "Here is a text block from a cookbook..."
    *   `task`: "Extract the ingredients and instructions. Identify the title."
    *   `schema`: (Auto-generated from Pydantic models).
*   **Templates:**
    *   `REPAIR_RECIPE_STRUCTURE`: For when ingredients/steps are mashed together.
    *   `EXTRACT_METADATA`: For parsing complex "Yield: 2 (10-inch) pies" strings.
    *   `SPLIT_MULTIPLE_RECIPES`: For when a single text block contains multiple distinct recipes.

### 3. Provider & Caching Layer (`cookimport.llm.client`)

**Goal:** Manage API calls, costs, and caching.

*   **Provider Abstraction:** Support OpenAI, Gemini, Anthropic via a common interface (or use `litellm`/`langchain`).
*   **Caching:**
    *   Check SQLite/File cache before making a call.
    *   Key: `hash(prompt_template + input_text + model_name)`.
*   **Cost Tracking:** Log token usage per file/import to the run report.

## Integration Point

*   **Importers:** call `repair_candidate` only when:
    *   Confidence score is low.
    *   Heuristics fail to find required fields (e.g., no ingredients found).
    *   Structure is confusing (interleaved columns).
*   **Configuration:** Users can set a global `--use-llm=true/false` or `--llm-budget=low/high`.

## Context from "Thoughts"

*   "LLM escalation scaffolding is repeated in all three."
*   "Treat 'confidence + reasons' as a first-class output."
*   "Deterministic first, 'AI' only when you must."
