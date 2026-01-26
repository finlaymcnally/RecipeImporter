---
summary: "ExecPlan for ML-based text classification (zero-shot, weak supervision) as alternatives to pure heuristics."
read_when:
  - When heuristics fail to achieve adequate tip/recipe classification accuracy
  - When considering ML augmentation of the parsing pipeline
---

# ML Text Classification ExecPlan

This ExecPlan is a placeholder for future ML-based text classification approaches. It captures research ideas from Improving_Recipe_Import_Pipeline.md that go beyond pure heuristics but don't require full LLM calls.

## Purpose / Big Picture

When deterministic heuristics cannot reliably classify text segments (tip vs recipe-note vs instruction vs headnote), lightweight ML models may bridge the gap before escalating to expensive LLM calls. This plan captures potential approaches.

## Progress

- [ ] Initial ExecPlan drafted.
- [ ] (Future) Evaluate zero-shot classification on sample cookbook data.
- [ ] (Future) Implement if accuracy gains justify complexity.

## Approaches to Consider

### 1. Zero-Shot Classification

Use pre-trained NLI models without labeled training data.

**How it works:**
- Feed text segment + candidate labels to model (e.g., BART-large-MNLI)
- Model scores each label based on language understanding
- No training required—just inference

**Example (Hugging Face):**
```python
from transformers import pipeline
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")
result = classifier(
    "Remove eggs from pan just before they finish cooking.",
    candidate_labels=["general cooking tip", "recipe instruction", "recipe-specific note"]
)
```

**Pros:** No labeled data needed, quick to try.
**Cons:** Lower accuracy than fine-tuned models, slower than heuristics.

### 2. Weak Supervision (Snorkel-style)

Train a model using noisy heuristic labels instead of manual annotations.

**How it works:**
- Define labeling functions (existing heuristics) that vote on each segment
- Combine noisy votes into probabilistic labels
- Train a downstream model on these soft labels

**Pros:** Leverages existing rules, generalizes beyond individual heuristics.
**Cons:** Requires setup complexity, may inherit rule biases.

### 3. Simple Supervised Classifier

If a small labeled dataset can be created, train a lightweight classifier.

**Options:**
- TF-IDF + Logistic Regression (fast, interpretable)
- DistilBERT fine-tuned on ~100-500 labeled examples

**Pros:** High accuracy if labels are good.
**Cons:** Requires manual labeling effort.

### 4. Clustering / Topic Modeling (Discovery)

Use unsupervised methods to find patterns, not classify directly.

**How it works:**
- Vectorize paragraphs using embeddings
- Cluster to find instruction-like vs explanatory-like groups
- Use clusters to identify candidates for manual review

**Pros:** Can discover patterns rules missed.
**Cons:** Not a direct classifier—a discovery tool.

## Decision Log

- Decision: Create placeholder plan rather than implement immediately.
  Rationale: Heuristics are working acceptably; ML should only be added if accuracy problems emerge. Keep research documented for future reference.
  Date/Author: 2026-01-24 / Agent

## Integration Strategy

If implemented, ML classification would slot in as:
1. **After heuristics, before LLM:** Use ML to classify low-confidence heuristic results
2. **Confidence gating:** Only escalate to LLM if ML confidence is also low
3. **Hybrid voting:** Combine heuristic + ML scores for final decision

## Dependencies (if implemented)

- `transformers` (Hugging Face) for zero-shot
- `scikit-learn` for simple classifiers
- Optional: `snorkel` for weak supervision framework
