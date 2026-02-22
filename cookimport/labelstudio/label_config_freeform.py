"""Label Studio config for freeform text-span annotation."""

FREEFORM_TEXT_NAME = "segment_text"
FREEFORM_LABEL_CONTROL_NAME = "span_labels"
FREEFORM_LABEL_RESULT_TYPE = "labels"
FREEFORM_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "TIP",
    "NOTES",
    "VARIANT",
    "YIELD_LINE",
    "TIME_LINE",
    "OTHER",
)
FREEFORM_ALLOWED_LABELS = frozenset(FREEFORM_LABELS)
FREEFORM_LABEL_ALIASES: dict[str, str] = {
    "TIME": "TIME_LINE",
    "YIELD": "YIELD_LINE",
    "NOTE": "NOTES",
    "KNOWLEDGE": "TIP",
    "NARRATIVE": "OTHER",
}


def normalize_freeform_label(raw: str) -> str:
    """Normalize user/LLM freeform labels to canonical Label Studio values."""
    normalized = raw.strip().upper().replace("-", "_").replace(" ", "_")
    normalized = FREEFORM_LABEL_ALIASES.get(normalized, normalized)
    return normalized


def build_freeform_label_config() -> str:
    """Return Label Studio XML config for freeform span highlighting."""
    labels_xml = "\n".join(f'    <Label value="{label}"/>' for label in FREEFORM_LABELS)
    return f"""
<View>
  <Header value="Cookbook Freeform Span Labeling"/>
  <Header value="Highlight any span and apply one label."/>
  <Text
    name="{FREEFORM_TEXT_NAME}"
    value="${FREEFORM_TEXT_NAME}"
    style="white-space: pre-wrap;"
  />
  <Labels name="{FREEFORM_LABEL_CONTROL_NAME}" toName="{FREEFORM_TEXT_NAME}">
{labels_xml}
  </Labels>
</View>
""".strip()
