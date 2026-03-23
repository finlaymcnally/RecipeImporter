"""Label Studio config for freeform text-span annotation."""

FREEFORM_TEXT_NAME = "segment_text"
FREEFORM_LABEL_CONTROL_NAME = "span_labels"
FREEFORM_LABEL_RESULT_TYPE = "labels"
FREEFORM_LABELS: tuple[str, ...] = (
    "RECIPE_TITLE",
    "INGREDIENT_LINE",
    "INSTRUCTION_LINE",
    "HOWTO_SECTION",
    "YIELD_LINE",
    "TIME_LINE",
    "RECIPE_NOTES",
    "RECIPE_VARIANT",
    "KNOWLEDGE",
    "OTHER",
)
FREEFORM_ALLOWED_LABELS = frozenset(FREEFORM_LABELS)


def normalize_freeform_label(raw: str) -> str:
    """Normalize user/LLM freeform labels to canonical Label Studio values."""
    return raw.strip().upper().replace("-", "_").replace(" ", "_")


def build_freeform_label_config() -> str:
    """Return Label Studio XML config for freeform span highlighting."""
    labels_xml = "\n".join(f'    <Label value="{label}"/>' for label in FREEFORM_LABELS)
    return f"""
<View>
  <Header value="Cookbook Freeform Span Labeling"/>
  <Header value="Highlight any span and apply one label."/>
  <Header value="Label ONLY the focus range shown below. Nearby context is used for AI prelabeling, not displayed here."/>
  <Header value="$focus_scope_hint"/>
  <Header value="Focus: $focus_block_range | Context before: $context_before_block_range | Context after: $context_after_block_range"/>
  <Header value="Blocks are separated by blank lines in the text below."/>
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
