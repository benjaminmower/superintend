# Adding a TrackerSource adapter

The tracker is an adapter. Everything above `TrackerSource`
(`src/tracker_agent/sources/base.py`) — flags, brief, report, backtest,
RAG — is written against the canonical `Item`/`Change` model in
`core/models.py`, never against a source's native shape. Swapping
trackers means writing one adapter and passing `tests/contract/`.

## Checklist

1. **Declare capabilities.** Set `capabilities: Capability` on your class
   (see `core/capabilities.py`) to exactly what the source can actually
   do. A read-only source (e.g. a CSV export) leaves `WRITE_*` unset;
   feature code checks capabilities before calling a method that needs
   them, so writes are silently skipped rather than crashing.
2. **Map the source's vocabulary onto `status` and `ball`.** Every
   source has its own status/ball-in-court vocabulary. Map it in the
   adapter's own config (for Sheets, that's `done_status` /
   `ball_in_our_court` / `waiting_on_others` in `sheet.yaml`) into the
   canonical `Ball` enum, not the other way around.
3. **Give each item a stable `id`.** It must be stable across repeated
   reads even when the source has no natural key. The Sheets adapter
   hashes normalized `(project_id, group, title)`
   (`sources/gsheets/parse_weekly.py::item_id`), because row numbers
   move when a weekly tab is duplicated.
4. **Implement `health()` honestly.** A bad parse, an expired token, or
   an unparseable tab layout must show up in `health()` so a run stops
   *before* writing, never mid-write. Don't let `list_items()` or
   `write_items()` raise for a condition `health()` should have caught.
5. **Pass `tests/contract/`.** Add your adapter to `SOURCE_BUILDERS` in
   `tests/contract/conftest.py` with seed data equivalent to the other
   builders (same item titles/groups/ball states), then run
   `uv run pytest tests/contract/` unmodified. If a contract test
   doesn't make sense for your source (e.g. no history), guard it on
   the relevant `Capability` the way the existing tests do — don't skip
   the whole file.
6. **Record rate limits and pagination in the adapter's docstring.**
   Anyone adding a poller or a webhook handler later needs this without
   re-reading the vendor's docs.
7. **Normalize at the boundary.** IDs become `str`, envelopes get
   unwrapped, pagination is hidden behind a helper, timestamps become
   timezone-aware `datetime`s — all inside the adapter. Feature code
   never sees a vendor's response shape, only `Item`/`Change`.

## Reference implementations

- `sources/fake.py` — the simplest possible adapter; in-memory, used by
  every test that doesn't specifically need Sheets's mess.
- `sources/gsheets/` — the messiest one, done first on purpose: if the
  interface survives a spreadsheet with inconsistent tab names, a title
  row, fill-down, multi-select values, and a change log with shifting
  row numbers, it will survive a cleaner API-backed source too.
  - `raw.py` — low-level grid access + the two write guards
    (`write_ai_cells`, `write_agent_tab`). Internal; nothing outside
    `sources/gsheets/` should import it directly.
  - `client.py` — the real `gspread`-backed `SheetClient`.
  - `parse_weekly.py` / `parse_changelog.py` — raw grid → `Item` /
    `RawChange` → canonical `Change`.
  - `source.py` — `GSheetsSource`, the `TrackerSource` implementation
    that ties the above together.

## Adapters on the roadmap (Phase 6+)

Roughly in order of effort: CSV/Excel export (pandas, read-only,
universal fallback), Airtable/monday/Smartsheet (REST, closest in shape
to the sheet), Procore/Buildertrend/Fieldwire (REST + OAuth, the real
industry targets — Procore notes below), MS Project/P6 XER (file parse,
schedule-shaped not task-shaped, read-only).

### Procore, when it's time

- **Versioning is per resource, not global** (`/rest/v1.2/projects` vs.
  `/rest/v2.x/...`). Pin a version per endpoint in one `ENDPOINTS` table
  with the changelog date in a comment; never build a URL from a global
  version constant.
- v1 vs. v2 differ in company/project scoping (header vs. path),
  response shape (top-level vs. a `data` envelope), ID type (int vs.
  str), and pagination (v2 is paginated, default 10/max 100, via
  `Per-Page`/`Total`/`Link` headers). Normalize all of this inside the
  adapter per rule 7 above.
- Use a Developer Managed Service Account (DMSA) / client-credentials
  grant for the unattended poller — there's no one around to approve an
  interactive OAuth prompt on a cron job.
- Confirm the actual rate limit (hourly number, scope: per app or per
  company) and whether the free developer sandbox comes seeded with
  RFIs/submittals/schedule data before writing the adapter.
- Map RFI → `group`=trade/spec section, `ball` from Procore's own
  ball-in-court field (maps cleanly onto our `Ball` enum); Submittal →
  `group`=spec section, `ball` from the current review step's
  responsible party; Punch item → `group`=trade, `ball`=assignee; Daily
  log → feeds RAG, not the item list; Schedule task → read-only,
  `date`=finish.
- If API/sandbox access stalls, Procore also exports CSV — the CSV
  adapter still demonstrates the seam without blocking on partner
  access.
