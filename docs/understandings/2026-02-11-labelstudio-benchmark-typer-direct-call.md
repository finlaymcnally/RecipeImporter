---
summary: "Why direct calls to labelstudio-benchmark need Annotated Typer options."
read_when:
  - Extending C3imp interactive actions that call Typer command functions directly
  - Debugging OptionInfo values appearing inside command logic
---

# Label Studio Benchmark Direct Call Rule

- `_interactive_mode` calls `labelstudio_benchmark()` directly (not through Typer CLI parsing).
- With `param=typer.Option(...)` defaults, direct calls receive `OptionInfo` objects and can fail at runtime.
- Use `typing.Annotated[T, typer.Option(...)]` with a real Python default (`= None`, `= "both"`, etc.) for commands that may be called directly.
