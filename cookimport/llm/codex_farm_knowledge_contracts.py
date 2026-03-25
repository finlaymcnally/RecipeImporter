from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

_PACKET_VERSION_V1: Literal["1"] = "1"


class SpanV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int
    end: int

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_int(cls, value: Any) -> Any:
        if value is None:
            return value
        return int(value)


class KnowledgeTableHintV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table_id: str
    caption: str | None = None
    markdown: str | None = None
    row_index_in_table: int | None = None


class KnowledgeCompactTableHintV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    table_id: str = Field(alias="id")
    caption: str | None = Field(default=None, alias="c")
    row_index_in_table: int | None = Field(default=None, alias="r")


class KnowledgePacketBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    block_index: int = Field(alias="i")
    text: str = Field(alias="t")
    heading_level: int | None = Field(default=None, alias="hl")
    table_hint: KnowledgeCompactTableHintV1 | None = Field(default=None, alias="th")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgePacketContextBlockV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    block_index: int = Field(alias="i")
    text: str = Field(alias="t")
    heading_level: int | None = Field(default=None, alias="hl")

    @field_validator("block_index", mode="before")
    @classmethod
    def _coerce_block_index(cls, value: Any) -> Any:
        return int(value)


class KnowledgePacketContextPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    blocks_before: list[KnowledgePacketContextBlockV1] = Field(default_factory=list, alias="p")
    blocks_after: list[KnowledgePacketContextBlockV1] = Field(default_factory=list, alias="n")


class KnowledgePacketGuardrailsPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    context_recipe_block_indices: list[int] = Field(default_factory=list, alias="r")

    @field_validator("context_recipe_block_indices", mode="before")
    @classmethod
    def _coerce_context_recipe_block_indices(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        return value


class KnowledgePacketJobInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    packet_version: Literal["1"] = Field(default=_PACKET_VERSION_V1, alias="v")
    packet_id: str = Field(alias="bid")
    blocks: list[KnowledgePacketBlockV1] = Field(default_factory=list, alias="b")
    context: KnowledgePacketContextPayloadV1 | None = Field(default=None, alias="x")
    guardrails: KnowledgePacketGuardrailsPayloadV1 | None = Field(default=None, alias="g")


class KnowledgeShardJobInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    shard_version: Literal["1"] = Field(default=_PACKET_VERSION_V1, alias="v")
    shard_id: str = Field(alias="sid")
    packets: list[KnowledgePacketJobInputV1] = Field(default_factory=list, alias="p")


def knowledge_input_bundle_id(payload: Mapping[str, Any] | None) -> str:
    data = payload or {}
    return str(
        data.get("sid")
        or data.get("shard_id")
        or data.get("bid")
        or data.get("packet_id")
        or ""
    ).strip()


def knowledge_input_packets(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    data = payload or {}
    packets = data.get("p")
    if not isinstance(packets, list):
        packets = data.get("packets")
    if isinstance(packets, list):
        return [dict(item) for item in packets if isinstance(item, dict)]
    blocks = data.get("b")
    if not isinstance(blocks, list):
        blocks = data.get("blocks")
    if not isinstance(blocks, list):
        return []
    packet_id = str(data.get("bid") or data.get("packet_id") or "").strip()
    if not packet_id:
        return []
    packet_payload: dict[str, Any] = {
        "bid": packet_id,
        "b": [dict(item) for item in blocks if isinstance(item, dict)],
    }
    if isinstance(data.get("x"), Mapping):
        packet_payload["x"] = dict(data["x"])
    if isinstance(data.get("g"), Mapping):
        packet_payload["g"] = dict(data["g"])
    if data.get("v") is not None:
        packet_payload["v"] = data.get("v")
    return [packet_payload]


def knowledge_input_blocks(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    packets = knowledge_input_packets(payload)
    if len(packets) == 1:
        blocks = packets[0].get("b")
        if isinstance(blocks, list):
            return [dict(item) for item in blocks if isinstance(item, dict)]
    return [
        dict(block)
        for packet in packets
        for block in (packet.get("b") or [])
        if isinstance(block, dict)
    ]


def knowledge_input_packet_ids(payload: Mapping[str, Any] | None) -> list[str]:
    packet_ids = [
        str(packet.get("bid") or packet.get("packet_id") or "").strip()
        for packet in knowledge_input_packets(payload)
        if str(packet.get("bid") or packet.get("packet_id") or "").strip()
    ]
    if packet_ids:
        return packet_ids
    bundle_id = knowledge_input_bundle_id(payload)
    blocks = knowledge_input_blocks(payload)
    if not bundle_id or not blocks:
        return []
    return [bundle_id]


def knowledge_input_block_index(block_payload: Mapping[str, Any] | None) -> int | None:
    data = block_payload or {}
    value = data.get("i", data.get("block_index"))
    if value is None:
        return None
    return int(value)


def knowledge_input_block_text(block_payload: Mapping[str, Any] | None) -> str:
    data = block_payload or {}
    return str(data.get("t", data.get("text")) or "")
