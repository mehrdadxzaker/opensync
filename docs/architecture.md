# Architecture

The command is the product boundary: register a source, capture its current content, and keep the shared knowledge base synchronized.

`adapters.py` normalizes source identities and captures bounded snapshots. Local folders, individual files, HTTP resources, and public HTTPS Git repositories feed the same Document interface. Parsing supports text, HTML, DOCX, and optional PDF extraction. Git uses an isolated shallow clone, disables hooks and interactive credential prompts, and never executes repository code.

`core.py` owns source registrations, transaction boundaries, document digests, line chunks, FTS5 retrieval, and sync history. A source snapshot is assembled before index mutation begins. The old complete snapshot remains available until all new document and passage changes commit. Failures roll back the source update and write error metadata in a separate transaction. Each source has its own transaction, so a failed source does not undo successful sources from the same batch.

The CLI serializes mutation with a per-store process lock. SQLite WAL allows searches to use the preceding committed snapshot during a refresh. Changes to extracted content or titles replace only that document's passages. The current implementation rereads unchanged files and downloads unchanged URLs; digests avoid reindexing, not network transfer. ETag/Last-Modified conditional HTTP fetching and filesystem change detection are future optimizations.

Search sanitizes query words, joins them with AND or OR, and ranks matching chunks by BM25. It returns document IDs, original locations, extracted line ranges, timestamps, pause state, and sync errors. The separate read command expands an indexed document without recontacting its original source.

`scheduler.py` emits absolute runtime paths for per-store launchd or systemd timers. A timer calls `refresh`, which selects due unpaused sources. The portable foreground worker provides the same loop elsewhere. Successful refreshes set the next due time relative to completion; failures retry no more frequently than once per five minutes or the source period if shorter.

The root plugin package includes the same runtime and four skills. Codex and Claude compatibility manifests use the same source files. There is no MCP process, cloud service, model call, API key, automatic shell hook, or database copy per agent. The skill invokes scripts/kb.py using a package-relative path resolved to an absolute location.

The v0.1.0 schema is created on first use. Future schema changes must include an explicit migration before raising the stored schema version; this release does not migrate the earlier standalone kb.py prototype's database.
