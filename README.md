# OpenSync

**Sync anything to a local, searchable knowledge base.**

```sh
kb sync https://example.com/docs --every 6h
kb sync ~/Documents/project --every 15m
kb sync git+https://github.com/owner/repo.git --every 1d
kb search "deployment requirements"
```

Register a source once. OpenSync indexes it immediately and refreshes it on your chosen interval. Your agents share one local SQLite knowledge base with ranked passages, source locations, line citations, and freshness.

No API keys. No model downloads. No hosted indexing service. Search works offline.

## Install

Python 3.10+ with SQLite FTS5 is required. macOS and Linux support user-level OS timers. Windows uses the portable foreground worker or your own task scheduler.

```sh
uv tool install git+https://github.com/mehrdadxzaker/opensync.git
```

Or install from a checkout:

```sh
git clone https://github.com/mehrdadxzaker/opensync.git
cd opensync
python3 -m pip install .
```

Both `kb` and `opensync` invoke the same CLI. To try the bundled runtime without installing anything:

```sh
python3 scripts/kb.py sync ./examples --every 6h --no-schedule
python3 scripts/kb.py search "shared knowledge"
```

The GitHub install is the release distribution path. This project has not been published to PyPI.

## Sync your sources

| Source | Example | Behavior |
| :--- | :--- | :--- |
| Web resource | `kb sync https://example.com/docs --every 6h` | Extract one HTTP(S) resource; no recursive crawling |
| File | `kb sync ./guide.md --every 15m` | Track changes to a document |
| Folder | `kb sync ./notes --every 15m` | Recursively index supported documents; remove deleted documents |
| Git repository | `kb sync git+https://github.com/owner/repo.git --every 1d` | Track the remote default branch through an isolated shallow clone |
| Source list | `kb sync --from sources.txt --every 6h` | Register multiple sources, deduplicated |
| Standard input | `cat sources.txt | kb sync --from - --every 6h` | Import a source list from another command |

A source list has one source per line. Blank lines and lines beginning with `#` are ignored. Local paths resolve relative to the list file. The list is imported, so rerun the command after changing it.

```text
https://example.com/docs
./notes
git+https://github.com/owner/repo.git
```

Multiple sources can also be passed directly:

```sh
kb sync https://example.com/docs ./notes ./guide.md --every 6h
```

Supported formats: text, Markdown, HTML, JSON, CSV, TSV, XML, YAML, TOML, notebooks as JSON, common source code, and DOCX. PDF text extraction is optional:

```sh
python3 -m pip install '.[pdf]'
```

Scanned PDFs require external OCR. Audio, video, authenticated SaaS connectors, browser-rendered pages, and semantic embeddings are future adapters. "Anything" is the product direction; this release supports the formats and transports above.

## Search with evidence

```sh
kb search "state transitions" --limit 5
kb search "state planning" --any
kb search "deployment" --source 2
kb read DOCUMENT_ID --start 20 --lines 80
```

Search uses SQLite FTS5 and BM25 ranking. All query words match by default; `--any` matches any word. Queries are treated as plain text, not raw FTS syntax. This is keyword search, not semantic search or a chatbot.

Every result is JSON with `document_id`, `source`, `location`, `title`, `line_start`, `line_end`, `passage`, `score`, `last_synced_at`, `stale`, `sync_error`, and `paused`. Read a result by its document ID to recover more context from the indexed snapshot. For HTML, DOCX, and PDF, citations refer to extracted text lines. Git locations use `git+https://…repo.git#relative/path`.

## Keep it current

`sync` installs a user-level refresh timer by default: launchd on macOS, systemd on Linux. The timer checks due sources every minute. It catches up when your computer wakes or your session resumes. It does not synchronize while the computer is off.

```sh
kb sources
kb refresh             # only due, unpaused sources
kb refresh 2           # one source immediately
kb refresh --all       # all unpaused sources immediately
kb pause 2
kb resume 2
kb history --source 2
kb schedule status
kb schedule plan
kb schedule install
kb schedule uninstall
```

If timer installation fails, indexing still completes and the command exits with status 1, reporting both outcomes. On Windows, Linux without systemd, or a restricted environment:

