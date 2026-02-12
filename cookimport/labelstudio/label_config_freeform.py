"""Label Studio config for freeform text-span annotation."""


def build_freeform_label_config() -> str:
    """Return Label Studio XML config for freeform span highlighting."""
    return """
<View>
  <Header value="Cookbook Freeform Span Labeling"/>
  <Header value="Highlight any span and apply one label."/>
  <Text
    name="segment_text"
    value="$segment_text"
    style="white-space: pre-wrap;"
  />
  <Labels name="span_labels" toName="segment_text">
    <Label value="RECIPE_TITLE"/>
    <Label value="INGREDIENT_LINE"/>
    <Label value="INSTRUCTION_LINE"/>
    <Label value="TIP"/>
    <Label value="NOTES"/>
    <Label value="VARIANT"/>
    <Label value="YIELD_LINE"/>
    <Label value="TIME_LINE"/>
    <Label value="OTHER"/>
  </Labels>
</View>
""".strip()
