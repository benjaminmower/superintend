# tracker-agent

An AI layer on top of an existing Google Sheets weekly construction
tracker — one spreadsheet per project, a new `wk M/D` tab duplicated each
week, and a change-log tab that already records every edit. The sheet
stays the only interface the team uses. This service flags at-risk
items, writes next actions, keeps an AI Brief tab, drafts the weekly
report email, and answers questions from project documents and tracker
history (RAG) with citations. A later phase adds an agent that
investigates each flagged item (history, related tasks, sub
responsiveness) before deciding, measured against the deterministic
rules on real project history rather than assumed to be better.

**Status:** Phase 0 (parsing) and Phase 1 (`tracker flag`) are done and
running against a real, active construction project — not just the demo.
Phases 2–7 are ahead; see `SPEC.md` for the full roadmap.

Full scope, the observed sheet structure, and phases: see `SPEC.md`.
Repo conventions and guardrails: see `CLAUDE.md`. How results will be
measured and reported, pinned before the numbers exist: see
`docs/measuring-value.md`. Work one phase at a time, in order.

Google Sheets is the first data source, not the architecture: every
feature is written against a source-agnostic `TrackerSource` interface
(`core/models.py`, `sources/base.py`), so a CSV export or a Procore
integration can be added later as a second adapter without touching
flags/brief/report/RAG. See `docs/adapters.md`.

## Quickstart

```bash
uv sync
uv run tracker inspect                 # tabs, latest week, header row, column mapping (read-only)
uv run tracker flag --dry-run          # AI Flag + AI Next Action on the latest weekly tab
uv run pytest
```

`flag` writes two things per item: a deterministic risk flag (overdue,
blocked, waiting on us/them too long, stale, missing a date, or
inconsistent) and one short next action from Claude. A next action is
only regenerated when the item's status, ball, due date, or notes
actually changed since the last run — an unchanged item reuses its
stored text instead of asking the LLM again and getting different
wording for the same situation. `--no-llm` runs the rules only, with no
API key needed.

Two rows that share the exact same subcontractor and item text within
one week are flagged `⚠️ Duplicate — consolidate with row N` instead of
guessing they're the same task — found running against a real, messy
280-item sheet, not the clean demo fixture.

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
