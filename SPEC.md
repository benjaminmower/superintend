# tracker-agent: MVP spec

## Goal

Add an AI layer to the Google Sheets project tracker for construction
professional services, **without changing how the team works**. The boss
keeps using the same sheet. The agent:

1. Writes a daily status summary and next action for each project row
2. Flags at-risk rows with a short reason
3. Emails a plain-English weekly digest
4. Answers questions from project documents (specs, plans, LADBS plan
   check, Title 24) with citations, through an "Ask" tab

**Portfolio goal:** a public repo with a demo sheet of fake data, a README
with architecture and tradeoffs, an eval with real accuracy numbers, and
usage metrics.

## Non-goals (MVP)

- No web UI and no new tools for the boss to learn
- No edits to human-owned cells
- No autonomous sending of RFIs or emails to subs or clients (the weekly
  digest to the boss is the only outbound message)
- No multi-user auth; one service account and one sheet

## Architecture

```
Google Sheet (tracker)  <--gspread-->  tracker-agent (Python CLI, run by cron/launchd)
   |  Projects tab (human columns + AI columns)          |-- summarize / flag / digest
   |  Ask tab (Question | Answer | Sources | Status)     |-- watch (polls Ask tab)
   |  AI Log tab (run history, optional)                  |-- rag: ingest -> SQLite FTS5 -> Claude
Google Drive folder (project docs: PDFs)  ---------------+
SMTP (Gmail app password)  <-- weekly digest
```

- **Scheduling:** macOS `launchd` (or cron) on Bronco's machine for the
  MVP. Cloud deploy is a stretch goal.
- **State:** `data/state.db` (SQLite) holds row snapshots (for staleness),
  the run log, and document chunks.
- **Retrieval:** start with SQLite FTS5 (BM25). Construction questions are
  full of exact tokens like sheet numbers ("A-501"), spec sections
  ("06 10 00"), and code sections, and keyword search handles those well.
  Add embeddings only if the Phase 5 eval shows retrieval misses. This is
  a deliberate tradeoff to document in the README.

Work one phase at a time, in order. Do not start a phase until the
previous one's "Done when" criteria are met and the user has confirmed.

## Phase 0: Setup and sheet discovery

**Tasks**
- Scaffold the repo per `CLAUDE.md` (uv, ruff, pytest, typer CLI,
  `.gitignore`, `.env.example`)
- Google Cloud project, service account, enable Sheets and Drive APIs;
  share the tracker and docs folder with the service account email
  (Bronco does the console steps; instructions live in `docs/setup.md`)
- Make a **demo copy** of the tracker with fake projects, used for all
  development
- `tracker inspect`: list tabs, headers, row count, and 3 sample rows (the
  sample rows are printed to the terminal, never saved)
- Generate a draft `config/sheet.yaml` from the headers; Bronco edits it
  to map meaning:

```yaml
tab: Projects
key_column: "Project"          # unique row id
columns:                        # semantic name -> header text in the sheet
  project: "Project"
  address: "Address"
  phase: "Phase"
  status: "Status"
  next_milestone: "Next Milestone"
  milestone_date: "Target Date"
  notes: "Notes"
  permit_status: "Permit"
  inspection_next: "Next Inspection"
ai_columns:                     # the ONLY columns the agent may write; created if missing
  summary: "AI Summary"
  next_action: "AI Next Action"
  flag: "AI Flag"
  flag_reason: "AI Flag Reason"
  updated: "AI Updated"
```

**Done when:** `inspect` runs against the demo and real sheets;
`sheet.yaml` is filled in; `pytest` runs green with `FakeSheetClient`.

## Phase 1: Status summary column

**Behavior**
- For each row, build a compact text of the mapped columns and call
  Claude with a pydantic schema: `{summary: str <=200, next_action: str <=120}`
- Skip rows whose snapshot hash hasn't changed since the last run (saves
  tokens); `--force` re-runs all
- Write `AI Summary`, `AI Next Action`, and `AI Updated` in one batch
  update

**Prompt rules:** plain language a superintendent would use; state facts
from the row only; if information is missing, say what's missing ("No
target date set") instead of inventing one.

**Done when:** a dry run shows sensible diffs on the demo sheet; unchanged
rows are skipped; a guard test proves writes to non-AI columns raise an
error.

## Phase 2: Risk flags

**Deterministic rules** (in `settings.yaml`, all thresholds configurable):

| Flag | Rule |
|---|---|
| Overdue | `milestone_date` is in the past and status isn't complete |
| Due soon | `milestone_date` within `due_soon_days` (default 7) |
| Stale | row hash unchanged for `stale_days` (default 10), based on the snapshot history |
| Missing data | key fields blank (target date, next milestone) |
| Inspection risk | next inspection within 3 days and notes mention an open blocker |

- The rules decide the flag; Claude only writes `flag_reason` (<=100
  chars), using the row plus the triggered rules
