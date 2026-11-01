---
name: kb
description: Use OpenSync to manage the user's local knowledge base, inspect source freshness, pause or resume synchronization, or remove indexed sources. Route adding sources to kb-sync and retrieval to kb-search.
---

Use the bundled CLI at `../../scripts/kb.py`, resolved relative to this skill's directory. Run `python3 /absolute/plugin/path/scripts/kb.py --help` when command syntax is needed. Quote each path or URI as a separate argument. The package requires Python 3.10+ with SQLite FTS5.

1. For source management, run `python3 <bundled-cli> sources`. The JSON includes stable IDs, errors, pause state, and freshness.
2. Apply the requested operation using that exact source ID: `pause ID`, `resume ID`, or `refresh ID`. `refresh` without an ID refreshes only due unpaused sources; `refresh --all` refreshes all unpaused sources.
3. For removal, establish that the user requested removal of the source and its indexed content, then run `remove ID --yes`. The original source is preserved.
4. Read back `sources` and report the resulting state. Use `history --source ID` to diagnose a failure.

For a new source or a source list, use kb-sync. For a factual question about indexed material, use kb-search. Setup and scheduler repair belong to kb-setup. A command error is a failure; report it and the concrete recovery step.

The database is shared across tasks on the same computer. An explicit `--home PATH` before the subcommand or `OPENSYNC_HOME` selects a separate knowledge base. Keep the user's existing choice consistent throughout the workflow.
