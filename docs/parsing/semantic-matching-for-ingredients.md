# Semantic Matching for Ingredient-to-Step Assignment

## The Problem

Current ingredient matching uses exact token matching: if the instruction says "Add the dough", it won't match an ingredient named "All-Butter Pie Dough" because "dough" alone doesn't appear as a token in the ingredient name (it's part of "Pie Dough").

Similarly, if an instruction says "on a well-floured board", it won't match "Flour for rolling" because "floured" ≠ "flour".

## What is Semantic Matching?

Semantic matching uses meaning/similarity rather than exact text matching. Two approaches:

### 1. Embedding-based Similarity

Use a sentence/word embedding model to convert text to vectors, then compare similarity:

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

# Embed ingredient and instruction text
ing_embedding = model.encode("All-Butter Pie Dough")
instr_embedding = model.encode("Roll out the chilled dough")

# Cosine similarity (0-1, higher = more similar)
similarity = cosine_similarity(ing_embedding, instr_embedding)
if similarity > 0.5:
    # Match!
```

**Pros**: Catches synonyms, related terms, different word forms
**Cons**: Requires ML model (adds dependency, ~100MB+), slower

### 2. Lemmatization + WordNet

Simpler approach using linguistic tools:

```python
import nltk
from nltk.stem import WordNetLemmatizer
from nltk.corpus import wordnet

lemmatizer = WordNetLemmatizer()

# "floured" -> "flour", "dough" -> "dough"
lemmatizer.lemmatize("floured", pos='v')  # -> "flour"

# Check if words are related via WordNet synsets
def are_related(word1, word2):
    synsets1 = wordnet.synsets(word1)
    synsets2 = wordnet.synsets(word2)
    for s1 in synsets1:
        for s2 in synsets2:
            if s1.wup_similarity(s2) > 0.8:
                return True
    return False
```

**Pros**: Lightweight, handles word forms (flour/floured), no ML model needed
**Cons**: Misses context-dependent matches, limited vocabulary

## Recommended Approach for This Project

**Start with lemmatization** since it's lightweight and handles the common cases:

1. Add `nltk` dependency
2. Lemmatize both ingredient names and instruction text before matching
3. "floured" → "flour" will now match "Flour for rolling"
4. "dough" in "chilled dough" will match "Pie Dough"

If that's insufficient, consider embedding-based matching as a fallback for unassigned ingredients only (to minimize performance impact).

## Where to Integrate

In `cookimport/parsing/step_ingredients.py`:

1. `_tokenize()` - add lemmatization step
2. `_build_aliases()` - generate lemmatized aliases alongside current ones
3. Consider a two-pass approach: exact match first, then semantic match for remaining

## Libraries to Research

- **NLTK**: `pip install nltk` - WordNet, lemmatization
- **spaCy**: `pip install spacy` - faster lemmatization, better NER
- **sentence-transformers**: `pip install sentence-transformers` - embeddings
- **rapidfuzz**: `pip install rapidfuzz` - fuzzy string matching (middle ground)



### SOME FEEDBACK

Your plan is heading in the right direction: add a “cheap” normalization layer first, then only spend heavier compute (embeddings) to rescue the leftovers. That matches how your current step-linker is already structured (aliases + context scoring + weak-match filtering).  

## What I’d change / clarify in the plan

### 1) Reframe it as “augment aliasing + scoring,” not a separate matcher

In **AI_Context.md**, the step linker already scans steps using **multiple aliases** and uses **context/verb signals** + weak-match filtering. 
So “semantic matching” should slot in as:

* better **normalization** for `_tokenize()` and alias generation, and/or
* an additional **scoring feature** used only when lexical signals are weak.

This keeps your current precision guardrails instead of bypassing them.

### 2) Don’t lean too hard on WordNet “semantic similarity” (synsets) for this domain

WordNet can help with **morphology** (“floured” → “flour”), but WordNet synset similarity (like Wu–Palmer) is:

* slow-ish at scale,
* sense-ambiguous,
* and often weak on culinary-specific vocabulary.

I’d keep WordNet mainly for lemmatization (or skip WordNet entirely if you adopt a different lemmatizer) and treat “semantic similarity via synsets” as optional.

### 3) Add explicit false-positive guardrails (you’ll need them more after lemmatization/embeddings)

Once you make matching more flexible, you’ll accidentally match generic stuff more often (e.g., “dough”, “mixture”, “sauce”, “batter”, “season”). Your current design already mentions weak-match filtering. 
I’d add to the plan:

* a small **generic-token list** (domain stopwords) that gets down-weighted unless accompanied by a strong “use” verb context
* a **minimum-evidence rule** for semantic-only matches (e.g., must have a nearby use verb *or* a strong lexical partial hit)

### 4) Tighten how embeddings are applied (otherwise they’ll be noisy)

Your embedding sketch compares “ingredient name” vs “full instruction sentence” with a fixed threshold. 
That often works, but it’s also where you’ll get weird matches because the instruction contains lots of unrelated context.

Better pattern:

* candidate generation stays lexical (including lemmatized tokens)
* embeddings are only used on **short spans** (e.g., noun phrases after “add/stir/fold in”, or a sliding window) and only for **unassigned** ingredients, which your plan already suggests. 

### 5) Add an evaluation + debugging loop to the plan

You already have **Label Studiond truth workflows. 
Make semantic matching measurable by adding:

* a small labeled set focused specifically on “ingredient ↔ step” links
* metrics: precision/recall, plus “% ingredients left unassigned”
* debug artifacts: for each assigned ingredient, log *why* (feature hits + score breakdown)

## What I’d add to the plan (concrete checklist)

1. **Normalization pipeline** (both ingredients + steps)

* lowercase + unicode normalize
* split hyphens/slashes (“all-butter” → “all”, “butter”)
* strip parentheticals and common prep phrases (“finely chopped”, “for serving”) into a separate field if you have it
* lemmatize (details below)

2. **Alias generation improvements**
   Use what you already parse as the ingredient “item” text (your ingreddient_text`, etc.). 
   Then generate aliases like:

