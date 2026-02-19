from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EpubSpineItemReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    idref: str | None = None
    href: str | None = None
    media_type: str | None = None
    linear: bool | None = None
    doc_title: str | None = None
    text_chars: int = 0
    word_count: int = 0
    top_tags: dict[str, int] = Field(default_factory=dict)
    class_keyword_hits: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EpubInspectReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    file_size_bytes: int
    sha256: str
    inspector_backend: str = "zip"
    container_rootfile_path: str | None = None
    package_path: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    spine: list[EpubSpineItemReport] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str


class CandidateDebug(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    start_block: int
    end_block: int
    score: float
    title_guess: str | None = None
    anchors: dict[str, bool] = Field(default_factory=dict)
    start_context: list[str] = Field(default_factory=list)
    end_context: list[str] = Field(default_factory=list)


class EpubCandidateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extractor: str
    block_count: int
    candidates: list[CandidateDebug] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: str
    options: dict[str, Any] = Field(default_factory=dict)
