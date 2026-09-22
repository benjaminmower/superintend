# tracker-agent

An AI layer on top of an existing Google Sheets weekly construction tracker (one spreadsheet per project, a new `wk M/D` tab each week, and a change-log tab). The sheet stays the only interface the team uses. This service flags at-risk items, writes next actions, keeps an AI Brief tab, drafts the weekly report email, and answers questions from project documents and tracker history (RAG) with citations.

Full scope, the observed sheet structure, and phases: see `SPEC.md`. Work one phase at a time, in order.

## Stack

- Python 3.12, managed with `uv`
- `gspread` + `google-auth` (service account) for Sheets and Drive
- `anthropic` SDK for all LLM calls. The model ID lives in `config/settings.yaml` and nowhere else.
- SQLite (stdlib `sqlite3`): run log, parsed history, doc chunks (FTS5)
- `pymupdf` for PDFs, `typer` CLI, `pydantic` for config and LLM output schemas, `jinja2` for email, `pytest`

## Commands

```bash
uv sync
uv run tracker inspect                    # tabs, latest week, header row, column mapping (read-only)
uv run tracker flag [--dry-run]           # Phase 1: AI Flag + AI Next Action on the latest weekly tab
uv run tracker brief [--dry-run]          # Phase 2: rewrite the AI Brief tab
uv run tracker report [--dry-run]         # Phase 3: weekly report email (dry-run writes out/*.html)
uv run tracker roll-week [--apply]        # Phase 3 optional: create next week's tab (dry-run by default)
uv run tracker ingest                     # Phase 4: index Drive docs + tracker history
uv run tracker ask "question"             # Phase 4
uv run tracker watch                      # Phase 4: poll the Ask tab
uv run tracker eval                       # Phase 5: RAG eval
uv run tracker backtest                   # Phase 5: replay flags against change-log history
uv run tracker stats                      # Phase 5
uv run pytest
```

## Layout

```
src/tracker_agent/
  cli.py            # typer entrypoints only; no business logic
  config.py         # settings.yaml + sources.yaml + .env → pydantic
  core/models.py    # Item, Change, Flag, Brief — the canonical domain model. Source-agnostic.
  core/capabilities.py
  sources/base.py   # TrackerSource protocol + CAPABILITIES enum + registry
  sources/gsheets/  # client.py, weekly.py (parser), changelog.py, writer.py
  sources/fake.py   # in-memory source used by every test
  llm.py            # single anthropic wrapper: retries, schema output, token/cost logging
  state.py          # SQLite
  flags.py  brief.py  report.py           # consume core.models ONLY
  rag/ ingest.py  retrieve.py  answer.py  # docs + source.history()
  backtest.py
config/  settings.yaml  sources.yaml
evals/questions.yaml
tests/fixtures/     # FAKE data only, mimicking the real structure
tests/contract/     # the source contract suite every adapter must pass
```

## The source boundary (read this before writing any feature)

The tracker is **one implementation behind an interface**, not the architecture. `flags.py`, `brief.py`, `report.py`, `backtest.py`, and `rag/` must work against any `TrackerSource` and must never import from `sources/gsheets/` or mention tabs, cells, A1 ranges, or gspread.

```python
class TrackerSource(Protocol):
    name: str
    capabilities: set[Capability]

    def items(self) -> list[Item]: ...                  # current open work
    def history(self, since: date | None) -> list[Change]: ...
    def write_annotations(self, anns: list[Annotation], *, dry_run: bool) -> WriteResult: ...
    def write_brief(self, brief: Brief, *, dry_run: bool) -> WriteResult: ...
    def questions(self) -> list[Question]: ...          # Ask-tab equivalent; may be empty
    def answer_question(self, qid: str, answer: Answer, *, dry_run: bool) -> WriteResult: ...
    def health(self) -> SourceHealth: ...               # parse confidence, warnings
```

