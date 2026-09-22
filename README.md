# tracker-agent

An AI layer on top of an existing Google Sheets construction project tracker.
The sheet stays the only interface the team uses; this service reads it,
writes to its own AI columns, flags risk, emails a weekly digest, and
answers questions from project documents (RAG) with citations.

Full scope and phases: see `SPEC.md`. Work one phase at a time, in order.

## Stack

- Python 3.12, managed with `uv`
- `gspread` + `google-auth` (service account) for Sheets and Drive
- `anthropic` SDK for all LLM calls. The model ID lives in
  `config/settings.yaml` and nowhere else.
- SQLite (stdlib `sqlite3`) for state: row snapshots, run log, doc chunks
  (FTS5)
- `pymupdf` for PDF text extraction
- `typer` for the CLI, `pydantic` for config and LLM output schemas,
  `pytest` for tests

## Commands

```bash
uv sync                                   # install
uv run tracker inspect                    # tabs, headers, row count, 3 sample rows (demo sheet, read-only)
uv run tracker inspect --no-demo          # same, against the real sheet
uv run tracker summarize [--dry-run]      # Phase 1
uv run tracker flag [--dry-run]           # Phase 2
uv run tracker digest [--dry-run]         # Phase 3 (dry-run writes out/digest-YYYY-MM-DD.html instead of sending)
uv run tracker ingest                     # Phase 4: index Drive docs
uv run tracker ask "question"             # Phase 4: answer from the CLI
uv run tracker watch                      # Phase 4: poll the Ask tab and answer new questions
uv run tracker eval                       # Phase 5: run the RAG eval set
uv run tracker stats                      # Phase 5: print metrics from the run log
uv run pytest
```

Google Cloud / service account setup: see `docs/setup.md`.

## Layout

```
src/tracker_agent/
  cli.py            # typer entrypoints only; no business logic
  config.py         # loads settings.yaml + sheet.yaml + .env into pydantic models
  sheets.py         # SheetClient protocol + GspreadClient + FakeSheetClient (tests)
  llm.py            # single wrapper around anthropic; retries, token logging, JSON schema output
  state.py          # SQLite: snapshots, run_log, chunks
  summarize.py  flags.py  digest.py
  rag/ ingest.py  retrieve.py  answer.py
config/
  settings.yaml     # model, thresholds, schedule, email recipients
  sheet.yaml        # column mapping: which headers mean what (generated in Phase 0, then hand-edited)
evals/questions.yaml
tests/fixtures/     # FAKE data only
```

## Guardrails (non-negotiable)

1. **Never write to a column not listed under `ai_columns` in `sheet.yaml`.** All writes go through `sheets.write_ai_cells()`, which enforces this. Human-owned cells are read-only to this code.
2. **`--dry-run` must work for every write command.** It prints the diff of what would change and writes nothing.
3. **Batch writes.** One `batch_update` per run, not per cell (Sheets API quotas).
4. **No real project data in git.** Not in tests, fixtures, evals, README, or commit messages. `.env`, `credentials/`, `data/`, and `*.db` are gitignored. Fixtures use invented projects and addresses.
5. **RAG answers must cite a source** (doc name + page, sheet number, or spec section). If retrieval finds nothing relevant, the answer is "Not found in project documents", never a guess.
6. **Every LLM call goes through `llm.py`** so tokens, latency, and cost are logged to `run_log`.
7. Deterministic logic first, LLM second. Date math, staleness, and overdue checks are plain Python; the LLM only writes the human-readable reason or summary.

## Conventions

- Map columns by header name through `sheet.yaml`, never by letter or index. The boss may reorder columns.
- Treat blank, "TBD", "n/a", and malformed dates as missing, not as errors. Log them.
- LLM outputs use pydantic schemas; validate, and on failure retry once, then skip the row and log it.
- Keep AI cell text short: summaries ≤ 200 characters, flag reasons ≤ 100.
- Type hints everywhere; `ruff` for lint and format.

## Verifying a change

- `uv run pytest` passes (tests use `FakeSheetClient`, no network).
- Run the command with `--dry-run` against the **demo sheet** (`SHEET_ID_DEMO`) and check the printed diff.
- Only then run it against the real sheet (`SHEET_ID`).
