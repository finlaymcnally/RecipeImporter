---
summary: "Plain-English walkthrough for humans of what cookimport does, how it works, and where AI fits."
read_when:
  - Coding agents, DO NOT READ
  - This is the simple human-friendly explanation of the program
  - When someone wants to understand the project without code or pipeline jargon
---

# Plain-English Explanation of `cookimport`

This document is for a normal human who wants to understand what this project does without reading code and without getting buried in technical language.

If `docs/AI_context.md` is the "serious architecture handoff for another AI," this file is the "tell me what this thing actually is and why it is built this way" version.

## Short version

`cookimport` is a tool for taking messy cookbook-like sources and turning them into clean, structured recipe data plus useful evidence about how that data was produced.

It can work with things like:

- PDFs
- EPUBs
- spreadsheets
- Word docs
- markdown/text files
- Paprika exports
- RecipeSage exports
- some web/schema-style sources

The project is not just trying to "scrape recipes."

It is trying to do something stricter:

1. read a source in a reliable way
2. break it into a clean internal representation
3. decide what is recipe material and what is not
4. turn recipe material into structured recipe outputs
5. keep enough evidence and artifacts around that a human or another tool can check what happened later

That last part matters a lot. This project cares about provenance, reviewability, and clean boundaries between deterministic logic and AI judgment.

## What the project is really for

Imagine you have a cookbook, export, or recipe collection that is messy, inconsistent, and hard to work with.

Maybe:

- recipes are mixed with intros, stories, tips, and reference material
- formatting changes from page to page
- one source type behaves very differently from another
- some things are obviously recipes and some things are not
- some parts are easy for normal code to understand and some parts need fuzzier judgment

`cookimport` exists to turn that mess into something structured and reusable.

The outputs can then be used for things like:

- importing recipes into another system
- reviewing recipe extraction quality
- generating tasks for human labeling or correction
- running benchmarks to compare methods
- producing analytics and debugging artifacts

So the project is not just a "converter."

It is closer to a careful processing pipeline with strong bookkeeping.

## The most important idea in the whole repo

The biggest thing to understand is this:

The project has moved away from the old idea of "whatever the importer says is truth."

Instead, it now works more like this:

- importers gather source material
- a shared central pipeline makes the important meaning decisions
- the final outputs and evidence come from that shared pipeline

That means the importer is not supposed to be the final boss.

The importer helps turn a source into a standard internal form.
After that, the shared processing pipeline is what decides what counts as recipe content, what counts as non-recipe content, and what the final outputs should look like.

If you understand that one idea, the rest of the design makes much more sense.

## What kinds of sources it can handle

The tool supports several families of inputs.

### Book-like files

These are the big, messy sources where structure is often implied rather than explicit.

Examples:

- PDF
- EPUB

These are especially important because they often need splitting, merging, and more careful processing.

### Text-like sources

These are sources that are already fairly text-friendly.

Examples:

- markdown
- plain text
- DOCX

### Record-like sources

These are more structured from the start.

Examples:

- spreadsheets
- exported recipe collections

### Already somewhat structured recipe sources

Examples:

- Paprika exports
- RecipeSage exports
- some schema/web inputs

These are usually easier in some ways, but they still need to pass through the same shared truth-making pipeline if they are going through the main stage flow.

## What happens when you process a source

At a high level, the tool does not jump straight from "input file" to "final recipes."

It moves through a set of steps.

## Step 1: pick the right importer

The tool first asks:

"What kind of source is this, and which importer is best suited to read it?"

Different importers know how to deal with different source types.

But the importer's job is mainly to normalize the source, not to declare final recipe truth.

That is a very important distinction.

## Step 2: turn the source into a standard internal form

Once the right importer is chosen, the source gets converted into a common internal representation.

You can think of this as:

"Take all these weird source types and get them into one house style so the rest of the pipeline can reason about them consistently."

That internal form includes things like:

- source blocks
- supporting evidence
- raw artifacts
- reports about what was found

This is the stage where the tool becomes less about "what kind of file was this?" and more about "what content is actually here?"

## Step 3: run the shared semantic pipeline

This is the center of the system.

The current main flow has five named stages:

1. extract
2. recipe-boundary
3. recipe-refine
4. nonrecipe-route
5. nonrecipe-finalize

Those names are more important than old historical stage nicknames.

Here is what they mean in human language.