```sh
kb sync ./notes --every 6h --no-schedule
kb worker
```

Keep the foreground worker running, or configure your OS scheduler to run `kb refresh` every minute. `--no-schedule` skips timer setup and leaves any existing timer untouched. `worker --once` runs one due-source iteration. Timers reference absolute package paths: rerun `kb schedule install` after moving the checkout, updating the plugin, or changing Python installations.

Snapshots are transactional per source. Changed documents are reindexed; unchanged documents retain their index entries. A failed read, incomplete directory traversal, parse error, or failed Git fetch preserves the previous complete snapshot and records an error. Folder deletions enter the index only after a complete successful scan. Sources in the same batch succeed or fail independently.

## Agent plugins

The repository is a portable Agent Plugins package with native Codex and Claude compatibility manifests. The plugin bundles the runtime, so agents can run it without installing a separate CLI. It contains four skills: `kb`, `kb-sync`, `kb-search`, and `kb-setup`.

### Codex

Register the repository marketplace:

```sh
codex plugin marketplace add mehrdadxzaker/opensync --ref main
```

Open the Plugins Directory in the desktop app, choose **OpenSync**, and install the plugin. Run its setup workflow, then ask it to sync a source or search your knowledge base. Codex supports invoking the skill from its skill picker, including `$opensync:kb-sync` and `$opensync:kb-search` where namespaced skill invocation is available.

For a local checkout, use `codex plugin marketplace add /absolute/path/to/opensync`. A portable ZIP is also produced by the packaging script. Public directory submission and review are separate from repository marketplace distribution; this README does not imply OpenAI approval.

### Claude Code

```text
/plugin marketplace add mehrdadxzaker/opensync
/plugin install opensync@opensync
/kb sync ./notes every 6h
```

The same skills and runtime back both plugins. No MCP server or lifecycle hooks are required.

## Your data

Default storage:

| Platform | Directory |
| :--- | :--- |
| macOS | `~/Library/Application Support/opensync` |
| Linux | `$XDG_DATA_HOME/opensync` or `~/.local/share/opensync` |
| Windows | `%LOCALAPPDATA%/opensync` |

Use `OPENSYNC_HOME` or `kb --home /absolute/path …` to choose another knowledge base. Database directories are created with private permissions where supported. SQLite stores extracted content in plaintext; use disk encryption for sensitive material.

Hidden files, hidden folders, common dependency/build directories, and nested symlinks are excluded from folder scans. Add `.opensyncignore` to the source root for additional fnmatch patterns matched against relative paths or basenames. This is separate from `.gitignore`; negation rules are not supported. Visible supported files are otherwise included, so choose folders intentionally. Secrets embedded in ordinary documents are not automatically redacted.

```text
private/
*.log
exports/*.csv
```

Per-document input and extracted text are limited to 16 MiB. Each source snapshot is limited to 128 MiB and 10,000 documents. HTTP requests time out after 25 seconds; Git commands after 120 seconds. Refresh work is serialized, and concurrent readers use SQLite WAL snapshots.

```sh
kb export              # source registration metadata as JSON
kb remove 2 --yes       # remove source and indexed content; preserve originals
```

URLs are stored as supplied after normalization, including query strings. Use URLs without secret tokens. Git supports public HTTPS repositories without embedded credentials; private repository authentication is not part of this release. A removed Git source can leave its isolated clone cache on disk; removal is not secure erasure. See [privacy](docs/privacy.md).

## Develop

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate_plugin.py
python3 scripts/package_plugins.py
```

Tests use temporary knowledge bases and mocked network calls. They cover synchronization, edits, deletions, atomic rollback, stale evidence, source lists, retrieval, independent WAL readers, scheduler plans, and extracted plugin execution. CI runs the suite on macOS, Linux, and Windows with Python 3.10 and 3.12.

The adapter boundary is `snapshot(uri, kind, home) -> list[Document]`. Add a transport or parser there while keeping transactions, scheduling, and retrieval shared. See [architecture](docs/architecture.md).

MIT licensed.
