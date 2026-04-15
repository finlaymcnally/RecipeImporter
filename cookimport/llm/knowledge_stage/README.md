Private knowledge-stage package.

Start with:
- `planning.py` for shard planning and packet budgets
- `stage_plan.py` for the shared knowledge phase-plan builder that preview and runtime both consume
- `workspace_run.py` for the live inline-json/taskfile worker loop
- `structured_session_contract.py` for worker-visible packet/prompt/response shaping
- `task_file_contracts.py` for taskfile validation and grouping task construction
- `promotion.py` and `reporting.py` for final stage outputs and summaries

Current inline classification contract:
- pass 1 is row-grounded and asks for one ordered `rows` array of `{row_id, category}`
- allowed categories stay binary: `keep_for_review` or `other`
- missing rows now narrow repair through unresolved `row_id`s in the `rows` array itself

Current inline grouping contract:
- pass 2 reads one mixed `ordered_rows` surface
- plain `rXX | ...` rows are groupable
- `ctxXX | ng | ...` rows are context only and must not be grouped

Authority boundary:
- deterministic code validates structure, row coverage, grouping contiguity, and catalog/legal grounding shape
- deterministic code does not demote accepted knowledge rows based on usefulness heuristics