- Apply background color to the `AI Flag` cell only (red/yellow/none)
- An LLM-only "soft risk" check on the notes text (e.g., "waiting on
  engineer", "sub no-show") -> yellow flag with reason. Can be turned off
  with `llm_soft_flags: false`

**Done when:** unit tests cover each rule with fixed dates (inject a
`today` value); the dry run lists the flag counts.

## Phase 3: Weekly digest email

**Behavior**
- `tracker digest` builds an email: counts by flag, top 5 risks with
  reasons, what changed this week (from snapshot diffs), and upcoming
  inspections and milestones for the next 14 days
- Claude writes a 3-5 sentence opening summary; everything else is
  templated (Jinja2 -> simple HTML + plain-text fallback)
- Sent via SMTP with a Gmail app password; recipients are listed in
  `settings.yaml`
- A "Sent by tracker-agent, read-only summary of <sheet link>" footer
- Schedule: Fridays at 7am PT via launchd

**Done when:** `--dry-run` writes `out/digest-YYYY-MM-DD.html` for review;
a test send goes to Bronco only before the boss is added.

## Phase 4: RAG "Ask" tab

**Ingest** (`tracker ingest`)
- Source: a Drive folder set in settings, with subfolders per project
  (e.g., `/<Project>/specs`, `/plan-check`, `/code`)
- Download PDFs, extract text per page with pymupdf, and keep metadata:
  `project, doc_name, page, doc_type`
- Chunking: split by page, then by heading or spec section where
  detectable (regex for CSI sections like `\d{2} \d{2} \d{2}`, sheet IDs
  like `[A-Z]{1,2}-?\d{3}`); ~800 tokens with overlap. Store the detected
  sheet and section numbers as chunk metadata
- Re-ingest only files whose Drive `modifiedTime` changed
- Note: scanned drawings have little extractable text. Log pages with
  less than 50 characters as "needs OCR" (OCR is a stretch goal)

**Retrieve and answer**
- The query goes to FTS5 BM25, filtered by project if the question names
  one -> top 8 chunks
- Claude answers **only** from the provided chunks, with a schema of
  `{answer, citations: [{doc_name, page, section?}], confidence: high|medium|low|not_found}`
- If the chunks don't contain the answer, the answer is "Not found in
  project documents"
- Citations are validated: each must match a chunk that was actually
  retrieved; drop any that don't and lower the confidence

**Ask tab**

| Question | Project (optional) | Answer | Sources | Confidence | Status | Asked | Answered |
|---|---|---|---|---|---|---|---|

- `tracker watch` polls every 60s for rows where Question is filled and
  Status is blank, answers them, and sets Status = `answered` (or
  `error`). The Ask tab's Answer through Answered columns are agent-owned
- `tracker ask "..."` does the same from the CLI for testing

**Done when:** 10 hand-checked questions on the demo docs return correct
citations; "not found" behavior is verified on questions that are out of
scope.

## Phase 5: Eval, metrics, portfolio polish

**Eval** (`evals/questions.yaml`, 30-50 items, written from REAL project
docs but kept out of the public repo; a public version uses the demo docs)

```yaml
- q: "What is the required edge nailing for the shear wall on sheet S-201?"
  project: demo-1
  expect_source: {doc_name: "structural.pdf", page: 4}
  expect_answer_contains: ["8d", "4\" o.c."]
  type: lookup            # lookup | code | cross-doc | not_found
```

- Metrics: retrieval hit@8 (the expected source is in the retrieved
  chunks), citation accuracy, answer correctness (keyword match + a
  Claude-as-judge pass), and the not-found precision
- `tracker eval` prints a table and saves `evals/results/<date>.json`
- **Decision point:** if hit@8 is below ~85%, add embeddings (hybrid BM25
  + vector) and re-run. Record before and after numbers

**Metrics** (`tracker stats`, from `run_log`): runs, rows summarized,
flags raised by type, questions answered, tokens and $ cost, and an
estimated hours saved (configurable minutes-per-task x count)

**README:** the problem, a screenshot of the demo sheet, the architecture
diagram, the guardrails, the eval table, the BM25-vs-embeddings decision,
and cost per week

---

## Stretch (after MVP)

- Plan check intake: drop an LADBS correction PDF into Drive -> one
  tracker row per correction, with owner and due date (writes to a new
  agent-owned tab, not to Projects)
- Submittal log generation from spec sections
- OCR for scanned drawings; sheet-index extraction from title blocks
- Deploy to Cloud Run plus Cloud Scheduler so it doesn't depend on the
  laptop being awake

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Boss edits or reorders columns | Header-based mapping; `inspect` warns on mapping drift and stops writes |
| Agent overwrites human data | `ai_columns` allow-list enforced in one write function, plus a test |
| Hallucinated code or spec answers | Answers only from retrieved chunks; citation validation; "not found" path; eval |
| Client data leaking into the public repo | Demo sheet and docs; gitignored `data/`; fake fixtures only |
| Laptop asleep -> no runs | launchd catches up missed runs; Cloud Run is a stretch goal |
| Cost creep | Skip unchanged rows; log tokens; weekly cost in `stats` |

**Before Phase 1 touches the real sheet:** confirm with the boss that
project data can be sent to the Anthropic API.

## Guardrails (non-negotiable, apply to every phase)

1. Never write to a column not listed under `ai_columns` in `sheet.yaml`.
   All writes go through `sheets.write_ai_cells()`, which enforces this.
2. `--dry-run` must work for every write command: prints the diff, writes
   nothing.
3. Batch writes — one `batch_update` per run, never per cell.
4. No real project data in git: not in tests, fixtures, evals, README, or
   commit messages. `.env`, `credentials/`, `data/`, `*.db` are gitignored.
   Fixtures use invented projects and addresses.
5. RAG answers must cite a source or say "Not found in project documents."
6. Every LLM call goes through `llm.py` so tokens/latency/cost are logged
   to `run_log`.
7. Deterministic logic first, LLM second.
