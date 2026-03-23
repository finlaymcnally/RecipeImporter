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
    assert "durable cooking leverage" in prompt
    assert "materially improve a cook's future decisions, diagnosis, or technique" in prompt
    assert "technically true but low-value" in prompt
    assert "keep that heading with the useful body instead of forcing it to `other` as decoration" in prompt
    assert "Usually `knowledge`: a short concept heading such as `How Salt Affects . . .`" in prompt
    assert "per chunk: `cid` chunk id, `b` blocks" in prompt
    assert (
        "The input always contains exactly one owned chunk. When `c` is non-empty, `r` must therefore contain exactly one row for that chunk."
        in prompt
    )
    assert (
        '`u=true` requires at least one `d[*].c="knowledge"` decision and at least one snippet in `s`.'
        in prompt
    )
    assert (
        "`u=false` requires every `d[*].c` to be `other` and requires `s=[]`."
        in prompt
    )
    assert "Do not return `r: []` when `c` is non-empty." in prompt
    assert "Never invent synthetic `cid` values such as `processing_error`." in prompt
    assert "final answer must be that JSON object only" in prompt
    assert "return compact minified JSON on a single line" in prompt
    assert "Do not collapse a clearly useful technique/reference shard into blanket `u=false`." in prompt
    assert (
        "If the shard contains durable cooking leverage, surface it positively with `u=true`, `knowledge` decisions, and grounded snippets."
        in prompt
    )
    assert "suggested lane" not in prompt.lower()
    assert "<BEGIN_INPUT_JSON>" in prompt
    assert "<END_INPUT_JSON>" in prompt
    assert '"bid":"fixture.ks0001.nr"' in prompt
