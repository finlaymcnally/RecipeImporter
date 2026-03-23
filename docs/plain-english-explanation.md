# A-to-Z

This is the current plain-English story of how a cookbook moves through the program from start to finish.

a note to AI editors: please do not include code/file referneces here. it is confusing and not helpful to read (unless you are highlihgting something about that file specifically, but each time you mention code doesn't need a "citation" to that file)

1. A run starts by creating a new timestamped output folder and deciding how much parallel work to use.

2. The program looks at each input file and chooses the importer that seems most appropriate for that file type.

3. Some importers are record-first. They try to read recipes directly from rows, fields, or structured data.

4. Other importers are block-first. They first turn the book into one long ordered stream of text blocks, then try to find recipe-shaped regions inside that stream.

5. At this early point, everything is still provisional. The importer is making its best first guess about recipes and leftover non-recipe text.

6. PDF and EPUB have an extra wrinkle: if the file is large, the program may split it into temporary sub-jobs. Those sub-jobs only do early parsing work.

7. When a file was split, the program later merges all the temporary pieces back together, rebuilds the full book text, fixes block indexes and recipe IDs, and only then runs the main semantic pipeline on the merged book.

8. The real center of the pipeline is a shared stage session. This is where most of the hidden architecture lives.

9. The first big thing that session does is rebuild an authoritative line-by-line view of the book. It creates a block archive, breaks blocks into smaller atomic lines, and labels those lines.

10. Those labels start with deterministic rules. If line-role review is enabled, an LLM may refine them. But even then, the program still treats the repo-owned validation and cleanup logic as the final gate.

11. After the lines are labeled, the program groups them back into recipe spans. This is where one of the most important authority changes happens.

12. Importer recipes are not the final truth. The final recipe list comes from whichever recipe spans survive this regrouping step.

13. A grouped span usually needs a title anchor to count as a real recipe. Structured-looking text without a proper title can be rejected as a pseudo-recipe.

14. If the importer thought there were recipes but the regrouping step ends up with zero real recipes, the program does not quietly fall back to the importer guess. It stays on the regrouped result and records that mismatch as a warning.

15. Once the accepted recipe spans exist, the program rebuilds recipe candidates from them.

16. That means recipe structure is regenerated after regrouping instead of simply being carried forward from the importer output.

17. If recipe LLM correction is enabled, it runs now, on the recipe side only.

18. Even then, the LLM is not the final writer. It is a correction layer. The program still builds the final recipe outputs locally with deterministic shaping code.

19. Next the program handles everything outside the accepted recipe spans. This is the Stage 7 non-recipe world.

20. Every outside-recipe block is classified into a simple seed map, mainly "knowledge" or "other," plus review routing.

21. Some obviously useless outside-recipe material can be excluded immediately here: navigation, publishing junk, endorsements, page furniture, and similar noise.

22. The important subtle rule is that outside-recipe meaning is intentionally unfinished at this point. Review-eligible outside-recipe text is not yet final semantic truth.

23. Another very non-obvious rule lives here: the earlier line-labeling stage is not allowed to be the final authority for outside-recipe knowledge. It can route and exclude obvious junk, but it is not supposed to make the final subtle "this is real cooking knowledge" judgment.

24. That final semantic judgment belongs to the later knowledge stage.

25. If the knowledge stage is off, the program keeps the deterministic Stage 7 seed result and moves on.

26. If the knowledge stage is on, it reviews only the outside-recipe text that survived Stage 7 and is still review-eligible.

27. Before the knowledge reviewer sees anything, the program chunks that non-recipe text into local pieces so the reviewer is not judging the entire book at once.

28. The current design uses deterministic chunks as the basic review units. Workers return block-level keep-or-reject decisions plus grounded snippets.

29. Those worker decisions refine the Stage 7 seed map into the final outside-recipe authority.

30. So the final "knowledge" blocks are not whatever the importer found, and not whatever the early line-labeler guessed. They are whatever survives this later review path.

31. After that, the program extracts tables from the non-recipe side, regenerates staged knowledge chunks, normalizes recipe tags, rebuilds the final report, and writes the finished artifacts.

32. The program writes recipe outputs in two main forms: an intermediate schema-style form and the final cookbook-style form.

33. It also writes sections, chunks, tables, non-recipe authority files, knowledge output files, raw debug artifacts, and run summaries.

34. Benchmark-style block predictions are produced near the end from the final staged recipes plus the final outside-recipe authority, not from the importer's first guesses.

35. Finally, the run writes summary and observability files so later tools can inspect what happened.

 # Hidden Layers

  - Importer output is provisional. Label-first regrouping is the real recipe authority seam.
    HAVE EXECPLANS

  - Deterministic label-first still runs even when all LLM pipelines are off.
  NOT A PROBLEM, IMPORTER ISN"T SUPPOSED TO DO ANYTHING
  
  - “Non-recipe” exists in two live runtime states now: Stage 7 seed routing and final reviewed authority.
    
  - ConversionResult.non_recipe_blocks is a downstream cache populated by the stage session after authoritative outside-recipe ownership exists.
  
  - Recipe Codex and knowledge Codex are refinement layers over repo-owned deterministic scaffolding, not direct final-output writers.
 
  - Split PDF/EPUB debugging is different from single-file debugging because the semantic pipeline runs only after merge.

 # Design Smells Worth Investigating

  - execute_stage_import_session_from_result() is a god-function. Too much pipeline truth is concentrated in one place, which makes invisible design coupling likely.
  cookimport/staging/import_session.py:379
  PLANNING TO ADDRESS IN REFACTOR

  - The authority story is clean in principle but hard in practice because ownership moves several times: importer -> label-first regrouping -> Stage 7 seed routing ->
  knowledge final authority.
  HAVE EXECPLANS

  - Chunk outputs now depend only on final non-recipe authority. If a run has no surviving outside-recipe rows, it should emit no chunks instead of reviving an importer-side fallback.

  - The artifact names make it look like 08_nonrecipe_spans.json is purely final truth, but it actually mixes seed routing, excluded junk, reviewed authority, and unreviewed
  review-eligible rows.
   HAVE EXECPLAN
