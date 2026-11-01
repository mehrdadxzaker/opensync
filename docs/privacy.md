# OpenSync privacy

Effective November 1, 2026.

OpenSync is local software. Its publisher does not operate a hosted indexing service, collect telemetry, receive your indexed content, or require an OpenSync account.

## Data stored on your computer

The selected knowledge base directory contains source addresses, refresh intervals, errors, timestamps, extracted document text, search passages, synchronization history, a writer lock, and Git clone caches. OS timers can write refresh output and errors to local log files. Content is stored in plaintext SQLite files. Your computer, backup software, disk encryption, and user permissions determine access.

OpenSync requests the web URLs and Git repositories you choose. Those hosts receive normal request metadata such as your IP address and requested path. Redirects can contact another host; HTTPS to HTTP downgrades are rejected. The HTTP runtime can use your system's proxy settings. URL query strings are persisted, so use URLs without credentials or secret tokens.

## Agent hosts

When an agent invokes search, the result enters that agent's conversation and is subject to the agent provider's data policies. Keeping the index local does not mean a cloud agent processes retrieved passages locally. Decide which material to index and expose to your agent.

## Deletion

`kb remove ID --yes` deletes that source registration and its searchable snapshot. Original files remain unchanged. Git caches, SQLite free pages or WAL history, OS logs, and backups may retain data; this command is not secure erasure. After stopping the scheduler and worker and closing readers, deleting the whole selected knowledge base directory removes the application's local store, subject to filesystem and backup retention.

## Scope

Folder scanning excludes hidden files, nested symlinks, selected build folders, and patterns in `.opensyncignore`. It does not automatically redact secrets inside visible documents. Broad folder scans can capture sensitive files. Choose sources and ignore patterns intentionally.

Questions or reports: use the public issue tracker at https://github.com/mehrdadxzaker/opensync/issues without posting private documents, credentials, or personal data.
