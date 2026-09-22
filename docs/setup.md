# Setup: Google Cloud service account for tracker-agent

Phase 0 needs a Google Cloud service account with read/write access to the
tracker Sheet and read access to the project docs Drive folder. Do these
steps yourself in the Google Cloud Console and Google Sheets/Drive UI —
Claude Code cannot do this part.

## 1. Create (or pick) a Google Cloud project

1. Go to https://console.cloud.google.com/
2. Top bar → project selector → **New Project**.
3. Name it something like `tracker-agent`. Note the project ID.

## 2. Enable the Sheets and Drive APIs

1. In the console, go to **APIs & Services → Library**.
2. Search for **Google Sheets API** → **Enable**.
3. Search for **Google Drive API** → **Enable**.

## 3. Create a service account

1. **APIs & Services → Credentials → Create Credentials → Service account**.
2. Name it `tracker-agent`. No roles needed at the project IAM level (access
   is granted per-file by sharing, in step 5).
3. After it's created, open the service account, go to the **Keys** tab →
   **Add Key → Create new key → JSON**. This downloads a `.json` key file.
4. Move that file to `credentials/service_account.json` in this repo
   (the path `.env.example` points at via `GOOGLE_SERVICE_ACCOUNT_FILE`).
   This directory is gitignored — the key never gets committed.
5. Note the service account's **email address**, shown on its details page.
   It looks like `tracker-agent@<project-id>.iam.gserviceaccount.com`.

## 4. Create the demo spreadsheet

Don't copy the real tracker for this — a hand-scrubbed copy is exactly how
a real name or address ends up in the demo. Instead, generate one from
scratch, seeded entirely with the same invented data the test fixtures
use (`tests/fixtures/demo_sheet.py`).

Service accounts get effectively no storage quota in their own "My
Drive", so the sheet has to be created inside a **Shared Drive**
(Workspace accounts only) that the service account is a member of:

1. https://drive.google.com → **Shared drives** → **+ New**. Name it
   e.g. `tracker-agent`.
2. Open it → **Manage members** → add the service account email from
   step 3.5 with **Content Manager** (or **Manager**) access.
3. Copy the Shared Drive's ID out of its URL:
   `https://drive.google.com/drive/folders/<SHARED_DRIVE_ID>`.

Then:

```bash
uv run python -m scripts.make_demo_sheet \
  --shared-drive <SHARED_DRIVE_ID> \
  --share you@example.com
```

`--share` also grants your own Google account Editor access so you can
open it in a browser (the service account owns it by default, since it
creates it). The script prints the new sheet's ID — save it, you'll need
it in step 6.

## 5. Share the real tracker with the service account

The demo sheet is already shared (the service account created it in step
4). For the **real** tracker:

1. Open the sheet → **Share**.
2. Paste in the service account email from step 3.5.
3. Give it **Editor** access (it needs to write the AI columns).
4. Uncheck "Notify people" (it's a service account, not a person).

Do the same for the Drive folder holding project documents (Phase 4):
share that folder with the service account email, **Viewer** is enough
since ingest only reads.

## 6. Fill in `.env`

Copy `.env.example` to `.env` and fill in:

```bash
ANTHROPIC_API_KEY=<your Anthropic API key>
SHEET_ID=<real tracker sheet ID>
SHEET_ID_DEMO=<demo sheet ID, printed by scripts/make_demo_sheet.py>
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/service_account.json
```

SMTP variables (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`) are needed
starting in Phase 3 (the weekly report email) — a Gmail app password
works for `SMTP_USER`/`SMTP_PASSWORD` with `SMTP_HOST=smtp.gmail.com`.
Not needed yet for Phase 0.

`config/sheet.yaml`'s `spreadsheets:` list maps a `project_id` to the
`.env` variable holding its sheet ID (`sheet_id_env: SHEET_ID_DEMO` by
default). All development runs against the demo project; add a second
entry once you're ready to point at the real sheet.

## 7. Verify

```bash
uv sync
uv run tracker inspect                  # reads the default (first) project in sheet.yaml
uv run tracker inspect --project demo-1 # reads a specific project_id
```

`inspect` is read-only — it cannot write anything, so it's safe to run
against the real sheet as soon as the service account has access.

If `inspect` fails with a permissions error, double check step 5 (the
sheet must be shared with the exact service account email, not just any
Google account).
