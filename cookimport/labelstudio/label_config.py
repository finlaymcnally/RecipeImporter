LABEL_CONFIG_XML = """
<View>
  <Header value="Cookbook Chunk Labeling"/>
  <Text name="text_display" value="$text_display"/>
  <Text name="text_raw" value="$text_raw"/>
  <Header value="Content Type"/>
  <Choices name="content_type" toName="text_display" choice="single" required="true">
    <Choice value="tip"/>
    <Choice value="recipe"/>
    <Choice value="step"/>
    <Choice value="ingredient"/>
    <Choice value="fluff"/>
    <Choice value="other"/>
    <Choice value="mixed"/>
  </Choices>
  <Header value="Value / Usefulness"/>
  <Choices name="value_usefulness" toName="text_display" choice="single" required="true">
    <Choice value="useful"/>
    <Choice value="neutral"/>
    <Choice value="useless"/>
    <Choice value="unclear"/>
  </Choices>
  <Header value="Optional Tags"/>
  <Choices name="tags" toName="text_display" choice="multiple">
    <Choice value="technique"/>
    <Choice value="troubleshooting"/>
    <Choice value="substitution"/>
    <Choice value="timing"/>
    <Choice value="storage"/>
    <Choice value="equipment"/>
    <Choice value="food_safety"/>
    <Choice value="measurement"/>
    <Choice value="science"/>
    <Choice value="make_ahead"/>
  </Choices>
</View>
"""