* full cleaned phrase
* head noun phrase
* lemma-token variants
* curated synonym expansions (see below)

3. **Scoring additions (incremental)**

* * lexical exact/phrase matches
* * lemma token overlap
* * fuzzy score (only if lexical overlap is close)
* * embedding score (only for leftovers, and only if you can constrain the compared span)

4. **Safety rails**

* generic token down-weighting
* require use-verb proximity for low-specificity matches
* “margin rule”: if top two candidate steps are close, prefer “unassigned” over guessing (or keep as ambiguous for review)

## Open-source building blocks you can lean on

### Lemmatization / morphology

* **NLTK**: `WordNetLemmatizer` is simple and documented (note POS matters). ([nltk.org][1])
* **spaCy**: has a dedicated lemmatizer component; rule-based modes may require POS tagging, but there are lookup-based options and `spacy-lookups-data` to keep things lighter. ([spacy.io][2])
* **LemmInflect**: dictionary-based lemmatization + OOV handling; can be standalone or integrate with spaCy. ([PyPI][3])

If you want “floured → flour” reliably without building a full POS pipeline, **LemmInflect** or a spaCy lookup lemmatizer is often less fiddly than NLTK+POS wiring.

### Fuzzy matching (cheap middle ground)

* **RapidFuzz**: fast, actively maintained, MIT licensed; includes efficient batch scoring (`cdist`) which is handy if you’re scoring many ingredient↔step pairs. ([GitHub][4])

### Embeddings (semantic fallback)

* **Sentence Transformers**: the go-to for local embeddings; supports `SentenceTransformer("all-MiniLM-L6-v2")` exactly like your sketch. ([GitHub][5])

### Vector search / ANN (only if you scale beyond “one recipe at a time”)

If later you want a persistent ingredient synonym index, ingredient KB, or corpus-wide retrieval:

* **FAISS** for fast similarity search. ([GitHub][6])
* **hnswlib** for efficient ANN indexes. ([GitHub][7])
* **Annoy** for memory-mapped, simple indexes. ([GitHub][8])

For *in-recipe* matching (dozens of ingredients/steps), you probably don’t need ANN—simple matrix cosine similarities are plenty.

### Domain vocabulary (optional but powerful)

* **FoodOn**: an open-source food ontology you can mine for synonym-like relationships / canonical naming (even if you only extract a small curated subset). ([GitHub][9])

In practice, a **small curated synonym map** gets you a lot:

* scallions ↔ green onions
* confectioners’ sugar ↔ icing sugar ↔ powdered sugar
* baking soda ↔ bicarbonate of soda
* cilantro ↔ coriander (leaf) *(careful with “coriander” seed in some regions)*

## A pragmatic “no-reinventing” implementation order

1. Add **lemmatization in `_tokenize()`** as (exactly as your plan proposes). 
2. Add **RapidFuzz** as a *rescuer* for near-misses (only if lemma overlap is non-zero). ([GitHub][4])
3. Add a **curated synonym map** (tiny, test-driven).
4. Add **Sentence Transformers** as the last fallback for *unassigned ingredients only*, but compare against constrained spans (verb-object phrases) rather than whole s ([GitHub][5])
5. Use **Label Studio** to measure whether recall improves without blowing up precision. 

If you want, paste (or uploaents.py` matching/alias code and I’ll suggest *exactly* where to splice in lemma/fuzzy/embedding signals with minimal churn.

[1]: https://www.nltk.org/api/nltk.stem.wordnet.html?utm_source=chatgpt.com "NLTK :: nltk.stem.wordnet module"
[2]: https://spacy.io/api/lemmatizer/?utm_source=chatgpt.com "Lemmatizer · spaCy API Documentation"
[3]: https://pypi.org/project/lemminflect/?utm_source=chatgpt.com "lemminflect · PyPI"
[4]: https://github.com/rapidfuzz/RapidFuzz?utm_source=chatgpt.com "GitHub - rapidfuzz/RapidFuzz: Rapid fuzzy string matching in Python using various string metrics"
[5]: https://github.com/UKPLab/sentence-transformers?utm_source=chatgpt.com "GitHub - huggingface/sentence-transformers: State-of-the-Art Text Embeddings"
[6]: https://github.com/facebookresearch/faiss?utm_source=chatgpt.com "GitHub - facebookresearch/faiss: A library for efficient similarity search and clustering of dense vectors."
[7]: https://github.com/nmslib/hnswlib?utm_source=chatgpt.com "GitHub - nmslib/hnswlib: Header-only C++/python library for fast approximate nearest neighbors"
[8]: https://github.com/spotify/annoy?utm_source=chatgpt.com "GitHub - spotify/annoy: Approximate Nearest Neighbors in C++/Python optimized for memory usage and loading/saving to disk"
[9]: https://github.com/FoodOntology/foodon?utm_source=chatgpt.com "GitHub - FoodOntology/foodon: The core repository for the FOODON food ontology project. This holds the key classes of the ontology; larger files and the results of text-mining projects will be stored in other repos."
