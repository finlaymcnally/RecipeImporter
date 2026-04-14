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

    assert len(rows) == 5
    assert rows[0] == "The key to cooking starches properly is using the correct amount of water and heat."
    assert rows[1].endswith("crumbly.")
    assert all(len(row) < 220 for row in rows)
    assert all(row.count(".") + row.count("?") + row.count("!") <= 2 for row in rows)


def test_yield_word_inside_prose_no_longer_splits_mid_sentence() -> None:
    sample = (
        "Working with hot sugar is one of the few temperature-specific endeavors in the kitchen, "
        "but it's not a particularly difficult one. At about 290°F, a melted sugar syrup will "
        "yield a firm nougat, but just a ten-degree increase will yield toffee."
    )

    assert _split_block_text(sample) == [
        "Working with hot sugar is one of the few temperature-specific endeavors in the kitchen, "
        "but it's not a particularly difficult one.",
        "At about 290°F, a melted sugar syrup will yield a firm nougat, but just a ten-degree "
        "increase will yield toffee.",
    ]


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