### Extract

Get the source material into the main working bundle the rest of the system will use.

This is where the project says:

"Here is the book or source as the shared pipeline will see it."

### Recipe boundary

Figure out what parts of the source actually belong to recipes.

This is not the same as fully understanding every recipe yet.
It is more about deciding which blocks of material belong inside recipe ownership and which do not.

### Recipe refine

Take the material that belongs to recipes and produce better recipe-level meaning from it.

This can include AI help when enabled, but the repo still validates and shapes the final result carefully.

### Nonrecipe route

Look at the material that is outside recipes and decide what should even be considered for further non-recipe handling.

Some things are obvious junk.
Some things are obviously not useful.
Some things are possible knowledge or supporting material worth keeping.

This stage is about routing that outside-recipe material sensibly.

### Nonrecipe finalize

Make the final call about the outside-recipe material that survived routing.

This is where the system decides what is meaningful knowledge and what is just "other."

## Why the recipe and non-recipe split matters

Cookbook-like sources do not contain only recipes.

They also contain:

- introductions
- headnotes
- memoir-ish writing
- kitchen advice
- reference sections
- nutrition notes
- sidebars
- obvious junk
- layout leftovers

A weak recipe importer often smashes all of that together and hopes for the best.

This project does not want to do that.

It wants a clean answer to questions like:

- which blocks belong to a recipe?
- which blocks are useful but outside the recipe?
- which blocks are neither and should be ignored?

That separation is one of the things that makes the repo feel more serious than a one-shot converter.

## Where AI fits in

AI is part of the project, but it is not supposed to own everything.

The repo has a strong philosophy here.

### Deterministic code should own:

- file and path handling
- IDs
- normalization
- validation
- artifact writing
- report generation
- final packaging
- making sure boundaries stay clean

### AI should own the fuzzy semantic judgment parts

Things like:

- tricky line-role decisions
- recipe refinement/correction
- deciding whether some outside-recipe material is meaningful knowledge or just other material
- freeform labeling suggestions

In simple terms:

The normal code should package evidence and enforce rules.
The AI should make the fuzzy calls.

What the repo explicitly does not want is normal deterministic code pretending it is smart enough to silently "fix" ambiguous meaning on its own.

That is considered dangerous here.

## So is this an AI-first project?

Not exactly.

It is better to think of it as:

- deterministic first in structure
- optional AI for hard semantic judgments
- deterministic validation and writing at the end

That is different from a project that just throws a whole file at an LLM and trusts whatever comes back.

This repo is trying to preserve clean boundaries between:

- gathering evidence
- making semantic judgments
- validating those judgments
- writing durable outputs

## What gets written out

One of the major goals of the project is not just "produce results."

It is also "leave behind enough useful artifacts that someone can inspect what happened."

Depending on the run and settings, outputs can include things like:

- final recipe drafts
- intermediate recipe outputs
- sections and chunks
- raw source artifacts
- manifests
- reports
- benchmark inputs and results
- Label Studio tasks or exports
- AI runtime artifacts
- analytics history

So a run is not just one final JSON file.

It is more like a timestamped folder of outputs and evidence.

## Why the timestamped folders matter

The project writes runs into timestamped folders so different runs stay separate and inspectable.

That helps with things like:

- comparing runs
- benchmarking changes
- keeping provenance straight
- avoiding confusion about which artifacts came from which execution

This project cares a lot about reproducibility and auditability, so the run folder structure is part of the design, not an afterthought.

## Why split jobs and merge behavior exist

Some inputs, especially big PDFs and EPUBs, are too awkward or too large to handle as one giant undifferentiated chunk.

So the project can split work into source jobs and then merge those jobs back together before the main shared semantic pipeline makes final decisions.

This matters because:

- it helps with large inputs
- it helps with source ranges
- it keeps processing manageable
- it still preserves one shared truth-making pass later

That last point is the key.

Splitting does not mean each piece gets to invent its own final truth forever.
The split pieces come back together so the shared semantic pipeline can decide meaning on the merged whole.

## What Label Studio is doing here

Label Studio support exists because sometimes you want human labeling, human review, or benchmark-style evaluation around the processing pipeline.

In practice, this means the project can:

- generate tasks for labeling
- upload tasks when that is explicitly intended
- export or compare reviewed results
- reuse stage-backed truth for benchmark flows

