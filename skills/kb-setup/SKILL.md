---
name: kb-setup
description: Set up the OpenSync desktop plugin, verify Python and SQLite, choose a first source, and diagnose refresh scheduling.
---

This plugin runs on the user's computer. Resolve `../../scripts/kb.py` relative to this directory. It bundles its own Python source and needs no pip installation, model, API key, or account.

1. Run `python3 <bundled-cli> --version` and `python3 <bundled-cli> status`. Success confirms the runtime and SQLite FTS5 index are usable. If Python 3.10+ is unavailable, explain that requirement and stop dependent commands.
2. If the user already supplied a source, use kb-sync. Otherwise explain the command `kb sync SOURCE --every 6h` and ask which source they want. Avoid indexing a broad folder based on assumptions.
3. After syncing, run `schedule status`. A user timer must be active for unattended refresh. Use `schedule plan` to inspect its exact configuration and `schedule install` to repair a timer the user wants enabled.
4. Explain the result and show how to search the source. A failed setup remains a failed setup until the runtime, indexing, and scheduler results support success.

macOS LaunchAgents and Linux systemd user timers run while the user session and machine are available. Missed intervals catch up after the next timer tick. On Windows or Linux without systemd, `worker` provides a foreground loop; OS scheduling can invoke `refresh` every minute. Keep the package in a stable location because timers reference its absolute runtime path. After moving or updating the package, rerun `schedule install`.
