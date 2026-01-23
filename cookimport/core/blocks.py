from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

class BlockType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    UNKNOWN = "unknown"

class Block(BaseModel):
    """A shared intermediate representation for document content."""
    
    text: str
    type: BlockType = BlockType.TEXT
    
    # Layout info
    page: Optional[int] = None
    bbox: Optional[List[float]] = None # [x0, y0, x1, y1]
    indent_level: int = 0
    
    # Style info
    font_size: Optional[float] = None
    font_weight: Optional[str] = None # "bold", "normal"
    alignment: Optional[str] = None # "left", "center", "right"
    
    # Feature vector (populated by signals)
    features: Dict[str, Any] = Field(default_factory=dict)
    
    def add_feature(self, key: str, value: Any):
        self.features[key] = value

    class Config:
        use_enum_values = True
