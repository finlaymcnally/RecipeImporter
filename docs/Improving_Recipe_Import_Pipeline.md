# Improving Recipe Import Pipeline: Extracting Cooking Tips & Knowledge

> **ExecPlan Integration Notes (2026-01-24):**
>
> Ideas from this document have been distributed to execplans as follows:
>
> **Added to PROCESS-tip-knowledge-extraction-execplan.md:**
> - Multi-pass heuristic parsing (~92.6% accuracy research)
> - Lexical classification signals (generic vs specific language, length as signal)
> - Explanatory keywords as general knowledge indicators
> - Confidence-based LLM escalation strategy
>
> **Added to PROCESS-common-parsing-and-normalization.md:**
> - SpaCy NLP integration (Matcher, POS tagging, TextCategorizer)
> - Cookbook-specific overrides approach
> - Testing/validation with golden sets
>
> **Added to NEW PROCESS-ml-text-classification.md:**
> - Zero-shot classification (BART-large-MNLI)
> - Weak supervision (Snorkel-style labeling functions)
> - Supervised classification (TF-IDF, DistilBERT)
> - Clustering/topic modeling for discovery
>
> **Already covered (no changes needed):**
> - Distinguishing general tips from recipe-specific notes (already in tip extraction plan)
> - Hybrid pipeline with rules + LLM (already in PROCESS-llm-repair.md)
> - Schema-constrained LLM output (already in PROCESS-llm-repair.md)
> - Ingredient parser library recommendation (already using it: PROCESS-ingredient-parser-integration.md)

## Understanding the Challenge of Cookbook Knowledge Extraction

