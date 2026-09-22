# tracker-agent

An AI layer on top of an existing Google Sheets weekly construction
tracker — one spreadsheet per project, a new `wk M/D` tab duplicated each
week, and a change-log tab that already records every edit. The sheet
stays the only interface the team uses. This service flags at-risk
items, writes next actions, keeps an AI Brief tab, drafts the weekly
report email, and answers questions from project documents and tracker
history (RAG) with citations.

Full scope, the observed sheet structure, and phases: see `SPEC.md`.
Repo conventions and guardrails: see `CLAUDE.md`. Work one phase at a
time, in order.

Google Sheets is the first data source, not the architecture: every
feature is written against a source-agnostic `TrackerSource` interface
(`core/models.py`, `sources/base.py`), so a CSV export or a Procore
integration can be added later as a second adapter without touching
flags/brief/report/RAG. See `docs/adapters.md`.

## Quickstart

```bash
uv sync
uv run tracker inspect        # tabs, latest week, header row, column mapping (read-only)
uv run pytest
```

Google Cloud / service account setup: see `docs/setup.md`.

## Guardrails (non-negotiable)

1. Writes are allow-listed: only `ai_columns` on the **latest** weekly
   tab, plus the fully agent-owned tabs (`AI Brief`, `Ask`'s answer
   columns, `AI Log`). Human columns A–F, title rows, older weekly tabs,
   and the change log are read-only. Enforced in
   `sources/gsheets/raw.py`'s `write_ai_cells()` / `write_agent_tab()`,
   behind `TrackerSource.write_annotations()` / `write_brief()`.
2. `--dry-run` works for every write command and prints the exact diff.
3. If parsing is uncertain, stop and log — never write.
4. One batch update per run.
5. No real project data in git — `.env`, `credentials/`, `data/`, `out/`,
   `*.db` are gitignored; fixtures use invented names.
6. RAG answers cite a source, or say "Not found."
7. Every LLM call goes through `llm.py`; deterministic logic runs first.

See `CLAUDE.md` for the full list and the sheet-parsing quirks (fill-down,
the blank DATE header, multi-select cleanup, tab-naming drift).
