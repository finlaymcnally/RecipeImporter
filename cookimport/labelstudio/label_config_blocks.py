"""Label Studio config for canonical block labeling."""


def build_block_label_config() -> str:
    """Return Label Studio XML config for block classification tasks."""
    return """
<View>
  <Header value="Cookbook Block Labeling"/>
  <Text name="block_meta" value="Source: $source_file | Block $block_index"/>
  <Header value="Instructions"/>
  <Text name="instructions" value="Pick the best label for the block. Use OTHER when no label fits."/>
  <Header value="Context (Before)"/>
  <Text name="context_before" value="$context_before"/>
  <Header value="Block"/>
  <Text name="block_text" value="$block_text"/>
  <Header value="Context (After)"/>
  <Text name="context_after" value="$context_after"/>
  <Header value="Block Label"/>
  <Choices name="block_label" toName="block_text" choice="single" required="true">
    <Choice value="RECIPE_TITLE"/>
    <Choice value="INGREDIENT_LINE"/>
    <Choice value="INSTRUCTION_LINE"/>
    <Choice value="TIP"/>
    <Choice value="NARRATIVE"/>
    <Choice value="OTHER"/>
  </Choices>
</View>
""".strip()
