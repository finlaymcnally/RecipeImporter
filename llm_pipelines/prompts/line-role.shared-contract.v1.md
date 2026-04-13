Label distinctions that matter:
- `RECIPE_TITLE`: fresh recipe names that start a new recipe, especially when the next rows turn into yield, ingredients, or method.
- `INGREDIENT_LINE`: quantity/unit ingredients and bare ingredient items in ingredient lists.
- `INSTRUCTION_LINE`: recipe-local imperative action sentences, even when they include time.
- `TIME_LINE`: stand-alone timing/temperature lines, not full instruction sentences.
- `HOWTO_SECTION` is recipe-internal only. Use it for subsection headings that split one recipe into a real mini-preparation with its own nearby ingredients and/or steps.
- `HOWTO_SECTION` is book-optional. Some books legitimately use zero of them, so do not invent subsection structure just because the label exists.
- `YIELD_LINE`: stand-alone yield or serving lines such as `SERVES 4` or `Makes about 1/2 cup`.
- `RECIPE_VARIANT`: local alternate-version headings, intro prose, or short alternate-version runs inside one parent recipe.
- `RECIPE_NOTES`: recipe-local prose that belongs with the current recipe but is not ingredient or instruction structure, including storage, leftovers, make-ahead, and freezing guidance.
- `NONRECIPE_CANDIDATE`: outside-recipe material that is not recipe-local and should be sent to knowledge later.
- `NONRECIPE_EXCLUDE`: obvious outside-recipe junk that should never reach knowledge.

