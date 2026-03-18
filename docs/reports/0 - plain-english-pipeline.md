## Plain-English Pipeline

If you want the current Codex-backed flow in operator language instead of artifact language, this is the simplest accurate version:

1. The program parses the cookbook into one ordered set of atomic lines and other deterministic intermediate structures.
2. The program makes a deterministic first pass over those lines before any Codex-backed review.
3. The line-role Codex surface reviews the whole book line set in one file-backed labeling pass. Operator-wise this is just "label the lines."
4. The program groups the corrected recipe-side lines into coherent recipe spans and recipes. Everything not grouped into recipe spans becomes the non-recipe side.
5. The recipe Codex surface reviews the recipe side in owned recipe shards. It returns corrected recipe payloads plus ingredient-step mapping and raw selected tags.
6. The program deterministically validates and promotes those recipe outputs into the final recipe formats.
7. The knowledge Codex surface reviews the non-recipe side. It does not blindly process every leftover line as raw text; the program first builds eligible non-recipe chunks and skips obvious low-signal noise. Codex then keeps/refines useful cooking knowledge while rejecting blurbs, filler, and other author yapping.
8. The program validates owned output coverage, writes artifacts/reports, and emits the final recipe, knowledge, and debug outputs.

Worker/shard mental model:

- A setting such as `5 / 5 / 5` means the runtime aims for about five owned shards/workers for each enabled surface (`line_role`, `recipe`, `knowledge`), not that five agents free-edit shared files in place.
- The durable contract is "immutable input payload in, structured owned output/proposal out." The runtime then validates exact ownership/coverage and promotes only valid results.
- Recipe tags are part of the recipe correction surface, not a fourth independent Codex phase.
- Freeform prelabel is separate again; it is not part of the recipe/line-role/knowledge trio above.