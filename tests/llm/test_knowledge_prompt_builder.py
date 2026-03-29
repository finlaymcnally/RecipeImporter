from __future__ import annotations

from cookimport.llm.knowledge_prompt_builder import build_knowledge_direct_prompt


def test_build_knowledge_direct_prompt_uses_inline_json_contract() -> None:
    prompt = build_knowledge_direct_prompt(
        {
            "bid": "fixture.kp0001.nr",
            "v": "1",
            "b": [{"i": 4, "t": "Whisk constantly."}],
        }
    )

    assert "{{INPUT_PATH}}" not in prompt
    assert "The authoritative packet JSON is included inline below." in prompt
    assert "Use only that inline JSON payload." in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "The raw packet block text is authoritative. Only mechanically true structure is provided." in prompt
    assert "packet adjacency is not semantic proof" in prompt
    assert "Classify each owned block on its own merits." in prompt
    assert "durable cooking leverage" in prompt
    assert "materially improve a cook's future decisions, diagnosis, or technique" in prompt
    assert "technically true but low-value" in prompt
    assert "keep that heading with the useful body instead of forcing it to `other`" in prompt
    assert "Do not treat two blocks as one idea just because they are adjacent in the packet" in prompt
    assert "Every `knowledge` block must belong to exactly one idea group." in prompt
    assert "top level: `v`, `bid`, `d`, `g`" in prompt
    assert "top level: `v` packet version, `bid` packet id, `b` owned packet blocks" in prompt
    assert "Every `g[*].s[*]` needs at least one evidence quote from owned packet blocks." in prompt
    assert "final answer must be that JSON object only" in prompt
    assert "return compact minified JSON on a single line" in prompt
    assert "<BEGIN_INPUT_JSON>" in prompt
    assert "<END_INPUT_JSON>" in prompt
    assert '"bid":"fixture.kp0001.nr"' in prompt