Negative rules:
- If a line contains explicit cooking action plus time mention, prefer `INSTRUCTION_LINE` over `TIME_LINE`.
- `INSTRUCTION_LINE` means a recipe-local procedural step for the current recipe, not generic culinary advice or cookbook teaching prose.
- Do not use `INSTRUCTION_LINE` for explanatory/advisory prose just because it contains verbs like `use`, `choose`, `let`, `think about`, or `remember`.
- If a line discusses what cooks generally should do, or gives examples across many dishes rather than advancing one recipe, prefer `NONRECIPE_CANDIDATE`, not `INSTRUCTION_LINE`.
- If local evidence is genuinely ambiguous, resolve the row from the text and neighboring context alone.
- If the shard rows are outside recipe context, default to `NONRECIPE_CANDIDATE`; only use recipe-structure labels when nearby rows in the same shard show immediate recipe-local evidence.
- Use `HOWTO_SECTION` only when nearby rows show immediate recipe-local structure before or after the heading.
- A `HOWTO_SECTION` should own a real mini-preparation. If the heading is just one named component inside a larger ingredient list, do not promote it to `HOWTO_SECTION`.
- A short named component such as `Lime Vinaigrette` is usually not `HOWTO_SECTION` when the nearby rows show it is simply one ingredient/component among many rather than the start of its own ingredient-and-step subsection.
- A single outside-recipe heading by itself is not enough to justify `HOWTO_SECTION`.
- A full sentence or paragraph beginning with `To make ...` or `To serve ...` is usually variant or procedural prose, not `HOWTO_SECTION`, unless the whole line is a short heading-shaped header.
- A bare cue line such as `Variation` or `Variations` is not itself enough for `RECIPE_VARIANT`; treat it as a cue that following rows may become variant content.
- The rows after `Variation` or `Variations` may still be `RECIPE_VARIANT` when they clearly form a local alternate-version run inside the current recipe.
- A heading-like variant title and its immediately attached intro prose can both be `RECIPE_VARIANT` when nearby rows show they are introducing alternate versions within the current recipe rather than a new recipe or generic prose.
- Short `Variation` / `Variations` follow-up lines such as `To add a little heat ...` or `To evoke the flavors ...` usually stay `RECIPE_VARIANT`.
- Variant context is local, not sticky. End a nearby `Variations` run when a fresh title-like line is followed by a strict yield line or ingredient rows.
- Do not let nearby `Variations` prose swallow a fresh recipe start such as `Bright Cabbage Slaw` -> `Serves 4 generously` -> `1/2 medium red onion, sliced thinly`.
- If a short title-like line is immediately followed by a strict yield line or ingredient rows, reset to a new recipe: prefer `RECIPE_TITLE`, not `RECIPE_VARIANT`, even when earlier nearby rows were variants.
- A strict yield header such as `SERVES 4`, `Makes about 1/2 cup`, or `Yield: 6 servings` stays `YIELD_LINE` when it appears between a recipe title and ingredient or method structure; do not downgrade it to `RECIPE_NOTES`.
- Storage guidance belongs to `RECIPE_NOTES`, not `INSTRUCTION_LINE`, even when written as an imperative sentence.
- Lines about refrigerating, storing, freezing, leftovers, keeping time, or make-ahead handling usually stay `RECIPE_NOTES`.
- Local row evidence wins over shaky prior span assumptions. A title-like line followed by yield or ingredients can still be `RECIPE_TITLE` even if upstream recipe-span state is missing or noisy.
- Do not use `HOWTO_SECTION` for chapter, part, topic, or cookbook-lesson headings such as `Salt and Pepper`, `Cooking Acids`, `Starches`, or `Stewing and Braising`; those are usually outside-recipe labels.
- If a heading introduces explanatory prose rather than recipe-local ingredients or steps, prefer `NONRECIPE_CANDIDATE`, not `HOWTO_SECTION`.
- Lesson headings such as `Balancing Fat` or `WHAT IS ACID?` stay `NONRECIPE_CANDIDATE` only when surrounding rows clearly carry reusable explanatory prose.
- A lone question-style or topic heading such as `What is Heat?` or `Balancing Fat` usually stays `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose worth knowledge review.
- Contents-style title lists, endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.
- Contents-style title lists such as `Winter: Roasted Radicchio and Roquefort` or `Torn Croutons` usually stay `NONRECIPE_EXCLUDE` unless nearby rows prove one live recipe.
- Endorsements, intro framing, and isolated topic headings default to `NONRECIPE_EXCLUDE` unless nearby rows clearly show reusable lesson prose or one live recipe.
- Obvious praise blurbs, foreword or preface setup, book-thesis or manifesto framing, and `this book will teach you ...` jacket-copy promises usually stay `NONRECIPE_EXCLUDE`, not `NONRECIPE_CANDIDATE`.
- First-person narrative or memoir framing is usually `NONRECIPE_EXCLUDE` when it reads like foreword/introduction setup rather than reusable cooking knowledge.
- Endorsements, acknowledgments, foreword/introduction framing, memoir setup, and broad book-encouragement prose usually stay `NONRECIPE_EXCLUDE`; use `NONRECIPE_CANDIDATE` only when the line itself carries reusable cooking knowledge.
- Dedications, acknowledgments, author biography, restaurant backstory, travel scenes, childhood food memories, and chef-origin stories usually stay `NONRECIPE_EXCLUDE` even when they mention real dishes, ingredients, or kitchen lessons.
- Broad encouragement or manifesto prose such as `you can become a great cook`, `keep reading and I'll teach you how`, or `trust your palate` usually stays `NONRECIPE_EXCLUDE`, not `NONRECIPE_CANDIDATE`.
- Do not rescue a memoir or intro paragraph into `NONRECIPE_CANDIDATE` just because it contains one true cooking claim near the end. If the row still reads mainly like story, framing, or inspiration, keep it `NONRECIPE_EXCLUDE`.
- Use `NONRECIPE_CANDIDATE` only when the row itself would be worth retrieving later as a standalone cooking concept without needing the memoir, chapter setup, or book-thesis wrapper around it.
- Mixed anecdote-plus-moral rows usually stay `NONRECIPE_EXCLUDE`. If a later row states the reusable lesson directly and can stand on its own, that later row may be `NONRECIPE_CANDIDATE`.

Few-shot examples:
1) Context: inside recipe, heading line
   Line: `FOR THE MALT COOKIES`
   Label: `HOWTO_SECTION`

2) Context: adjacent lines are ingredients
   Line: `Grapeseed oil`
   Label: `INGREDIENT_LINE`

3) Context: inside recipe
   Line: `SERVES 4`
   Label: `YIELD_LINE`

4) Context: recipe method
   Line: `Whisk in the cream and simmer for 2 to 3 minutes.`
   Label: `INSTRUCTION_LINE`

5) Context: inside recipe
   Line: `NOTE: Cooled hollandaise can break if reheated too fast.`
   Label: `RECIPE_NOTES`

6) Context: inside recipe explanatory prose
   Line: `Copper pans conduct heat quickly and evenly, so temperature changes show up fast.`
   Label: `RECIPE_NOTES`

7) Context: inside recipe, ingredient range
   Line: `4 to 6 chicken leg quarters`
   Label: `INGREDIENT_LINE`

8) Context: inside recipe, all-caps variant header
   Line: `DINER-STYLE MUSHROOM, PEPPER, AND ONION OMELET`
   Label: `RECIPE_VARIANT`

