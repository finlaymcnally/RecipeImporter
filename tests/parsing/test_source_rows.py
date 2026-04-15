from cookimport.parsing.source_rows import _split_block_text


def test_large_prose_paragraph_breaks_into_smaller_rows() -> None:
    sample = (
        "The key to cooking starches properly is using the correct amount of water and heat. "
        "Use too little water or undercook starches and they will be dry and unpleasantly tough "
        "in the center. Cakes and bread baked with too little water are dry and crumbly. "
        "Undercooked pasta, beans, and rice are unpleasantly tough in the center. But use too "
        "much water or heat, or simply overcook starches, and they will be mushy. Starches are "
        "eager to undergo browning and will burn easily if overcooked or exposed to too much heat."
    )

    rows = _split_block_text(sample)

    assert len(rows) == 2
    assert rows[0].startswith(
        "The key to cooking starches properly is using the correct amount of water and heat."
    )
    assert "dry and crumbly." in rows[0]
    assert rows[1].endswith("too much heat.")
    assert all(len(row) < 360 for row in rows)
    assert all(row.count(".") + row.count("?") + row.count("!") <= 4 for row in rows)


def test_yield_word_inside_prose_no_longer_splits_mid_sentence() -> None:
    sample = (
        "Working with hot sugar is one of the few temperature-specific endeavors in the kitchen, "
        "but it's not a particularly difficult one. At about 290°F, a melted sugar syrup will "
        "yield a firm nougat, but just a ten-degree increase will yield toffee."
    )

    assert _split_block_text(sample) == [sample]


def test_makes_serves_and_yields_inside_prose_do_not_create_structural_splits() -> None:
    makes_sample = (
        "I don't recommend using iodized salt as it makes everything taste slightly metallic. "
        "In 1924, when iodine deficiency was a common health problem, Morton Salt began iodizing "
        "salt to help prevent goiters, leading to great strides in public health."
    )
    serves_sample = (
        "That opening bowl serves as a reminder that salt is structural, not decorative. "
        "It should support the rest of the dish."
    )
    yields_sample = (
        "Whisking steadily yields a smoother sauce when the pan is hot enough. "
        "It also keeps the emulsion stable."
    )

    assert _split_block_text(makes_sample) == [makes_sample]
    serves_rows = _split_block_text(serves_sample)
    assert serves_rows == [serves_sample]
    yields_rows = _split_block_text(yields_sample)
    assert yields_rows == [yields_sample]


def test_lowercase_mid_sentence_serves_no_longer_creates_yield_split() -> None:
    sample = (
        "But she only ever serves one of two salads at our dinner table: Persian cucumber, "
        "tomato, and onion, or Shirazi Salad, and a romaine-pecorino-sun-dried tomato number. "
        "As a child, I quickly grew bored with salad. By the time I left for college, "
        "I'd disavowed it altogether."
    )

    assert _split_block_text(sample) == [sample]


def test_to_x_and_for_x_phrases_do_not_split_prose_mid_sentence() -> None:
    sample = (
        "Sometimes you'll need to use multiple fats to achieve different textures within a "
        "single dish. Deep-fry crisp pieces of fish in grapeseed oil, and then use olive oil "
        "to make a creamy Aioli to serve alongside it. Use oil to make a supremely moist "
        "Chocolate Midnight Cake, then slather it in buttercream frosting or softly whipped cream."
    )

    assert _split_block_text(sample) == [sample]


def test_standalone_howto_headings_still_survive_without_boundary_split() -> None:
    assert _split_block_text("FOR THE SAUCE") == ["FOR THE SAUCE"]
    assert _split_block_text("To Serve") == ["To Serve"]
    assert _split_block_text("To make a creamy Aioli") == ["To make a creamy Aioli"]


def test_yield_line_separates_cleanly_from_first_ingredient() -> None:
    sample = "Serves 6-10 1 kg pork rind, with a 5mm layer of fat left on 2-3 tbsp cornish sea salt"

    assert _split_block_text(sample) == [
        "Serves 6-10",
        "1 kg pork rind, with a 5mm layer of fat left on",
        "2-3 tbsp cornish sea salt",
    ]


def test_existing_small_recipe_rows_stay_unchanged() -> None:
    assert _split_block_text("1 cup stock 2 tbsp butter") == [
        "1 cup stock",
        "2 tbsp butter",
    ]
    assert _split_block_text("FOR THE SAUCE") == ["FOR THE SAUCE"]
    assert _split_block_text("Step 1. Whisk the stock and butter together until glossy.") == [
        "Step 1. Whisk the stock and butter together until glossy."
    ]


def test_dense_title_catalog_stays_grouped_for_context() -> None:
    sample = (
        "Beans. Braises. Paella. Jasmine Rice. Chicken Vindaloo. Pozole . Quinoa. Stews. "
        "Risotto. Chili. Béchamel sauce. Potato gratin. Tomato sauce. Chicken stock. "
        "Polenta. Oatmeal. Thai curry. It didn't matter-this applied to everything cooked "
        "in liquid. It was a life-changing revelation!"
    )

    assert _split_block_text(sample) == [sample]


def test_question_ladder_stays_grouped_for_context() -> None:
    sample = (
        "Relinquish the false sense of control an oven offers, just like I did at the spit. "
        "Instead pay attention to how your food is cooking. Is it rising? Browning? Setting? "
        "Smoking? Bubbling? Burning? Jiggling? When you read recipes, think of temperatures "
        "and cooking times as strong suggestions, rather than fixed rules. Set your timer for "
        "a few minutes less than a recipe might suggest, then use all of your senses to check "
        "for doneness. Always remember the qualities you seek in your food. Adjust course "
        "constantly and accordingly to achieve them. This is what good cooking looks like."
    )

    assert _split_block_text(sample) == [sample]


def test_long_narrative_paragraph_rechunks_into_balanced_rows() -> None:
    sample = (
        "The first paid job I had in the kitchen at Chez Panisse was called Pasta/Lettuce. "
        "I spent about a year washing lettuces and making every kind of pasta dough imaginable. "
        "I'd also start the pizza dough every morning, adding yeast, water, and flour into "
        "the bowl of the gigantic stand mixer and tending to it throughout the day. Once the "
        "water and flour brought the dormant yeast back to life, I'd add more flour and salt. "
        "Then, after kneading and proofing, I'd finish the dough by adding in some olive oil. "
        "One day, when it was time to add the flour and salt, I realized the salt bin was "
        "empty. I didn't have the time right then to go down to the storage shed to get "
        "another bag of salt, so I figured I'd just wait to add the salt at the end, along "
        "with the oil. As I kneaded the dough, I noticed that it came together much more "
        "quickly than usual, but I didn't really give it a second thought. When I returned a "
        "couple of hours later to finish the dough, something unbelievable happened. I turned "
        "on the machine and let it deflate and knead the dough, like I always did, and then I "
        "added the salt. As it dissolved into the dough, I could actually see the machine "
        "begin to strain. The salt was making the dough tougher-the difference was remarkable! "
        "I had no idea what was happening. I was worried that I'd done something terribly wrong."
    )

    rows = _split_block_text(sample)

    assert len(rows) == 4
    assert rows[0].startswith(
        "The first paid job I had in the kitchen at Chez Panisse was called Pasta/Lettuce."
    )
    assert rows[-1] == "I had no idea what was happening. I was worried that I'd done something terribly wrong."
    assert all(len(row) <= 520 for row in rows)
