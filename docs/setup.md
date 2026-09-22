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

## 4. Make a demo copy of the tracker

1. Open the real tracker sheet.
2. **File → Make a copy**, name it something like `Tracker (demo)`.
3. Replace every real project name, address, and note with invented data —
   this copy is what all development and the public repo's screenshots use.
   No real client or project data should ever appear in it.
4. Copy the demo sheet's ID out of its URL: the long string between `/d/`
   and `/edit` in `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.

## 5. Share both sheets with the service account

For **both** the real tracker and the demo copy:

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
SHEET_ID_DEMO=<demo tracker sheet ID>
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/service_account.json
```

SMTP variables (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`) are needed
starting in Phase 3 (weekly digest email) — a Gmail app password works
for `SMTP_USER`/`SMTP_PASSWORD` with `SMTP_HOST=smtp.gmail.com`. Not
needed yet for Phase 0.

## 7. Verify

```bash
uv sync
uv run tracker inspect          # reads the demo sheet by default
uv run tracker inspect --no-demo  # reads the real sheet
```

`inspect` is read-only — it cannot write anything, so it's safe to run
against the real sheet as soon as the service account has access.

If `inspect` fails with a permissions error, double check step 5 (the
sheet must be shared with the exact service account email, not just any
Google account).
