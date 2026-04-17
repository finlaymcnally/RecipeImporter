from __future__ import annotations

from cookimport.llm.knowledge_prompt_builder import build_knowledge_direct_prompt


def test_build_knowledge_direct_prompt_uses_inline_json_contract() -> None:
    prompt = build_knowledge_direct_prompt(
        {
            "bid": "fixture.kp0001.nr",
            "v": "1",
            "b": [{"i": 4, "t": "Whisk constantly."}],
            "x": {
                "p": [{"i": 3, "t": "Previous row."}],
                "n": [{"i": 5, "t": "Next row."}],
            },
        }
    )

    assert "{{INPUT_PATH}}" not in prompt
    assert "The authoritative packet JSON is included inline below." in prompt
    assert "Use only that inline JSON payload." in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "The raw packet block text is authoritative. Only mechanically true structure is provided." in prompt
    assert "checked-in Cookbook tag catalog" in prompt
    assert "packet adjacency is not semantic proof" in prompt
    assert "Each owned row is rendered as `rXX | row_index | text`." in prompt
    assert "Classify each owned block on its own merits." in prompt
    assert "Do the keep/drop judgment block by block before you think about idea groups." in prompt
    assert "Do not let one useful block launder nearby memoir" in prompt
    assert "retrieval-grade cooking leverage" in prompt
    assert "materially improve a cook's future decisions, diagnosis, or technique without needing the surrounding paragraph" in prompt
    assert "technically true but low-value, too generic, motivational" in prompt
    assert "personal story with an embedded cooking lesson is still usually `other`" in prompt
    assert "Praise, endorsement, foreword, thesis, manifesto" in prompt
    assert "proposed tag under an existing category" in prompt
    assert "keep only that block and leave the surrounding framing `other`" in prompt
    assert "A heading alone is not enough for `knowledge`." in prompt
    assert "keep it `other` even when it names the nearby concept clearly" in prompt
    assert "keep the heading itself `other` and let the explanatory body carry the `knowledge`" in prompt
    assert "use it to understand the body but keep the heading itself `other`" in prompt
    assert "unsupported by reusable explanatory body text in the owned packet" in prompt
    assert "Do not treat two blocks as one idea just because they are adjacent in the packet" in prompt
    assert "Every `knowledge` block must belong to exactly one idea group." in prompt
    assert "top level: `v`, `bid`, `d`, `g`" in prompt
    assert "decision: `i`, `c`, `gr`" in prompt
    assert "top level: `v` packet version, `bid` packet id, `rows` owned packet rows" in prompt
    assert "Every `g[*].s[*]` needs at least one evidence quote from owned packet blocks." in prompt
    assert "final answer must be that JSON object only" in prompt
    assert "return compact minified JSON on a single line" in prompt
    assert "<BEGIN_INPUT_JSON>" in prompt
    assert "<END_INPUT_JSON>" in prompt
    assert '"ontology":{' in prompt
    assert '"bid":"fixture.kp0001.nr"' in prompt
    assert '"rows":["r01 | 4 | Whisk constantly."]' in prompt
    assert '"context_before_rows":["3 | Previous row."]' in prompt
    assert '"context_after_rows":["5 | Next row."]' in prompt
