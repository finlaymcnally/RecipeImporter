# Agent Guidelines — /cookimport

- Reuse shared spinner/status helpers instead of adding one-off indicator implementations.
- For any loop over a known-size worklist, spinner/progress text must include `task X/Y`.
- If total work is unknown at start, emit phase-only status first, then switch to `task X/Y` as soon as total is known.
- Prefer progress propagation through existing `progress_callback` plumbing in runtime modules.
