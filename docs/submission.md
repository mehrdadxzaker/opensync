# OpenAI plugin submission

The repository marketplace and public OpenAI directory are separate distribution paths. Building a ZIP or registering a marketplace does not submit a public directory listing.

## Package

Run `python3 scripts/package_plugins.py`. Upload `dist/opensync-codex-0.1.0.zip` through https://platform.openai.com/plugins using the Skills only path. It contains the portable manifest, Codex compatibility manifest, bundled Python runtime, four skills, assets, privacy statement, and license. It contains no MCP server, app references, lifecycle hooks, or credentials.

The manifest sets `requires_local_executor: true` because the product accesses a local knowledge base and calls a local Python runtime. This is a desktop plugin. Keep that declaration in the submitted package. If the portal rejects desktop execution for the selected organization, confirm eligibility with the OpenAI representative rather than misclassifying it as a cloud skill.

## Listing

Display name: OpenSync

Subtitle: Your knowledge, synced locally

Description: Keep URLs, files, folders, and Git repositories synchronized in a shared local knowledge base. Search offline with citations and freshness. No API keys or model downloads. Requires Python 3.10+ on your computer.

Category: Productivity

Website: https://github.com/mehrdadxzaker/opensync

Support: https://github.com/mehrdadxzaker/opensync/issues

Privacy: https://github.com/mehrdadxzaker/opensync/blob/main/docs/privacy.md

Terms: https://github.com/mehrdadxzaker/opensync/blob/main/docs/terms.md

## Reproducible review workflow

1. Install the desktop plugin in a clean environment with Python 3.10+ and SQLite FTS5.
2. Ask it to index a small Markdown file in a temporary directory every six hours. Verify the returned source and schedule status. If OS timer setup is unavailable, verify the reported failure and use the foreground worker explicitly.
3. Ask a question answered by the file. Verify that retrieval cites the original path, extracted line range, and freshness.
4. Edit the file, request a refresh, and repeat the question. Verify the updated answer.
5. Temporarily make the source unreadable or unavailable and request another refresh. Verify that the old content is still searchable and is reported as stale with a synchronization error.
6. Pause and resume the source, then remove its registration. Verify that the original file remains unchanged.

A signed-in submitting organization needs Apps Management write access and a verified developer identity. Complete the portal's scans and fix each error before submitting. Agreement acceptance and identity verification remain account-owner actions when required.

## Verification scope for v0.1.0

The implementation suite passes locally on Python 3.13 and 3.14. Tests use mocked web responses, a real local Git fixture, temporary stores, mock OS timer execution, and clean extracted plugin archives. An offline wheel build and clean virtual environment installation were also verified. CI is configured for Python 3.10 and 3.12 on macOS, Linux, and Windows; consult the Actions results for executed CI status. This document does not claim public directory approval or a live installed-host evaluation.
