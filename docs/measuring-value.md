# Measuring value

How this project proves it works. Definitions are pinned here **before** results exist, so the numbers can't be tuned to flatter the tool afterward.

**The rule:** every definition in this doc is frozen once the first backtest runs (Phase 5). Changing one later means re-running everything and saying so in the README.

This doc is binding on how Phase 3 (report), Phase 5 (backtest), and Phase 7 (agent) get *measured* — it doesn't mean those phases exist yet. See `SPEC.md` for the implementation plan.

---

## 0. The baseline that expires — do this first

**Time your weekly report, by hand, for the next 3 weeks.** Start a timer when you begin assembling it, stop when you send it. Log it in `metrics/manual-baseline.csv` (gitignored — real project timing/notes, never published raw; only aggregated numbers go in the README):

```csv
date,minutes,items_reviewed,notes
2026-09-25,47,280,"chased 3 subs for status first"
```

Everything else in this doc can be reconstructed from the Changelog later. **This can't.** The moment Phase 3 ships, the before-state is gone forever.

Same idea, cheaper: note roughly how long you spend each week scanning the tracker for what needs attention, separate from writing the report.

---

## 1. Accuracy (backtest) — free, historical, most credible

Replay every Monday from the Changelog (3,079 change events), run the rules as of that date, and compare against what actually happened next.

### The slip definition (frozen)

An item **slipped** if, at any point after the evaluation Monday:

1. its `DATE` moved to a later date, **or**
2. it reached `Completed` after its `DATE`, **or**
3. it went to `Blocked` or `Cancelled` from any non-done state, **or**
4. it received no Changelog entry for > 14 days while not done.

Items already `Completed` or `Cancelled` on the evaluation Monday are excluded from both numerator and denominator.

**Attribution window:** a flag counts as predicting a slip only if the slip occurs within **28 days** of the flag. Later than that and the flag wasn't the reason anyone acted.

> Write the exact function into `backtest.py` as `did_slip(item, as_of)` and never edit it without re-running and noting the change in the README.

### Metrics

| Metric | Definition | Why it matters |
|---|---|---|
| **Precision** | flagged ∧ slipped ÷ flagged | Low precision = noise the boss learns to ignore. The number that decides whether it gets used. |
| **Recall** | flagged ∧ slipped ÷ slipped | Low recall = it misses what matters. |
| **Median lead time** | days between first flag and the slip | **The money metric.** 2 days is a notification; 10 days is a schedule you can still change. |
| **Noise rate** | false flags per week | Report absolute, not just a rate — "6 bad flags a week" lands harder than "78% precision". |
| **Per-rule breakdown** | precision/recall for each rule | Some rules will be worthless. Cutting them is a result worth reporting. |

### Baselines to beat (report all three)

1. **Flag nothing** — the do-nothing floor.
2. **Flag everything not done** — trivially 100% recall; its precision is the bar your precision must clear.
3. **Flag everything overdue** — the one-line rule anyone could write in a spreadsheet formula.

**If the rules don't beat #3 by a clear margin, they're decoration.** Publish the comparison either way; showing the naive baseline is what makes the real number believable.

### Threshold tuning — and the honesty rule

Thresholds (`stale_days`, `chase_days`, `our_move_days`) get tuned against the backtest. That is legitimate, but it means the tuned numbers are **fit to this data**.

- Hold out the **last 6 weeks** as a test set. Tune on the rest, report on the holdout.
- Report both: "tuned on Aug–Nov, validated on Dec–Jan."
- Anyone technical will ask this. Having the answer ready is worth more than a higher number.

---

## 2. Agent vs. rules (Phase 7)

Run the agent over the same replay. The rules provide the baseline for free.

| | Rules only | Rules + agent |
|---|---|---|
| Precision | baseline | ? |
| Recall | baseline | ? |
| False positives / week | baseline | ? |
| Median lead time | baseline | ? |
| Cost / week | ~$0 | $? |

Agent-only numbers:

- **Correct drops:** rule false positives the agent removed ÷ all rule false positives.
- **Bad drops:** real slips the agent dropped. **Weight this heavily** — a missed real risk costs far more than one noise flag.
- **Escalations:** how many `escalate` verdicts were warranted, judged by you against what happened. Small n is fine; describe them individually.

**Publish this even if the agent loses.** "No measurable gain over the rules at $0.60/week, so it ships off by default" is a stronger credibility signal than a project where the AI always wins. If it loses, say which of the four decision types failed and why.

---

## 3. RAG accuracy (Phase 4/5)

From `evals/questions.yaml`, 30–50 questions across `lookup | history | code | cross-source | not_found`:

- **Retrieval hit@8** — is the expected source among the retrieved chunks. Below ~85% → add embeddings and report before/after.
- **Citation accuracy** — cited sources actually contain the answer.
- **Answer correctness** — keyword match plus a Claude-as-judge pass; spot-check the judge against your own grading on 10 items.
- **Not-found precision** — of out-of-scope questions, how many correctly returned "not found" instead of inventing something. **Report this prominently.** Willingness to say "I don't know" is the trust metric.

---

## 4. Usage and cost — automatic, from `run_log`

- Runs attempted / succeeded; parse warnings over time (a reliability trend)
- Items processed, flags by type, next actions written, questions answered
- Tokens and dollars, rolled up to **one sentence: "runs for about $X/month"**
- Cache hit rate on the fingerprint cache — what share of items skipped an LLM call

Stating the cost is what makes the rest believable. Most portfolio projects never mention it.

---

## 5. Human value — has to be collected deliberately

The part everyone hand-waves. Keep it small and real.

| What | How | When |
|---|---|---|
| **Report prep time** | the manual baseline above vs. timed prep after Phase 3 | before + after |
| **Action rate** | add a temporary column: did this flag cause anyone to do something that week? | 1 month |
| **Catch log** | `metrics/catches.md` — items surfaced that you'd have missed, one paragraph each | ongoing |
| **The turn-off question** | ask your boss after a month: "if I switched this off, would you notice?" | month 1 |

**The catch log is the most valuable artifact here.** Five concrete stories — what the item was, why it was missed, what it would have cost — beat any percentage in an interview. Write each one the week it happens, while the detail is fresh.

---

## 6. What this adds up to

The README headline, once the numbers exist:

> Flags at-risk items with **X% precision** and a **Y-day median lead time**, backtested across 5 months and 3,079 change events on a live LA new-construction project. Cuts weekly report prep from **A to B minutes**. Runs for about **$Z/month**.

Specific, falsifiable, and it says what it costs.

### Honesty rules for reporting

1. **No cherry-picked window.** Report the full backtest period, and call out anything unusual (a holiday shutdown, a permit delay that stalled everything).
2. **Report the losses.** Rules that didn't work, the agent phase if it doesn't beat the baseline, questions the RAG got wrong.
3. **Name the sample size.** One project, one GC, five months. Don't generalize past it.
4. **Separate backtest from live.** Backtested precision and observed precision are different claims. Label which is which everywhere.
5. **No real project data in the public repo** — numbers and anonymized examples only, per guardrail #6.

---

## Collection schedule

| When | Do |
|---|---|
| **This week** | Start the manual report-time baseline (3 weeks) |
| **Now → ongoing** | Catch log, whenever something surfaces |
| **Phase 3 ships** | Time the assisted report prep for 3 weeks |
| **Phase 5** | Freeze `did_slip()`, run the backtest, holdout validation, publish tables |
| **Phase 7** | Same replay with the agent; fill the comparison table |
| **Month 1 live** | Action-rate column for 4 weeks; ask the turn-off question |
