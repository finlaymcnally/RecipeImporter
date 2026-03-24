# CLI Commands

Each file owns one public `cookimport` command family. `cookimport/cli.py` is now only the thin
composition root and compatibility surface, while `cookimport/cli_support.py` keeps the shared CLI
helper state that these modules import.
