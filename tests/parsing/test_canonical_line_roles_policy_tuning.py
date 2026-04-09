from __future__ import annotations

import tests.parsing.canonical_line_role_support as _support

globals().update({
    name: value
    for name, value in _support.__dict__.items()
    if not name.startswith("test_")
    and not (name.startswith("__") and name.endswith("__"))
})


def test_deterministic_outside_recipe_technique_heading_routes_to_candidate(tmp_path) -> None:
    predictions = label_atomic_lines(
        [
            AtomicLineCandidate(
                recipe_id=None,
                block_id="block:technique:0",
                block_index=0,
                atomic_index=0,
                text="Balancing Fat",
                within_recipe_span=False,
                rule_tags=["title_like"],
            )
        ],
        _settings("off"),
        artifact_root=tmp_path,
        live_llm_allowed=False,
    )

    assert predictions[0].label == "NONRECIPE_CANDIDATE"


def test_deterministic_outside_recipe_copyright_boilerplate_stays_excluded(tmp_path) -> None:
    predictions = label_atomic_lines(
        [
            AtomicLineCandidate(
                recipe_id=None,
                block_id="block:legal:0",
                block_index=0,
                atomic_index=0,
                text="Copyright 2024 by Example Press. All rights reserved.",
                within_recipe_span=False,
                rule_tags=["explicit_prose"],
            )
        ],
        _settings("off"),
        artifact_root=tmp_path,
        live_llm_allowed=False,
    )

    assert predictions[0].label == "NONRECIPE_EXCLUDE"