9) Context: inside recipe, primary recipe heading
   Line: `A PORRIDGE OF LOVAGE STEMS`
   Label: `RECIPE_TITLE`

10) Context: cookbook concept heading introducing explanatory prose
    Line: `Cooking Acids`
    Label: `NONRECIPE_CANDIDATE`

11) Context: front matter or navigation heading
    Line: `Acknowledgments`
    Label: `NONRECIPE_EXCLUDE`

12) Context: broad outside-recipe action-verb advice
    Line: `Use limes in guacamole, pho ga, green papaya salad, and kachumbar.`
    Label: `NONRECIPE_CANDIDATE`

13) Context: general teaching/setup prose, not a recipe step
    Line: `Think about making a grilled cheese sandwich.`
    Label: `NONRECIPE_CANDIDATE`

14) Context: outside recipe, lesson heading with explanatory prose nearby
    Line: `Gentle Cooking Methods`
    Label: `NONRECIPE_CANDIDATE`

15) Context: outside recipe, memoir or introduction framing prose
    Line: `Then I fell in love with Johnny, who introduced me to San Francisco.`
    Label: `NONRECIPE_EXCLUDE`

16) Context: outside recipe, reusable lesson prose with brief first-person framing
    Line: `Salt, Fat, Acid, and Heat were the four elements that guided basic decision making in every single dish, no matter what.`
    Label: `NONRECIPE_CANDIDATE`

17) Context: outside recipe, short declarative lesson line in a knowledge cluster
    Line: `Foods that are too dry can be corrected with a bit more fat.`
    Label: `NONRECIPE_CANDIDATE`

18) Context: outside recipe, lone question heading without explanatory support
    Line: `What is Heat?`
    Label: `NONRECIPE_EXCLUDE`

19) Context: front matter or contents heading, not a live recipe
    Line: `The Four Elements of Good Cooking`
    Label: `NONRECIPE_EXCLUDE`

20) Context: contents-style seasonal title list
    Line: `Winter: Roasted Radicchio and Roquefort`
    Label: `NONRECIPE_EXCLUDE`

21) Context: outside recipe, publisher-style promise or thesis framing
    Line: `This book will teach you the four elements of good cooking.`
    Label: `NONRECIPE_EXCLUDE`

22) Context: outside recipe, obvious imperative prep step with nearby recipe structure
    Line: `Quarter the cabbage through the core. Use a sharp knife to cut the core out at an angle.`
    Label: `INSTRUCTION_LINE`

23) Context: short variation follow-up line after `Variations`
    Line: `To add a little heat, add 1 teaspoon minced jalapeño.`
    Label: `RECIPE_VARIANT`

24) Context: nearby rows are `Variations`, variant prose, then a fresh recipe start followed by yield and ingredients
    Line: `Bright Cabbage Slaw`
    Label: `RECIPE_TITLE`

25) Context: strict yield header immediately after that fresh recipe title
    Line: `Serves 4 generously`
    Label: `YIELD_LINE`

26) Context: ingredient row immediately after the reset title and yield
    Line: `1/2 medium red onion, sliced thinly`
    Label: `INGREDIENT_LINE`

27) Context: outside recipe, memoir anecdote with an embedded cooking takeaway
    Line: `After years of cooking, I finally understood why that bowl of polenta needed more salt.`
    Label: `NONRECIPE_EXCLUDE`

28) Context: outside recipe, explicit standalone lesson stated after the anecdote
    Line: `Taste constantly as you cook, and adjust seasoning before serving.`
    Label: `NONRECIPE_CANDIDATE`

29) Context: outside recipe, broad book promise or encouragement prose
    Line: `Keep reading and I'll teach you how to cook with confidence.`
    Label: `NONRECIPE_EXCLUDE`

30) Context: inside recipe, bare cue heading before alternate-version rows
    Line: `Variations`
    Label: `RECIPE_NOTES`

31) Context: inside recipe, heading-like local alternate-version title after a `Variations` cue
    Line: `Three Classic Shaved Salads`
    Label: `RECIPE_VARIANT`

32) Context: inside recipe, explanatory prose that is still introducing the local variant run
    Line: `I inherited my fondness for shaved salads from my friend Cal Peternell, and these are the three versions I return to most often.`
    Label: `RECIPE_VARIANT`

33) Context: inside recipe, named component within a larger ingredient list rather than its own sub-preparation
    Line: `Lime Vinaigrette`
    Label: `INGREDIENT_LINE`

34) Context: inside recipe, storage guidance after the main method
    Line: `Refrigerate leftovers, covered, for up to one night.`
    Label: `RECIPE_NOTES`
