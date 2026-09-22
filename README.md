# superintend

**Construction schedules slip in the gap between "someone asked" and "someone answered." This finds that gap in the tracker a team already uses, and says who's sitting on what.**

It reads the weekly Google Sheet a general contractor already keeps — no new tool, no migration, no training — and writes two columns back: a risk flag and one short next action. Later phases add a project brief, the weekly report email, a Q&A tab over project history, and an agent that investigates each flagged item before deciding whether it's really a problem.

Running live on an active Palisades Fire rebuild project: **280 items, 51 subcontractors, 39 weekly tabs, ~3,100 recorded edits.**

---

## Why it works this way

The superintendent I built this for is not going to adopt a new tool, and he's right not to. The tracker works. Every construction-software startup that has asked a GC to move off their spreadsheet has learned this the expensive way.

So the sheet stays the system of record. The agent writes into two new columns and three tabs of its own, touches nothing a human owns, and can be switched off without leaving a trace. **Adoption cost is zero by design** — that constraint drove every architectural decision below.

## What it does

`tracker flag` writes, per item:

- **A deterministic risk flag** — overdue, blocked, waiting on us too long, waiting on a sub too long, stale, missing a date, or internally inconsistent
- **One next action** from Claude, ≤100 characters — *"Call Jimmy today to confirm gas pipe crew arrival date; overdue since 8/31."*

The rules are plain Python, not a model: auditable, free, and backtestable. The LLM only writes the sentence a human reads, and it writes it from the item's own notes — which is why the next actions name the person and the date instead of saying "follow up."

A next action is regenerated only when the item's status, ball, due date, or notes actually changed. Otherwise the model paraphrases the same situation differently every night and churns the sheet for nothing. `--no-llm` runs the rules alone, no API key required.

**The tracker has two status columns, and both matter.** `STATUS` is the lifecycle (not started / in progress / completed). `DETAILS` is who holds the ball (waiting for response / need to respond / needs clarification / dependent on). Most of the useful signal lives in the second one, which is why the canonical model carries a separate `ball` field — and why a source adapter maps *both* onto it.

## Built against real mess, not a clean fixture

Things that only appeared when it ran on production data:

- **Duplicate rows.** Two rows sharing the exact subcontractor and item text within one week — seven times, including a three-way collision. Item ids hash `(project, group, title)` to stay stable across weeks, so these collide. Rather than guess they're the same task, each gets `⚠️ Duplicate — consolidate with row N` and a human resolves it on the sheet.
- **STATUS blank or wrong** while DETAILS carries the real signal. The parser infers the lifecycle state from DETAILS when it's unambiguous, and logs why when it isn't.
- **Tab naming drift** — `Wk 7/28`, `Wk of 8/18`, `wk 12/1`, stray `Copy of…` tabs, and a December-to-January rollover with no year anywhere in the name.
- **A blank header** over the date column.
- **Subcontractor names on the first row of each group only**, filled down visually by a human reading it.
- **Items that have been open for over a year.** One retaining wall is 400+ days past its date — a real slip, not a data artifact, and a reminder that "overdue" on a mature project is a distribution, not a binary.
- A batch response **silently truncated** by a default `max_tokens`, failing validation on every run until it was raised.

## Source-agnostic by design

Google Sheets is the first data source, not the architecture. Every feature is written against a `TrackerSource` interface over a canonical `Item` / `Change` model, with **capability flags** (`READ_ITEMS`, `READ_HISTORY`, `WRITE_ANNOTATIONS`, …) so features degrade rather than crash against a source that can't do something. A read-only CSV export still gets flags — they just arrive by email instead of in a column.

One contract test suite runs against every adapter. Adding a source means writing an adapter and passing that suite; no feature code changes. See `docs/adapters.md`.

## Measured, not asserted

The sheet's change log holds every edit since the project started, which means the tracker's own history can be replayed. **The flag rules will be backtested against five months of what actually happened**, against published baselines (flag nothing, flag everything not done, flag everything overdue) — if the rules don't clearly beat the one-line overdue rule, they're decoration, and that result gets published too.

The exact definitions — what counts as a "slip," the attribution window, the holdout split, how outliers are handled — are pinned in `docs/measuring-value.md` *before* the numbers exist, so results can't be tuned to flatter the tool afterward. Results land there and in `SPEC.md` as each phase ships.

## Is it an agent?

Not yet, deliberately. Today it's a scheduled pipeline with deterministic risk rules and LLM-written summaries, because the risk logic should be auditable and backtestable before anything gets to choose its own control flow.

Phase 7 adds the loop: the rules propose ~33 candidates out of 280 items, and an agent investigates each one with read-only tools — item history, related items, subcontractor responsiveness, note search, schedule context — before returning a verdict (confirm, downgrade, drop, or escalate) with evidence validated against what the tools actually returned. It never writes; deterministic code does.

`escalate` is the reason it's worth building: a rule only fires on what it was told to look for.

It will be measured against the rules on the same replay, per `docs/measuring-value.md`. **If it doesn't beat them, it ships off by default.**

## Status

| Phase | State |
|---|---|
| 0 — parsing, adapter interface, contract suite | ✅ live on the real sheet |
| 1 — `tracker flag` | ✅ live on the real sheet |
| 2 — AI Brief tab | next |
| 3 — weekly report email | |
| 4 — Q&A over tracker history, with citations | |
| 5 — backtest, eval, metrics | |
| 6 — second adapter (CSV) | |
| 7 — investigating agent, measured against the rules | |

Roadmap: `SPEC.md`. Conventions and guardrails: `CLAUDE.md`.

## Quickstart

```bash
uv sync
uv run tracker inspect                 # tabs, latest week, header row, column mapping (read-only)
uv run tracker flag --dry-run          # exact diff, writes nothing
uv run tracker flag --no-llm           # rules only, no API key
uv run pytest
```

Google Cloud / service account setup: `docs/setup.md`.

## Guardrails

1. **Writes are allow-listed** — only the AI columns on the *latest* weekly tab, plus fully agent-owned tabs (`AI Brief`, `Ask`'s answer columns, `AI Log`). Human columns A–F, title rows, older weekly tabs, and the change log are read-only. Enforced in one function, covered by a test.
2. `--dry-run` works for every write command and prints the exact diff.
3. **Uncertain parse → stop and log, never write.**
4. One batch update per run.
5. **No real project data in git** — `.env`, `credentials/`, `data/`, `out/`, `*.db` gitignored; every fixture uses invented names; the demo sheet is generated from fixtures rather than scrubbed from the real one, and every screenshot in this repo comes from the demo.
6. Answers cite a source, or say "Not found."
7. Every LLM call goes through one wrapper; deterministic logic runs first.

---

*Built by [Ben Mower](https://github.com/benjaminmower) — construction professional services, Los Angeles. The tracker this runs on is one I use at work.*
