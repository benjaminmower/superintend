# tracker-agent: MVP spec

## Goal

Add an AI layer to the existing Google Sheets weekly construction tracker **without changing how the team works**. The boss keeps reading the same sheet. The agent:

1. Flags at-risk items and writes a next action on each row
2. Writes a project brief (overall and per subcontractor) to its own tab
3. Drafts the weekly report and emails it
4. Answers questions from project documents **and the tracker's own history**, with citations, through an "Ask" tab

**Portfolio goal:** a public repo with a demo sheet of fake data, a README with architecture and tradeoffs, eval and backtest numbers, and usage metrics.

---

## The tracker as it exists today (observed)

**One spreadsheet per project.** Tab 1 is a change log; the other tabs are weekly snapshots.

### Weekly tabs
- One tab per week, made by duplicating last week's tab. Names are inconsistent: `Wk 7/28`, `Wk of 8/18`, `wk 12/1`. Stray tabs like `Copy of Wk 8/4` exist.
- Row 1 is a title ("<Company> Weekly Report - <address>"), followed by a header row. Data starts around row 4.
- Columns:

| Col | Header | Meaning | Values |
|---|---|---|---|
| A | SUBCONTRACTOR | Group label, **only on the first row of each group** (fill down) | Trade or company name; also "LA DBS" and the GC for its own tasks |
| B | ITEM | The task | free text |
| C | *(blank header)* | Target or completed date. The change log calls it `DATE` | M/D/YYYY, often blank |
| D | STATUS | Lifecycle | Not started, In progress, Completed, Blocked, Cancelled; sometimes a multi-select like "Blocked, Completed" |
| E | DETAILS | Who has the ball | Done!, On the schedule, Waiting for Response, Needs Clarification, Need to Respond, Seeking Approval, Reached out, No Answer – Followed Up, Cancelled |
| F | NOTES | Narrative | free text, often rich (decisions, inspector names, field changes) |

### Change log tab
`Timestamp, User, Sheet Name, Row, Column Name, Old Value, New Value, Item (Current), Subcontractor (Current)`. It's written by an edit trigger. On the real tracker this tab is named `Changelog` (no space) and holds ~3,079 rows since the project started — `changelog_tab: auto` detection (scanning every tab's header row) works but is expensive on a sheet with 39 tabs; set `changelog_tab` explicitly per spreadsheet once you know the name (see Phase 0 notes).

**Why this matters:** the change log gives us history for free. We use it for staleness, "what changed this week", time spent in each status, and replaying the sheet on past dates to backtest. **No snapshot-diffing is needed.**

**Note:** edits made through the Sheets API don't fire `onEdit` triggers, so the agent's own writes won't pollute the change log. That's good, but it also means the agent's changes need their own audit trail (`run_log` plus an AI Log tab).

