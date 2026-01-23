from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from cookimport.core.models import RecipeCandidate
from cookimport.llm.client import LLMClient
from cookimport.llm.prompts import REPAIR_TEMPLATE, SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# Global client instance (lazy init could be better but this is simple)
_CLIENT = LLMClient()

def repair_candidate(text_block: str, hints: Optional[Dict[str, Any]] = None) -> Optional[RecipeCandidate]:
    """
    Uses an LLM to extract a structured RecipeCandidate from a text block.
    """
    if hints is None:
        hints = {}

    # Get the JSON schema from the Pydantic model
    schema = RecipeCandidate.model_json_schema()
    
    # Construct the prompt
    prompt = REPAIR_TEMPLATE.format(
        text_block=text_block,
        hints=json.dumps(hints, indent=2),
        schema=json.dumps(schema, indent=2)
    )

    try:
        response_text = _CLIENT.complete(prompt=prompt, system_prompt=SYSTEM_PROMPT)
        
        # Clean potential markdown code blocks if the prompt instruction wasn't followed
        cleaned_response = response_text.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        
        data = json.loads(cleaned_response)
        
        # Validate against the model
        candidate = RecipeCandidate.model_validate(data)
        
        # Mark provenance
        candidate.provenance["extraction_method"] = "llm_repair"
        
        return candidate

    except json.JSONDecodeError:
        logger.error("LLM returned invalid JSON.")
        return None
    except Exception as e:
        logger.error(f"LLM repair failed: {e}")
        return None

def structure_repair(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Legacy/Wrapper: Calls repair_candidate with text from payload.
    """
    text = payload.get("text") or str(payload)
    candidate = repair_candidate(text)
    if candidate:
        return candidate.model_dump(by_alias=True)
    return None