def test_codex_outside_recipe_title_led_cluster_accepts_instruction_lines(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:title",
            block_index=1100,
            atomic_index=0,
            text="Roasted Beets",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:prep",
            block_index=1102,
            atomic_index=1,
            text=(
                "Preheat the oven to 425°F. Place the beets in a baking dish in a "
                "single layer and fill the pan with 1/4-inch water just enough to "
                "create steam in the pan without simmering the beets."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:finish",
            block_index=1103,
            atomic_index=2,
            text=(
                "Let the beets cool just enough so you can handle them, and then peel "
                "by rubbing with a paper towel. Cut into bite-size wedges and toss "
                "with wine vinegar, olive oil, and salt."
            ),
            within_recipe_span=False,
            rule_tags=["note_like_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "RECIPE_TITLE",
                1: "INSTRUCTION_LINE",
                2: "INSTRUCTION_LINE",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_TITLE",
        "INSTRUCTION_LINE",
        "INSTRUCTION_LINE",
    ]
    assert all(prediction.decided_by == "codex" for prediction in predictions)


def test_codex_outside_recipe_to_serve_line_accepts_instruction_with_title_support(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:title",
            block_index=1100,
            atomic_index=0,
            text="Roasted Beets",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:prep",
            block_index=1102,
            atomic_index=1,
            text=(
                "Preheat the oven to 425°F. Place the beets in a baking dish in a "
                "single layer and roast until tender."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:beets:serve",
            block_index=1104,
            atomic_index=2,
            text=(
                "To serve, arrange the wedges on the platter and season lightly "
                "with salt."
            ),
            within_recipe_span=False,
            rule_tags=["note_like_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "RECIPE_TITLE",
                1: "INSTRUCTION_LINE",
                2: "INSTRUCTION_LINE",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[2].label == "INSTRUCTION_LINE"
    assert predictions[2].decided_by == "codex"
    assert "codex_policy_rejected:instruction_without_local_support" not in (
        predictions[2].reason_tags
    )


def test_codex_outside_recipe_prepositional_instruction_accepts_component_context(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:dressing:ingredient:1",
            block_index=1368,
            atomic_index=0,
            text="1 garlic clove",
            within_recipe_span=False,
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:dressing:ingredient:2",
            block_index=1369,
            atomic_index=1,
            text="Salt",
            within_recipe_span=False,
            rule_tags=["ingredient_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:dressing:instruction:1",
            block_index=1370,
            atomic_index=2,
            text="In a small bowl or jar, let the shallot sit in the vinegars for 15 minutes to macerate.",
            within_recipe_span=False,
            rule_tags=["time_metadata"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:dressing:instruction:2",
            block_index=1371,
            atomic_index=3,
            text=(
                "Add the basil leaves, olive oil, and a generous pinch of salt and "
                "stir to combine."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "INGREDIENT_LINE",
                1: "INGREDIENT_LINE",
                2: "INSTRUCTION_LINE",
                3: "INSTRUCTION_LINE",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[2].label == "INSTRUCTION_LINE"
    assert predictions[2].decided_by == "codex"


def test_codex_outside_recipe_taste_adjust_step_accepts_instruction_cluster(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:croutons:1",
            block_index=1282,
            atomic_index=0,
            text="Toss the croutons with the olive oil and spread them out in a single layer.",
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:croutons:2",
            block_index=1283,
            atomic_index=1,
            text="Toast the croutons until golden brown and crunchy on the outside.",
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:croutons:3",
            block_index=1284,
            atomic_index=2,
            text="Taste a crouton and adjust the seasoning with a light sprinkling of salt if needed.",
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:croutons:4",
            block_index=1285,
            atomic_index=3,
            text="Let the croutons cool and keep in an airtight container for up to 2 days.",
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "INSTRUCTION_LINE",
                1: "INSTRUCTION_LINE",
                2: "INSTRUCTION_LINE",
                3: "INSTRUCTION_LINE",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[2].label == "INSTRUCTION_LINE"
    assert predictions[2].decided_by == "codex"


def test_codex_outside_recipe_variation_heading_accepts_named_variant_continuation(
    tmp_path,
) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:variation:heading",
            block_index=1357,
            atomic_index=0,
            text="Variation",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:variation:body",
            block_index=1358,
            atomic_index=1,
            text=(
                "To make a sweet-tart Kumquat Vinaigrette, add 3 tablespoons finely "
                "diced kumquats to the shallots and continue as above."
            ),
            within_recipe_span=False,
            rule_tags=["explicit_prose"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "RECIPE_VARIANT",
                1: "RECIPE_VARIANT",
            }
        ),
        live_llm_allowed=True,
    )

    assert [prediction.label for prediction in predictions] == [
        "RECIPE_VARIANT",
        "RECIPE_VARIANT",
    ]
    assert all(prediction.decided_by == "codex" for prediction in predictions)


def test_codex_outside_recipe_narrative_warning_keeps_instruction_authoritative(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:avocado:title",
            block_index=1096,
            atomic_index=0,
            text="Avocado Salad",
            within_recipe_span=False,
            rule_tags=["title_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:avocado:note",
            block_index=1097,
            atomic_index=1,
            text=(
                "Hass avocados are delicious when perfectly ripe and tender to the touch."
            ),
            within_recipe_span=False,
            rule_tags=["note_like_prose"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:avocado:warning",
            block_index=1098,
            atomic_index=2,
            text=(
                "A friend who's been a hand surgeon for nearly forty years told me that "
                "avocados and bagels are the two most common causes of hand injuries. "
                "So please put the avocado down on the board when you remove the pit."
            ),
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "RECIPE_TITLE",
                1: "NONRECIPE_CANDIDATE",
                2: "INSTRUCTION_LINE",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[2].label == "INSTRUCTION_LINE"
    assert predictions[2].decided_by == "codex"


def test_codex_outside_recipe_storage_note_keeps_instruction_authoritative(tmp_path) -> None:
    candidates = [
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:salad:instruction:1",
            block_index=1213,
            atomic_index=0,
            text="Dress the salad, toss, taste again, and serve.",
            within_recipe_span=False,
            rule_tags=["instruction_like"],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:salad:storage",
            block_index=1215,
            atomic_index=1,
            text="Refrigerate leftovers, covered, for up to one night.",
            within_recipe_span=False,
            rule_tags=[],
        ),
        AtomicLineCandidate(
            recipe_id=None,
            block_id="block:salad:variation",
            block_index=1216,
            atomic_index=2,
            text="Variations",
            within_recipe_span=False,
            rule_tags=[],
        ),
    ]

    predictions = label_atomic_lines(
        candidates,
        _settings("codex-line-role-route-v2"),
        artifact_root=tmp_path,
        codex_runner=_line_role_runner(
            {
                0: "INSTRUCTION_LINE",
                1: "INSTRUCTION_LINE",
                2: "NONRECIPE_CANDIDATE",
            }
        ),
        live_llm_allowed=True,
    )

    assert predictions[1].label == "INSTRUCTION_LINE"
    assert predictions[1].decided_by == "codex"
