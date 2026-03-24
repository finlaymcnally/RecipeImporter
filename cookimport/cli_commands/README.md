# CLI Commands

Each file owns one public `cookimport` command family. `cookimport/cli.py` rebuilds the Typer apps
from this package and re-exports compatibility wrappers back onto `cookimport.cli` so legacy direct
call sites and monkeypatch-heavy tests stay in sync with the command-family modules.