**Real-sheet quirks found once Phase 1 ran against production data (not visible in the demo's small fixture):**
- **STATUS is sometimes blank or wrong** while DETAILS still carries the real signal (e.g. STATUS blank + DETAILS="Cancelled"; or a DETAILS value like "Reached out" typed into STATUS by mistake). The parser infers STATUS from DETAILS when DETAILS unambiguously implies a lifecycle state (`Cancelled`, `Done!`); otherwise it falls back to `not_started` and logs why.
- **Duplicate (SUBCONTRACTOR, ITEM) rows exist within one week** — the same task re-entered, or a genuinely different task that happens to share the exact same title and sub (observed 7 times on the real tracker, including one three-way collision). Since `item_id()` hashes `(project, group, title)` to stay stable across weeks, these collide onto one id. The parser warns loudly (`ParseWarning`, visible on `inspect`/`--dry-run`); `flags.py`/`write_annotations()` never guesses a shared flag for colliding rows — each gets `⚠️ Duplicate — consolidate with row N[, M]` in `AI Flag` and a blank `AI Next Action` instead, so a human resolves it on the sheet.

---

## Portability: the tracker is an adapter

Google Sheets is the first source, not the design. Everything above the `TrackerSource` interface (flags, brief, report, backtest, RAG) works on the canonical `Item` / `Change` model defined in `CLAUDE.md`. Swapping trackers means writing one adapter and passing the contract suite.

**Adapters, roughly in order of effort:**

| Source | How | Notes |
|---|---|---|
| **Google Sheets** (MVP) | gspread | The messiest one. Doing it first proves the interface survives real-world mess. |
| **Fake** | in-memory | Ships with the repo; powers all tests and the demo. |
| **CSV / Excel export** | pandas | The universal fallback: nearly every tracker exports one. Read-only, so `WRITE_*` capabilities are off and output goes to email. |
| **Airtable / monday / Smartsheet** | REST API | Closest in shape to the sheet: rows, a status field, an owner, and a change history. |
| **Procore / Buildertrend / Fieldwire** | REST API, OAuth | The real industry targets. Richer objects (RFIs, submittals, punch items, daily logs), so the adapter flattens each into `Item` with `group` = trade or spec section. Check API access tier and sandbox availability before committing; Procore has a developer sandbox. |
| **MS Project / P6 XER** | file parse | Schedule-shaped, not task-shaped. Read-only; `Item.due_date` = the activity's early finish. |

**Adapter checklist** (in `docs/adapters.md`, written during Phase 0 and followed for each new source):
1. Declare capabilities.
2. Map the source's vocabulary to `status` and `ball` in `sources.yaml`.
3. Give each item a stable `id` (the Sheets adapter hashes normalized (sub, item), because row numbers move).
4. Implement `health()` so a bad parse or an expired token stops the run instead of writing junk.
5. Pass `tests/contract/`.
6. Record rate limits and pagination in the adapter's docstring.

**Push vs. pull:** the MVP polls. Adapters with `WEBHOOKS` can later feed the same handlers; nothing above the interface changes.

**The resume value is exactly this seam.** "Built a tracker-agnostic agent with a capability-based adapter layer; added Procore in ~200 lines and no changes to the feature code" is a stronger line than any single integration. Keep the adapter diff small and show it in the README.

## Non-goals (MVP)

- No web UI and no new tools for the boss to learn
- No edits to human-owned cells (A–F), the title row, or the change log
- No messages sent to subs, inspectors, or clients. The weekly email goes to Bronco (and the boss once approved) only
- No multi-user auth; one service account

## Architecture

```
Project spreadsheet
  ├─ Change log tab   ──read──┐
  ├─ wk M/D tabs      ──read──┤   tracker-agent (Python CLI, launchd/cron)
  │    └─ AI cols G–H <─write─┤     ├─ parse: latest tab, fill-down, normalize
  ├─ AI Brief tab     <─write─┤     ├─ flag / next-action / brief / report
  ├─ Ask tab          <─r/w──┤     ├─ rag: docs + tracker history → SQLite FTS5 → Claude
  └─ AI Log tab       <─write─┘     └─ state.db (run_log, chunks, parsed history)
Drive folder (plans, specs, LADBS, soils reports) ──read──┘
SMTP (Gmail app password) <── weekly report
```

**Retrieval:** SQLite FTS5 (BM25) first. Questions here are full of exact tokens (sheet numbers, sub names, "bottom inspection", "recompaction"), which keyword search handles well. Add embeddings only if the eval shows misses. This decision goes in the README.

---

## Phase 0: Setup and parsing

**Tasks**
- Scaffold the repo per `CLAUDE.md`
- Google Cloud service account; enable the Sheets and Drive APIs; share the spreadsheet and docs folder with the service account. Claude Code writes `docs/setup.md` with the steps; Bronco does the console work
- **Demo spreadsheet:** a copy with invented subs, address, and notes, but the same structure, tab-naming mess, and change log format. All development runs against it
- `tracker inspect`: list the tabs, classify each (`weekly`, `changelog`, `ignored`, `other`), print the detected latest weekly tab, header row index, column mapping, and group and item counts
- **Weekly tab parser**
  - Regex (case-insensitive): `^\s*(wk|week)\s*(of\s*)?(\d{1,2})/(\d{1,2})\s*$`. Ignore `Copy of …`
  - Resolve the year: walk tabs in order, and when the month goes backwards, increment the year (7/28 … 12/29 → 1/5 is the next year). `settings.yaml` can override
  - Find the header row by searching the first 10 rows for a row containing `SUBCONTRACTOR` and `ITEM`
  - Map columns by header, **with a positional fallback for the blank-header DATE column** (the column between ITEM and STATUS). Also suggest that Bronco type `DATE` into that header cell himself
  - Fill SUBCONTRACTOR down; skip fully blank rows
  - Normalize values: multi-select → last value ("Blocked, Completed" → Completed, and log a warning); trim; parse dates; treat blank, TBD, and n/a as missing
  - Output: `list[Item]` with `sub, item, date, status, details, notes, tab, row`
- **Change log parser** → `list[Change]`; match changes to items by `(Subcontractor (Current), Item (Current))`, normalized, because row numbers shift between weeks

`config/sheet.yaml`:
```yaml
spreadsheets:
  - project_id: project-1            # slug; keep real project names out of the public repo; used in the Ask tab and RAG filters
    sheet_id_env: SHEET_ID           # real ID lives in .env
    changelog_tab: "Changelog"       # optional per-spreadsheet override of changelog_tab below
changelog_tab: auto                  # default when a spreadsheet has no override; detect by
                                      # header "Timestamp, User, Sheet Name" (expensive on a
                                      # sheet with many tabs — set an override once known)
weekly_tab_regex: '^\s*(wk|week)\s*(of\s*)?(\d{1,2})/(\d{1,2})\s*$'
ignore_tab_regex: '^copy of'
columns:
  sub: SUBCONTRACTOR
  item: ITEM
  date: {header: DATE, fallback_after: ITEM}
  status: STATUS
  details: DETAILS
  notes: NOTES
ai_columns:                          # appended right of NOTES on the latest weekly tab ONLY
  flag: "AI Flag"
  next_action: "AI Next Action"
agent_tabs: ["AI Brief", "Ask", "AI Log"]   # fully agent-owned
done_status: [Completed, Cancelled]
done_details: ["Done!", Cancelled]   # DETAILS values meaning nobody holds the ball
ball_in_our_court: [Need to Respond, Needs Clarification, Seeking Approval]
waiting_on_others: [Waiting for Response, Reached out, "No Answer – Followed Up", "Dependent On"]
```

**Done when:** `inspect` correctly parses every weekly tab in the demo and real sheets (the item counts are plausible, no unmapped columns); tests cover tab-name variants, fill-down, year rollover, and multi-select cleanup. ✅ Done — verified against both the demo and the real 280-item, 51-subcontractor, 39-tab production sheet.

## Phase 1: Flags and next action (inline, on the latest weekly tab)

**Deterministic rules**, evaluated per item; thresholds in `settings.yaml`:

| Flag | Rule |
|---|---|
| 🔴 Overdue | `date` < today and status not in `done_status` |
| 🔴 Blocked | status = Blocked |
| 🟠 Our move | details in `ball_in_our_court` for > `our_move_days` (default 2) per the change log |
| 🟡 Chase | details in `waiting_on_others` for > `chase_days` (default 4) |
| 🟡 Due soon | `date` within `due_soon_days` (7) and status = Not started |
| 🟡 Stale | no change-log entry for this item in `stale_days` (10) and not done |
| ⚪ Needs date | not done and no date |
| ⚪ Inconsistent | status Completed but details ≠ Done!, or the reverse |

- The rules pick the flag (worst one wins). Claude writes **one** `next_action` line (≤ 100 chars) from the item, its notes, the triggered rules, and its last 3 change-log entries. Example shape: "Text <sub> for the sewer connection answer; waiting 6 days."
- Rows with no flag and a done status get a blank next action
- Writes go only to `AI Flag` and `AI Next Action`, in one batch (alongside one appended `AI Log` row — still one Sheets API call total). No cell background color in v1; the emoji carries severity
- Because tabs get duplicated weekly, AI columns may carry forward from last week. Every run clears and rewrites these two columns on the latest tab, so stale text never survives a run
- **Next actions are cached by fingerprint**, not regenerated every run: a `flag_state` table (`project_id, item_id, fingerprint, next_action`) keys on `(chosen flag, status, ball, due_date, notes)`. An item whose fingerprint hasn't changed since the last real (non-dry-run) write reuses its stored `next_action` text instead of calling the LLM again — otherwise the model paraphrases the same situation differently every run, and a rerun with nothing changed would still churn every next-action cell. `--dry-run` never reads or writes this state.
- **Duplicate items:** if two rows on the same tab share `(SUBCONTRACTOR, ITEM)` text, `item_id()` (a hash of that pair, meant to stay stable week to week) can't tell them apart. Rather than guess a shared flag/next-action for what may be genuinely different tasks, every row sharing a collided id gets `⚠️ Duplicate — consolidate with row N[, M]` in `AI Flag` and a blank `AI Next Action`. `inspect`/`--dry-run` surface a `ParseWarning` for each collision so it's visible before any write.
- The AI headers (`AI Flag`, `AI Next Action`) are added to the real sheet by hand, once, right of NOTES — `flag` never writes a header row. If they're missing, it stops with an actionable message rather than guessing where to put them.

**Done when:** unit tests cover each rule with an injected `today`; a dry run on the demo shows the flag counts and a sample of next actions; the allow-list test proves A–F can't be written. ✅ Done — 93 tests passing; verified end-to-end with a real, non-dry-run write against the production sheet (70 cells written across 33 flagged items + 7 duplicate-consolidation groups).

**Bugs found only by running against real data** (worth remembering for later phases — the demo's small, clean fixture didn't surface any of these):
- `call_llm`'s default `max_tokens=1024` silently truncated a 20-item next-action batch's JSON response, failing validation on every run until raised.
- A prompt that doesn't explicitly demand JSON output gets prose back from the model; `call_llm` itself does no format-enforcement, so every caller has to spell it out in the system prompt.
- `--dry-run` must never require state that only a real write needs (e.g. it was crashing on a missing `AI Log` tab even though dry-run never touches that tab).

## Phase 2: AI Brief tab

A fully agent-owned tab, rewritten every run:
- **Project snapshot** (3–5 sentences): phase, what moved this week, the top risks, and the next inspection or milestone
- **By subcontractor** table: sub | open items | worst flag | one-line status | last activity date
- **Waiting on** list: grouped by who has the ball (us vs. each sub vs. the city)
- **Cycle stats** from the change log: median days items sit in "Waiting for Response" per sub, and items completed this week
- A footer: "Generated <timestamp> from tab <wk M/D>. Read-only; edit the weekly tab, not this one."

**Done when:** the brief on the demo sheet reads correctly to a person who hasn't seen the tracker.

## Phase 3: Weekly report email (and optional week rollover)

- `tracker report` drafts the weekly report the tracker title already implies: a narrative summary, completed this week (from the change log), in progress, blocked or at risk with reasons, and upcoming dates for the next 14 days
- Claude writes the narrative; everything else is templated (Jinja2 → HTML + plain text)
- SMTP via a Gmail app password; the recipients list starts as **Bronco only**
- Schedule: Friday 7am PT

**Optional `tracker roll-week`** (dry-run by default; needs `--apply`): duplicate the latest weekly tab as `wk M/D` for the coming Monday, clear the AI columns, and keep the structure identical. It never deletes items; the humans decide what to prune. This saves the weekly copy-and-rename chore and fixes the tab-naming drift.

**Done when:** `--dry-run` writes `out/report-YYYY-MM-DD.html`; Bronco approves a test send before the boss is added.

## Phase 4: RAG "Ask" tab

**Sources**
1. **Drive docs:** plans, specs, LADBS corrections, soils and compaction reports, permits. Structure: `/<project_id>/{plans,specs,city,reports}`
2. **Tracker history:** every item's notes across all weekly tabs, plus the change log, indexed as dated chunks (`project, sub, item, tab/week, date`). This answers questions like "When did the bottom inspection pass?", "What did we decide about the garage footings?", and "What's the history with the sewer connection?"

**Ingest** (`tracker ingest`)
- PDFs: pymupdf per page; chunk by page, then by heading, CSI section (`\d{2} \d{2} \d{2}`), or sheet ID (`[A-Z]{1,2}-?\d{3}`), about 800 tokens. Detected sections go into metadata. Pages with less than 50 characters of text are logged as "needs OCR"
- Tracker history: one chunk per (item, week) with the notes text, plus change events; de-duplicate identical notes carried forward across weeks and keep the first and last week each note was seen
- Re-ingest only changed files (Drive `modifiedTime`) and new weeks

**Answer**
- FTS5 BM25 with an optional project filter, top 8 chunks → Claude answers only from those chunks. The schema is `{answer, citations[{source, page|week, section?}], confidence: high|medium|low|not_found}`
- Validate the citations against the retrieved chunks; drop any that don't match and lower the confidence
- No support in the chunks → "Not found in project documents or tracker history"

**Ask tab:** `Question | Project | Answer | Sources | Confidence | Status | Asked | Answered`. `tracker watch` polls every 60s for a filled Question with a blank Status. `tracker ask "…"` is the CLI version.

**Done when:** 10 hand-checked questions (5 from docs, 5 from tracker history) return correct citations, and out-of-scope questions return not-found.

## Phase 5: Eval, backtest, metrics, README

**RAG eval:** `evals/questions.yaml` with 30–50 items of types `lookup | history | code | cross-source | not_found`. Measure retrieval hit@8, citation accuracy, answer correctness (keyword match + a Claude-as-judge pass), and not-found precision. The real-data eval stays private; the public repo uses the demo. If hit@8 is below ~85%, add embeddings (hybrid) and record the before and after numbers.

**Flag backtest** (the strongest resume piece): use the change log to rebuild the tracker's state on every Monday from Aug to Dec 2025, run the flag rules as of that date, and check the outcomes. Did 🔴/🟠 items actually slip (their date moved, or they finished late)? Were items that slipped flagged beforehand? Report precision and recall and the lead time in days, then tune the thresholds from it.

**Metrics** (`tracker stats` from `run_log`): runs, items flagged by type, next actions written, questions answered, tokens and $ per week, and an estimated hours saved (configurable minutes per task × count).

**README:** the problem, demo-sheet screenshots (before and after), the architecture diagram, guardrails, the eval and backtest tables, the BM25-vs-embeddings decision, and weekly cost.

---

## Phase 6: Prove the seam (second adapter)

Do this once Phases 1–3 are working, not at the end. It's the phase that turns a one-off script into a portfolio piece.

1. **CSV adapter first** (a day's work): read an exported tracker into `Item`s, declare `READ_ITEMS` only, and confirm the flags and report still run with `WRITE_*` and `READ_HISTORY` off. This is what flushes out the hidden Sheets assumptions.
2. **Then one real API** — Procore's sandbox if you can get access, otherwise Airtable or monday, both of which have free tiers and quick auth.
3. Record the numbers for the README: lines of adapter code, how many feature files changed (the target is zero), and time to first working run.
4. `tracker sources` lists the registered adapters with their capabilities; `--source csv` overrides the active one per run.

**Done when:** the same commands produce a correct brief and report from two different sources, and the contract suite passes for both.

## Stretch

- Plan check intake: an LADBS correction PDF → items on a new agent-owned tab
- Multiple projects: several spreadsheets in `sheet.yaml`, one combined report
- Sub responsiveness scorecard from the change log
- OCR for scanned plan sheets; cloud deploy (Cloud Run + Scheduler)

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Tab naming drift or new layouts | Regex + header detection; `inspect` warns and **stops writes** if the latest tab can't be parsed confidently |
| Agent overwrites human data | Allow-list: AI columns on the latest weekly tab + agent-owned tabs only, enforced in one function and tested |
| Stale AI text copied into the new week's tab | Clear and rewrite the AI columns every run; `roll-week` clears them |
| Change log row numbers don't match after duplication | Join on (sub, item), not row |
| Two rows share (sub, item) text within one week | Warn loudly (`inspect`/`--dry-run`); write a "consolidate with row N" flag to each instead of guessing a shared next_action |
| Hallucinated answers | Chunk-only answering, citation validation, a not-found path, the eval |
| Real names and address leaking | Demo spreadsheet for the repo; gitignored `data/`; fake fixtures |
| The sheet is shared "anyone with the link" | Recommend restricting sharing to named people plus the service account |
| Laptop asleep | launchd catches up missed runs; cloud deploy is a stretch goal |

**Before anything writes to the real sheet:** confirm with the boss that project data can be sent to the Anthropic API and that two AI columns plus three tabs are OK to add. ✅ Done — confirmed; Phase 1 is live on the real tracker.

---

## Kickoff prompt for Claude Code

> Read CLAUDE.md and SPEC.md, including "The source boundary" and "Portability". We're doing Phase 0 only. Scaffold the repo per the Layout, write `docs/setup.md` (service-account steps for me) and `docs/adapters.md` (the adapter checklist), then implement `core/models.py`, `core/capabilities.py`, `sources/base.py`, `sources/fake.py`, `config.py`, the gsheets adapter (client, weekly parser, changelog parser, allow-listed writer), the contract test suite in `tests/contract/`, and `tracker inspect`. Build test fixtures that mimic the structure described in "The tracker as it exists today", with invented names. Include tests for tab-name variants, year rollover, SUBCONTRACTOR fill-down, the blank DATE header fallback, and multi-select status cleanup. Stop after Phase 0 and tell me what to do in the Google console.

For each later phase: "Phase N per SPEC.md. Show me the plan first, then implement with tests, and dry-run against the demo sheet before finishing."
