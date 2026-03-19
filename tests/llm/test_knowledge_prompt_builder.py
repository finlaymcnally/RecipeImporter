from __future__ import annotations

from cookimport.llm.knowledge_prompt_builder import build_knowledge_direct_prompt


def test_build_knowledge_direct_prompt_uses_inline_json_contract() -> None:
    prompt = build_knowledge_direct_prompt(
        {
            "bid": "fixture.ks0001.nr",
            "v": "2",
            "c": [],
        }
    )

    assert "{{INPUT_PATH}}" not in prompt
    assert "The authoritative shard JSON is included inline below." in prompt
    assert "Use only the inline JSON payload below." in prompt
    assert "Do not run shell commands, Python, or any other tools." in prompt
    assert "The raw chunk text is authoritative. Only mechanically true structure is provided." in prompt
    assert "Usually `other`: `PREFACE`, `Contents`, `Recipes and Recommendations`" in prompt
    assert "per chunk: `cid` chunk id, `b` blocks" in prompt
    assert (
        "When `c` is non-empty, `r` must contain exactly one row per input chunk, in input order."
        in prompt
    )
    assert "Do not return `r: []` when `c` is non-empty." in prompt
    assert "Never invent synthetic `cid` values such as `processing_error`." in prompt
    assert "final answer must be that JSON object only" in prompt
    assert "return compact minified JSON on a single line" in prompt
    assert (
        "If uncertain, still emit conservative `other` decisions and `s: []` for every input chunk."
        in prompt
    )
    assert "suggested lane" not in prompt.lower()
    assert "<BEGIN_INPUT_JSON>" in prompt
    assert "<END_INPUT_JSON>" in prompt
    assert '"bid":"fixture.ks0001.nr"' in prompt