Extracting general cooking **tips and knowledge** from cookbook text is
difficult because these snippets are often embedded alongside structured
recipes. Unlike clearly delineated recipe sections (titles, ingredients,
steps), tips and culinary advice appear in narrative form – for example,
in chapter introductions or side notes – making them harder to identify
programmatically. In many cases, **narrative content is mixed with
structured recipe text**, which confuses simple
parsers[\[1\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=an%20important%20and%20common%20extraction,strategic%20use%20by%20IE%20systems).
The key challenges include distinguishing **recipe-specific notes**
(e.g. “If you don’t have panko, this chicken dish works with regular
breadcrumbs”) from **general cooking tips** (e.g. “Always let steak rest
before cutting”) and **capturing longer explanatory pieces** (culinary
science or technique discussions) that may not be explicitly flagged as
tips. Additionally, without clear markers, a naïve parser may pick up
random sentences as “tips,” leading to false positives. Addressing these
challenges requires a combination of structural heuristics and language
understanding beyond basic regex rules.

## Leveraging Document Structure and Heuristics

A good starting point is to use the inherent **structure of cookbooks**
and some heuristic rules to separate recipes from other content. Most
cookbooks follow a semi-structured format (recipe titles, ingredient
lists, instructions, etc.), which you can exploit. For example:

- **Identify Recipe Boundaries:** Use cues like formatting or known
  patterns to find where each recipe starts and ends. Recipe titles
  might be in all-caps or a larger font (in text, maybe a line by
  itself). Ingredient lines often contain numbers, units, or fractions
  (e.g. “2 cups flour”), and instructions often start with verbs in
  imperative form (“Heat the pan…”). By detecting these patterns, you
  can mark sections of text that are definitely part of recipes (title,
  ingredients, steps). Everything **outside these sections** can be
  treated as candidate “knowledge/tip” text.
- **Multi-pass Heuristic Parsing:** Consider a multi-pass approach where
  you apply successive layers of rules to refine the extraction. For
  instance, a first pass could extract obvious recipes (using the cues
  above). A second pass can then process the remaining text to find
  **standalone tips or explanations**. This kind of layered rule-based
  strategy has been shown to work well for document text classification.
  In fact, a **rule-based multi-pass sieve** method for PDF text
  segmentation achieved ~92.6% accuracy, outperforming a
  machine-learning classifier on a similar
  task[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=The%20multi,%28p%3D0.005).
  The authors concluded that such a framework can effectively categorize
  mixed text segments and is a strong prerequisite step before deeper
  information
  extraction[\[3\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=Conclusions).
  This suggests that carefully designed heuristic rules, applied in
  sequence, can reliably separate structured recipe content from
  narrative tips in many cases.
- **Layout and Section Cues:** If your data includes format information
  (e.g. HTML tags in an ePub, or PDF layout coordinates), use that.
  Chapter introductions or sidebars might be marked with headings like
  “Tips,” “Chef’s Note,” or different styling. Even without explicit
  tags, the position can be a clue: text that appears at the start of a
  chapter or right before a recipe might be a general note about the
  upcoming recipes. Utilizing these cues can boost accuracy (for
  example, if a paragraph precedes an ingredient list without being part
  of the recipe instructions, it might be an editorial blurb or a
  general tip). In essence, **the more cookbook-specific heuristics you
  encode (and refine over time), the better the baseline extraction will
  perform** before bringing in heavier tools.

## Distinguishing General Tips from Recipe-Specific Notes

After isolating non-recipe text segments, the next step is classifying
them as **general-purpose cooking knowledge vs. recipe-specific notes**.
This can be tricky, but a few strategies can help:

- **Lexical and Context Clues:** General tips often use generic language
  (talking about ingredients or techniques in general) and **avoid
  referencing the specific dish** at hand. If a note contains phrases
  like “this dish,” the name of the recipe, or a unique ingredient only
  used in that recipe, it’s likely a recipe-specific note. Conversely,
  statements that **make general recommendations** (“Rest the meat
  before carving,” “Whole spices stay fresh longer than ground ones”) or
  explain *why* a technique matters tend to be broader knowledge. You
  can implement simple checks – for example, maintain a list of the
  current recipe’s key ingredients or title, and flag any note that
  mentions those specifically as “recipe-specific.” Also look for
  pronouns or context: a sentence like “This **will** ensure the sauce
  thickens properly” – “this” likely refers to a step in the same recipe
  (specific context), whereas “Ensuring the sauce thickens properly
  **requires a gentle simmer**” is phrased as a general principle.
- **Length and Detail:** Short notes that directly address ingredient
  substitutions or minor variations (often just one or two sentences)
  are frequently recipe-specific tips. In contrast, longer paragraphs
  that delve into technique or food science (e.g. explaining why
  *scrambled eggs can turn out fluffy vs. dense* and how to control
  that) are likely intended as general culinary knowledge sections. Your
  parser could use a **length threshold or the presence of explanatory
  keywords** (“because,” “in order to,” “best way,” etc.) to guess if
  something is a broader explanation.
- **Placement and Grouping:** Consider the placement of the note
  relative to the recipe. Many cookbooks include a brief introduction
  before each recipe – sometimes this includes both anecdotal context
  and a cooking tip for that recipe. These intros might be better
  attached to the recipe itself rather than treated as global knowledge.
  Meanwhile, a section at the start of a chapter like *“Grilling Tips:
  How to Manage Heat”* is clearly general. By analyzing where the text
  lies (e.g. immediately preceding a recipe’s ingredient list versus as
  a standalone section), you can infer its scope. As a rule of thumb,
  *text embedded within or immediately around a single recipe is more
  likely context-specific*, whereas *text in dedicated sections is more
  likely general advice*.
- **Iterative Refinement:** It’s expected that your initial rules will
  sometimes misclassify these notes. Treat this as an **iterative
  process**. Each time you parse a new cookbook, review the extracted
  “general tips” vs “recipe notes” and adjust your heuristics. Over
  time, you’ll build a collection of edge-case patterns. For example,
  you might discover many books use italicized paragraphs as side tips –
  then you could adjust your parser to catch italic markers from the raw
  text extraction. Since this is a personal project, it’s fine to handle
  things in a somewhat “janky” but pragmatic way: incorporate new rules
  as you encounter new formats. This pragmatic evolution is often how
  robust parsers are built in practice.

## Machine Learning Approaches for Text Segmentation

While heuristics are powerful, some distinctions may be too subtle or
varied across 300 cookbooks for pure rule-based logic. Introducing an
**ML model for text classification** can improve accuracy by learning
those nuances. A few approaches to consider:

- **Supervised Text Classification:** If you can compile a small labeled
  dataset of text segments (e.g. annotate a few cookbooks’ paragraphs as
  “recipe instruction,” “recipe-specific note,” or “general
  tip/knowledge”), you could train a classifier. Modern NLP models like
  BERT or DistilBERT can be fine-tuned on such data to recognize the
  differences in language. Even a simpler model (like logistic
  regression on TF-IDF features) might do surprisingly well for a first
  cut, given the vocabulary differences – for example, recipe
  instructions often contain action verbs and quantities, whereas tips
  might contain more adjectives or explanatory conjunctions. The
  downside is the need for labeled data; with hundreds of books, manual
  labeling is tedious. However, you might not need a lot – even a few
  hundred example snippets could be enough to fine-tune a classifier to
  a useful degree.
- **Weak Supervision:** An alternative is to use **weak supervision**
  techniques (like Snorkel-style labeling functions) to programmatically
  label data for training. You could write a set of simple heuristic
  checks (some of the ones discussed above) as labeling functions on
  text segments, each voting whether a segment seems general or specific
  or recipe text. These heuristic labels will be noisy, but you can feed
  them into a weak supervision framework to train a model that
  generalizes beyond the initial
  rules[\[4\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC5951191/#:~:text=Snorkel%3A%20Rapid%20Training%20Data%20Creation,such%20as%20patterns%2C%20heuristics%2C).
  The advantage is you leverage the rules you already suspect without
  needing ground-truth labels for everything. Over time, the model might
  learn deeper linguistic patterns of what constitutes a tip.
- **Zero-Shot Classification:** If creating a training set is
  impractical, consider using a **zero-shot classifier** with a
  pre-trained language model. Zero-shot classification uses a model
  (often one trained on natural language inference) to categorize text
  into user-defined labels without explicit training on those labels.
  For instance, you can take a model like *Facebook’s BART-large MNLI*
  and ask it whether a given text is about “Recipe Instruction,”
  “Specific Recipe Note,” or “General Cooking Tip.” The model has never
  seen those categories during training, but it leverages its broad
  language understanding to predict which label fits best. This approach
  is valuable when labeling data is
  costly[\[5\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=The%20term%20%E2%80%9CZero,new%20categories%20not%20previously%20seen).
  In practice, you would provide the segment text and a list of
  candidate labels or descriptions (even phrased as hypotheses, e.g.
  “This text is a general cooking tip.”), and the model will score each
  label[\[6\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=from%20transformers%20import%20pipeline)[\[7\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=).
  Many libraries (like Hugging Face Transformers) make this easy to try.
  Zero-shot models won’t be perfect, but they can give you a quick way
  to classify segments with no training – and you can then review and
  correct results to progressively improve your pipeline.
- **Clustering and Topic Modeling (Unsupervised):** As a supplementary
  tactic, you could use unsupervised methods to see if “tip” content
  clusters separately from recipe content. For example, vectorize all
  paragraphs from a cookbook (using embeddings) and run a clustering
  algorithm. You might find clusters where one corresponds to
  instructions (rich in verbs like *mix, bake, serve*), another to
  ingredients (lots of food nouns, units), and another to explanatory
  prose (more descriptive language, perhaps past tense or generic
  statements). Topic modeling (like LDA) might similarly find a topic
  for “general advice” characterized by words like *tips, always, best,
  avoid, should*. This isn’t a direct solution, but it could help
  **identify candidate segments** that look out-of-place from the main
  recipe clusters. Those candidates could then be manually checked or
  fed to a classifier. Essentially, unsupervised techniques can act as a
  discovery tool for hidden patterns or as a way to flag potential
  knowledge sections that your rules missed.

Keep in mind that any ML model’s predictions can be integrated with your
rules. For example, you might use a classifier to get a probability that
a segment is a general tip, and only accept it as such if the confidence
is high (low-confidence cases can be handed off to the LLM or a manual
review step). This **combination of rules + ML** often yields better
precision, as the model handles fuzzy cases while the rules handle the
straightforward ones.

## Hybrid Pipeline: Combining Rules with LLM Assistance

Given your plan to incorporate an LLM for the hardest cases, a **hybrid
approach** is very sensible. In fact, recent work in information
extraction has shown that combining rule-based methods with an LLM leads
to both accuracy and efficiency. For example, one two-step approach on
legal text first used **rules/regex + spaCy** to snag obvious structured
pieces, then applied GPT-3.5 to the selected segments for context-aware
extraction[\[8\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=To%20answer%20the%20research%20question%2C,detect%20patterns%20in%20money%20references)[\[9\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=,the%20other%20three%20features%20that).
The rule-based layer excels at catching patterns with certainty,
drastically narrowing down the text that the LLM needs to analyze. Then
the LLM shines by interpreting context and extracting details that rules
might miss, all on a much smaller text portion – saving time and API
cost. You can apply the same idea in your recipe pipeline:

1.  **Rule-Based Candidate Selection:** Use your local algorithm to
    parse recipes and pull out any text that is *likely* a tip or note.
    Even if this includes some false positives, the goal is high recall
    at this stage (don’t miss potential tips). For instance, you might
    select any standalone paragraph outside ingredient/instruction
    sections as a “candidate knowledge blurb.” You might also
    intentionally grab borderline cases – e.g. a sentence in the middle
    of instructions that contains a keyword like “tip” or “note” could
    be flagged for LLM review rather than either dropping or keeping it
    blindly.
2.  **LLM Classification or Extraction:** Once you have these
    candidates, pass them through an LLM to make the final call or to
    extract the useful content. Since you plan to do this only for
    low-confidence or tricky parts, the volume should be manageable. You
    could prompt an LLM (like GPT-4 or an instruction-tuned model) with
    something like: *“Identify if the following text is a general
    cooking tip/knowledge, a recipe-specific note, or unrelated. If it’s
    a general tip, paraphrase it concisely; if recipe-specific, label it
    as such.”* The LLM’s strength is understanding nuance – it can use
    context clues that your code might not, such as subtle wording that
    implies general applicability. By reviewing the LLM’s output, you
    can then decide to include the tip in your knowledge database or
    attach the note to a specific recipe entry.
3.  **Local or Smaller Models:** If API cost is a concern, you might
    explore running a **small LLM locally** for this classification
    task. Models in the 7–13B parameter range (like LLaMA 2 7B chat, or
    other GPT-3.5-level open models) can often handle classification or
    short extractions when given a well-crafted prompt. There are
    libraries (e.g. `transformers` with
    `pipeline("text-classification")` or LangChain with local LLM
    wrappers) that enable this. The DZone smart kitchen app example
    shows using a LLaMA 3.1 8B model via an API to extract structured
    info from commands, outputting JSON with specific
    fields[\[10\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=method%3A%20,include%20any%20explanation%20or%20extra)[\[11\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=This%20code%20defines%20a%20POST,structured%20data%20in%20JSON%20format)
    – a similar approach could be used to extract “tip text” from a blob
    or to label a snippet as a tip. Running a model locally might
    require a decent GPU or using quantized models, but it can eliminate
    ongoing costs. Alternatively, use the API only for final
    verification: for example, run all your candidates through a local
    model or heuristic filter, and then maybe only double-check the
    borderline ones with a high-accuracy API call (GPT-4) to be really
    sure.
4.  **Schema-Guided Extraction:** Another powerful LLM-assisted method
    is to define a **schema** for what you want to extract and let the
    model fill it in. For instance, you can ask the LLM to output JSON
    with fields like `"recipe_name": ...`, `"general_tips": [...]`,
    `"recipe_specific_notes": [...]`. Google’s **LangExtract** library
    is designed for this kind of use-case – you specify Pydantic models
    for your data (e.g., a Recipe model and maybe a Tip model) and
    provide a few examples, and the LLM will parse any input text
    accordingly[\[12\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=The%20beauty%20of%20LangExtract%20is,what%20you%20need%20in%20a).
    The beauty of such an approach is that the LLM truly **understands
    context and structure**, so it can extract exactly what you need
    without you hard-coding rules for every edge case. As one user
    noted, *you don’t have to write brittle parsers; an LLM-powered
    extractor “actually understands the content” and can handle
    unconventional
    formats*[\[13\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=LangExtract%20has%20completely%20changed%20how,that%20actually%20understand%20the%20content).
    In your scenario, you could feed an entire recipe chapter to such a
    system and have it return all the recipes and all the general tips
    in structured form. The downside, of course, is token limits and
    cost – entire cookbooks are long, so you would need to chunk the
    input (e.g. process chapter by chapter or 10 pages at a
    time)[\[14\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=1,gave%20LangExtract%20some%20poorly%20formatted).
    Nonetheless, this approach could dramatically improve recall of
    those “longer pieces of knowledge” that your current parser misses,
    because the LLM won’t be fooled by odd phrasing or placement – it
    will pick up that a paragraph is explaining *why slow cooking yields
    tender meat*, even if there’s no explicit label on that paragraph. A
    pragmatic approach might be: use your local parser to get 80% of the
    easy stuff, and for a particularly important cookbook (or one with
    lots of hidden gems of knowledge), run it through an LLM extractor
    to catch what was missed. You can then incorporate those results
    back into your database.

In summary, the hybrid pipeline ensures you **do as much as possible on
your machine** (fast and free) and lean on LLMs only when necessary.
This targeted use of AI – rules for well-structured patterns, and AI for
context-heavy judgments – is a best practice to balance efficiency and
accuracy[\[9\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=,the%20other%20three%20features%20that).
By configuring confidence thresholds (for example, if a heuristic or ML
classifier isn’t ~90% sure about a segment), you can funnel just the
uncertain cases to the LLM, thereby controlling costs.

## Tools and Libraries to Consider

To implement the above strategies, here are some **practical tools and
resources** that can help improve your importer pipeline:

- **Document Parsing and OCR:** If your cookbooks are in PDF or image
  form, ensure you use a reliable PDF text extractor or OCR. Tools like
  **PyMuPDF (fitz)** or **PDFMiner** can extract text along with layout
  information. For OCR of scanned pages, **Tesseract** or AWS/Azure OCR
  services could be used. Preserving basic layout (line breaks,
  headings) can assist in later identifying recipe titles and sections.
- **Recipe Parsers:** You already noted many exist. For web formats
  (HTML/Word), libraries like `recipe-scrapers` (for scraping recipe
  sites) or schema-based extractors might not directly apply to
  free-form text, but they illustrate common patterns. Since you have
  recipe parsing mostly working, continue leveraging those patterns.
  Also, libraries like **Ingredient Parser** (`ingredient-parser` in
  Python[\[15\]](https://ingredient-parser.readthedocs.io/#:~:text=Ingredient%20Parser%20documentation%20%E2%80%94%20Ingredient,How%20to%20achieve))
  or similar can reliably split quantity, unit, and ingredient name – it
  sounds like you’re using something along these lines and that’s a
  great practice (outsourcing ingredient syntax handling to a proven
  library).
- **SpaCy NLP:** SpaCy is a powerful library that can be handy in
  multiple ways. You can use its **rule-based Matcher** to find phrases
  (e.g. a pattern for “if you don’t have X” to catch substitution
  notes). SpaCy’s part-of-speech tagging might help differentiate an
  instruction (often starts with a verb imperative) versus a statement.
  It even has an **entity ruler** which you could customize to tag
  cooking terms or ingredients as entities. There’s also spaCy’s
  **TextCategorizer** component which you could train with a few
  examples of “tip” vs “non-tip” text if you decide to do a small ML
  model. SpaCy pipelines are efficient in pure Python and can handle
  fairly large volumes of text.
- **Machine Learning Frameworks:** If you go the route of training a
  classifier, libraries like **scikit-learn** (for simpler models) or
  **Hugging Face Transformers** (for fine-tuning BERT or using zero-shot
  models) will be useful. Hugging Face’s `transformers` library in
  particular gives you easy access to models like BERT, RoBERTa, etc.,
  and even the zero-shot pipeline shown earlier. For example, the
  zero-shot pipeline with `bart-large-mnli` can be invoked in a few
  lines of
  code[\[6\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=from%20transformers%20import%20pipeline).
  This can be integrated into your importer to auto-tag segments.
- **Google’s LangExtract (and Similar Tools):** LangExtract is a
  high-level extraction library that uses Google’s LLMs under the
  hood[\[16\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=match%20at%20L79%20The%20beauty,what%20you%20need%20in%20a).
  If you have access to it (and don’t mind using the API), it could
  significantly simplify the problem – you’d describe a schema like
  “CookbookImport” with fields for recipes and tips, and provide a few
  annotated examples from one cookbook, and the model might generalize
  to others. It’s essentially a form of prompt-based extraction using
  Pydantic for output format. Another similar approach without that
  library is to use **OpenAI function calling or JSON output
  formatting** with GPT-4, where you ask the model to output structured
  JSON of the content. This is a bit more manual but can be done with
  careful prompting. Keep in mind, these heavy LLM approaches are likely
  overkill for every single cookbook due to cost, but you could use them
  selectively on portions of data where your regular pipeline has low
  confidence.
- **Open-Source LLMs:** If you want to stay entirely offline, you can
  explore open-source language models. **GPT4All**, **Llama 2**, or
  **Falcon** models (especially fine-tuned variants) can run on a decent
  PC with CPU/GPU. They can be used for tasks like classification or
  even moderate-length extraction. Libraries like **LangChain** or
  **LLM-index (LlamaIndex)** allow you to do retrieval augmented
  generation, which could be interesting if you index your cookbooks –
  but that’s more for querying later rather than the import itself. For
  the import, an instruct model you can prompt programmatically might
  suffice (e.g., “Read the following text and extract any general
  cooking tips mentioned”). The quality won’t match GPT-4, but it might
  be good enough with iteration. The DZone example we saw demonstrates
  calling a LLaMA 8B instruct model to extract structured info via an
  API[\[10\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=method%3A%20,include%20any%20explanation%20or%20extra)[\[11\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=This%20code%20defines%20a%20POST,structured%20data%20in%20JSON%20format).
  You can mirror this locally using the same model weights with
  something like HuggingFace’s `transformers` or llama.cpp.
- **Testing and Validation Tools:** Since this is a personal project,
  you’ll be both developer and QA. It might help to maintain some test
  files or excerpts where you *know* the correct output, to verify that
  changes in your pipeline don’t break earlier successes. Simple scripts
  to highlight or log what the parser classifies as “tip” can let you
  quickly eyeball if it’s grabbing nonsense. Over time, building a small
  “golden set” of a few pages with tricky formatting and ensuring your
  pipeline handles them will give you confidence as you add more
  cookbooks to the mix.

## Practical Tips for Implementation

Finally, here are some **best-practice tips** to guide the development
of your improved importer:

- **Start Simple, Then Iterate:** It’s tempting to over-engineer
  upfront, but you already have something working “okay.” Gradually
  layer in improvements. For instance, implement a basic classification
  of tips vs. recipe-notes with a few keyword rules and see how much it
  improves output. Then maybe add a zero-shot classifier to catch the
  rest. By comparing results cookbook by cookbook, you’ll learn where
  the biggest gaps are.
- **High Recall, Then Precision:** When extracting tips/knowledge, it’s
  often better to err on the side of capturing too much (high recall)
  and then filtering out the false positives, rather than missing useful
  info. It’s easier to throw away a wrongly picked “tip” than to recover
  one you never captured. Your pipeline could mark each extracted tip
  with a confidence or source (rule X vs. ML vs. LLM) so you have
  traceability. You might choose to manually review low-confidence ones
  later.
- **Leverage Cookbook Structure Variety:** Since you have ~300
  cookbooks, you’ll encounter a lot of formatting styles. Pay attention
  to any consistent signals in each book (some use certain symbols or
  layouts for tips). You can create cookbook-specific overrides if
  needed (e.g. “if cookbook title contains X, use this set of parsing
  rules”). It doesn’t need to be elegant; even a hardcoded tweak for a
  particular series of books is fine if it saves time – you’re not
  building a commercial product, so maintainability for one user (you)
  is manageable.
- **Use Logging and Debugging:** Incorporate verbose logging in your
  importer when running it on new data. For example, log all paragraphs
  classified as tips, and perhaps which rule or model made that
  decision. This will help you quickly spot “Why on earth did it grab
  this line?” and refine the logic. Sometimes a rule might be too broad
  (e.g. catching any sentence with “if” as a tip – you’d see lots of
  false positives and realize you need to narrow it). Good logging is
  invaluable in a project like this, where the data is unstructured and
  varied.
- **Memory and Performance:** Parsing 300 cookbooks could be heavy. Make
  sure to handle one at a time or in chunks to avoid running out of
  memory. Also, if using ML models, batch your predictions where
  possible (e.g. classify paragraphs in bulk instead of one by one) to
  speed it up. If using an LLM API, group multiple small snippets into
  one prompt if that’s more cost-effective (just ensure the prompt stays
  under token limits and the model can separate them).
- **Future LLM Integration:** You mentioned eventually building an LLM
  pipeline for hard cases. As you design your data structures now,
  imagine how you’ll incorporate the LLM later. For instance, you might
  design the output of your current pipeline to include a field like
  `confidence` or `needs_llm_review`. That way, switching on an LLM step
  is as easy as filtering those entries and sending them to the LLM.
  Also consider keeping **references to source (cookbook name, page
  number)** for each extracted tip – if an LLM later needs more context
  to decide something, having the surrounding text or at least knowing
  where to look in the original can help.

By combining these techniques – structured parsing rules, intelligent
text classification, and targeted LLM usage – you’ll create a much more
robust import pipeline. This hybrid strategy is a **best practice for
complex text extraction**: use fast deterministic methods where you can,
and apply AI understanding where you must. It mirrors how a human might
approach the task (first flipping through pages to separate recipes from
prose, then reading ambiguous parts carefully to decide what kind of
information it is). As you implement these, you’ll likely find your
pipeline becomes both **more accurate and more adaptable** to the
diverse content in different cookbooks. Good luck with your project, and
enjoy the process of seeing your digital recipe database grow smarter!

## Sources

- Bui, D.D.A. et al. *“PDF text classification to leverage information
  extraction from publication reports.”* J. Biomed. Inform. 61 (2016):
  141–148. (Describes a rule-based multi-pass approach outperforming ML
  for segmenting mixed text in PDF
  documents)[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=The%20multi,%28p%3D0.005)[\[3\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=Conclusions).
- Nan, H. et al. *“Combining Rule-Based and Machine Learning Methods for
  Information Extraction.”* (2023). (Illustrates a hybrid pipeline:
  regex/spaCy to identify candidates, then GPT-3.5 for context-aware
  extraction)[\[8\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=To%20answer%20the%20research%20question%2C,detect%20patterns%20in%20money%20references)[\[9\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=,the%20other%20three%20features%20that).
- Chandrasekaran, A. *“How I Built a Recipe Parser That Actually Works
  Using Google’s LangExtract.”* Medium, 2025. (Introduces Google’s
  LangExtract library, which uses LLMs to parse text into structured
  data with minimal manual
  rules)[\[12\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=The%20beauty%20of%20LangExtract%20is,what%20you%20need%20in%20a)[\[13\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=LangExtract%20has%20completely%20changed%20how,that%20actually%20understand%20the%20content).
- Yali, A.S. *“Zero-Shot Text Classification.”* Medium, 2023. (Explains
  zero-shot classification using NLI-based models and why it’s useful
  when labeled data is
  scarce)[\[5\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=The%20term%20%E2%80%9CZero,new%20categories%20not%20previously%20seen)[\[6\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=from%20transformers%20import%20pipeline).

------------------------------------------------------------------------

[\[1\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=an%20important%20and%20common%20extraction,strategic%20use%20by%20IE%20systems)
[\[2\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=The%20multi,%28p%3D0.005)
[\[3\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/#:~:text=Conclusions)
PDF text classification to leverage information extraction from
publication reports - PMC

<https://pmc.ncbi.nlm.nih.gov/articles/PMC4893911/>

[\[4\]](https://pmc.ncbi.nlm.nih.gov/articles/PMC5951191/#:~:text=Snorkel%3A%20Rapid%20Training%20Data%20Creation,such%20as%20patterns%2C%20heuristics%2C)
Snorkel: Rapid Training Data Creation with Weak Supervision - PMC

<https://pmc.ncbi.nlm.nih.gov/articles/PMC5951191/>

[\[5\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=The%20term%20%E2%80%9CZero,new%20categories%20not%20previously%20seen)
[\[6\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=from%20transformers%20import%20pipeline)
[\[7\]](https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005#:~:text=)
Zero-Shot Text Classification. Discover how Zero-Shot Learning enables…
\| by Yali - Dev \| Medium

<https://medium.com/@asanchezyali/zero-shot-text-classification-c737db000005>

[\[8\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=To%20answer%20the%20research%20question%2C,detect%20patterns%20in%20money%20references)
[\[9\]](https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf#:~:text=,the%20other%20three%20features%20that)
wooverheid.nl

<https://wooverheid.nl/wp-content/uploads/2024/10/faia-395-faia241262.pdf>

[\[10\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=method%3A%20,include%20any%20explanation%20or%20extra)
[\[11\]](https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app#:~:text=This%20code%20defines%20a%20POST,structured%20data%20in%20JSON%20format)
Building a Voice-Powered Smart Kitchen App

<https://dzone.com/articles/building-a-voice-powered-smart-kitchen-app>

[\[12\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=The%20beauty%20of%20LangExtract%20is,what%20you%20need%20in%20a)
[\[13\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=LangExtract%20has%20completely%20changed%20how,that%20actually%20understand%20the%20content)
[\[14\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=1,gave%20LangExtract%20some%20poorly%20formatted)
[\[16\]](https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3#:~:text=match%20at%20L79%20The%20beauty,what%20you%20need%20in%20a)
How I Built a Recipe Parser That Actually Works Using Google’s
LangExtract \| by Aswin Chandrasekaran \| Artificial Intelligence in
Plain English

<https://ai.plainenglish.io/how-i-built-a-recipe-parser-that-actually-works-using-googles-langextract-6252ef808635?gi=3dfefa79b6c3>

[\[15\]](https://ingredient-parser.readthedocs.io/#:~:text=Ingredient%20Parser%20documentation%20%E2%80%94%20Ingredient,How%20to%20achieve)
Ingredient Parser documentation — Ingredient Parser 2.4.0

<https://ingredient-parser.readthedocs.io/>