The important design idea is that Label Studio flows are supposed to reuse the same underlying truth model, not create a completely separate competing one.

## What benchmarks are for

The benchmark side of the repo exists so the author can compare methods, measure changes, and inspect quality over time.

This is not just a "does it run?" repo.

It is also a:

- how good is this result?
- what got better?
- what got worse?
- which method should I trust more?

kind of repo.

That is why there is so much emphasis on artifacts, evidence, manifests, follow-up bundles, and evaluation surfaces.

## Why there are so many artifacts

From the outside, the repo can look artifact-heavy.

That is intentional.

A project like this becomes much easier to trust when it leaves behind:

- what input it saw
- what it thought the source blocks were
- what got classified as recipe
- what stayed outside recipe
- what final outputs were written
- what the AI did
- what got promoted
- what got rejected

Without those artifacts, it becomes much harder to debug, benchmark, or review.

## What the final outputs are supposed to be

There are two important user-facing ideas here:

### Intermediate recipe outputs

These are roughly described as:

`schema.org Recipe JSON`

### Final recipe outputs

These are roughly described as:

`cookbook3`

Internally you may still see names like `RecipeDraftV1`, but the human-facing idea is:

- intermediate recipe structure
- final cookbook-ready structure

## What "truth" means in this project

One reason this repo can feel complicated is that it cares a lot about where truth is decided.

Here is the simple version.

### Importers are not supposed to be final truth

They help turn a source into the standard internal form.

### The shared stage pipeline is the main truth-making system

This is where recipe ownership, recipe meaning, and non-recipe meaning get decided.

### Artifacts and manifests are important records of that truth

They are what downstream tools and reviewers should trust first when there is disagreement.

That is why the repo is so careful about boundaries.

If every stage started quietly inventing its own private truth, the whole pipeline would become much harder to trust.

## A good mental model for the whole thing

If you are trying to explain this project to someone in one paragraph, this is a decent version:

`cookimport` is a local processing pipeline for cookbook-like sources. It reads many source types, normalizes them into a shared internal form, runs one central multi-stage pipeline to decide what is recipe material and what is not, optionally uses AI for the ambiguous semantic parts, and writes both structured outputs and lots of supporting artifacts so the results can be reviewed, benchmarked, and reused.

## What the project is not

It is not mainly:

- a simple one-file converter
- a pure scraper
- a giant prompt wrapped in a CLI
- a system where importers make all the important decisions
- a system where AI is trusted without validation

Those are all useful contrasts, because they explain why the project has the shape it has.

## Why the project feels "serious"

The repo is trying to be careful in a few specific ways:

- it separates source reading from final semantic judgment
- it separates recipe from non-recipe material
- it keeps deterministic and AI responsibilities distinct
- it writes lots of evidence and artifacts
- it supports review and benchmark flows instead of only happy-path conversion
- it tries to keep truth centralized rather than duplicated

That combination gives the project a different feel from a quick script or a one-shot AI importer.

## A normal-human walkthrough of one run

Here is a simple mental picture of what happens.

### You give the tool a source

For example:

- a cookbook PDF
- an EPUB
- a recipe export file

### The tool picks the right importer

It figures out how to read that source.

### The source gets normalized

The source is converted into a standard internal shape the rest of the system can understand.

### The main processing pipeline takes over

It works through the current shared stages:

- extract
- recipe-boundary
- recipe-refine
- nonrecipe-route
- nonrecipe-finalize

### Optional AI help may be used

If enabled, AI helps with the fuzzy semantic calls.

### Deterministic code validates and writes outputs

The repo code makes sure the outputs are well-formed and writes the final files plus all the supporting artifacts.

### You end up with a timestamped run folder

Inside that folder are the main outputs and the evidence needed to inspect what happened.

## Why a plain-English doc like this exists

The repo has very detailed technical docs, and those are useful.

But sometimes you do not want:

- file paths
- type names
- internal package boundaries
- every little runtime contract

Sometimes you just want to know:

- what is this thing?
- what is it trying to do?
- where does AI fit?
- why are there so many steps?
- why so many artifacts?

That is what this document is for.

## The one-sentence takeaway

`cookimport` is a careful recipe-import pipeline that turns messy cookbook sources into structured outputs by combining deterministic evidence-handling, optional AI judgment for ambiguous meaning, and a lot of artifact-writing so the whole process stays reviewable and trustworthy.