`Item` is the contract: `id, project, group (sub/trade), title, due_date, status (enum), ball (enum), notes, last_changed, url, raw`.
- `status`: `not_started | in_progress | blocked | done | cancelled`
- `ball`: `us | them | city | none | unknown` — each adapter maps its own vocabulary onto these; the mapping table lives in `sources.yaml`, not in code.
- `raw` keeps the source's original record for debugging. Features must not read `raw`.

**Capabilities, not assumptions.** Sources differ, so features degrade instead of crashing:
`READ_ITEMS, READ_HISTORY, WRITE_ANNOTATIONS, WRITE_BRIEF, QUESTIONS, ATTACHMENTS, WEBHOOKS`.
Example: without `READ_HISTORY`, staleness falls back to snapshots in `state.db` and the brief drops its cycle stats. Without `WRITE_ANNOTATIONS`, flags go to the email and the brief only. Every feature declares what it needs and says plainly what it's skipping.

**Contract tests.** `tests/contract/` runs the same suite against every adapter, including `FakeSource`. A new adapter is done when it passes the suite. Don't write adapter-specific tests for shared behavior.

`config/sources.yaml` selects and configures the adapter:
```yaml
active: gsheets            # gsheets | fake | procore | ...
sources:
  gsheets: { spreadsheets: [...], weekly_tab_regex: '...', columns: {...}, ai_columns: {...} }
status_map:                # source vocabulary → canonical enums
  "Waiting for Response": {ball: them}
  "Need to Respond":      {ball: us}
```

## Guardrails (non-negotiable)

0. **Features never import an adapter.** Only `cli.py` / `config.py` resolve the active source. A feature that needs something the source can't do checks `capabilities` and degrades.
1. **Writes are allow-listed:** only the `ai_columns` on the **latest weekly tab**, plus the agent-owned tabs (`AI Brief`, `Ask` answer columns, `AI Log`). Human columns A–F, title rows, older weekly tabs, and the change log are read-only. Enforce this in `sheets.write_ai_cells()` / `write_agent_tab()` and cover it with tests.
2. **Never delete or rename tabs.** `roll-week` only creates a tab, and only with `--apply`.
3. **`--dry-run` works for every write command** and prints the exact cell diff.
4. **If parsing is uncertain** (no latest tab found, header row missing, unmapped columns), stop, log it, and write nothing.
5. **One batch update per run** (Sheets API quotas).
6. **No real project data in git:** no real names, addresses, notes, or sheet IDs in tests, fixtures, evals, README, or commit messages. `.env`, `credentials/`, `data/`, `out/`, and `*.db` are gitignored.
7. **RAG answers cite sources** (doc + page/section, or tracker week + item). With no support, the answer is "Not found", never a guess.
8. **Every LLM call goes through `llm.py`.** Deterministic logic first (dates, rule flags, change-log math); the LLM only writes the human-readable text.

## Sheet quirks to respect

- SUBCONTRACTOR is filled only on each group's first row: fill it down.
- The DATE column has a blank header: fall back to the column position right after ITEM.
- There are two status fields: STATUS (lifecycle) and DETAILS (who has the ball). Both matter for flags.
- Multi-select values like "Blocked, Completed" exist: take the last value and log a warning.
- Weekly tab names vary (`Wk 7/28`, `Wk of 8/18`, `wk 12/1`); ignore `Copy of …`. Infer the year by tab order.
- Row numbers shift between weeks: join the change log to items on normalized (sub, item), not on row.
- API writes don't trigger the sheet's `onEdit` change log, so record every agent write in `run_log` and the AI Log tab.

## Conventions

- Map columns by header through `sheet.yaml`, never by hard-coded letters (except the documented DATE fallback).
- LLM outputs use pydantic schemas: validate, retry once, then skip and log.
- AI cell text is short: next action ≤ 100 chars, snapshot ≤ 5 sentences.
- Type hints everywhere; `ruff` for lint and format.

## Verifying a change

1. `uv run pytest` passes (no network; uses `FakeSheetClient`).
2. `--dry-run` against the **demo** spreadsheet (`SHEET_ID_DEMO`); review the diff.
3. Only then run against the real sheet (`SHEET_ID`).
