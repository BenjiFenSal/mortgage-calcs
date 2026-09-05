# Going online: GitHub + Streamlit Community Cloud + Google Sheets sync

This app already works with zero setup, saving sessions to a local JSON file. This guide covers
the two things only you can do (they need your own accounts): publishing the code on GitHub, and
switching session storage over to Google Sheets so it syncs across devices/browsers instead of
being stuck on one machine. I can't create your Google Cloud project or push to your GitHub for
you, but everything below is written so you can just follow it step by step — ping me if any step
errors out and I'll help debug it.

## Part 1 — Push the code to GitHub

The local repo is already initialized and committed — this `v4/` folder is a subfolder of it, not
its own repo (`git log` from the repo root shows the commit history). Push the whole repo root:

On github.com: create a new **public** repository named whatever you like (don't check
"Add a README" — we already have files, and that would conflict). Then, from the repo root
(one level up from this `v4/` folder):

```bash
cd ..   # back to the mortgage-dashboard repo root, if you're currently inside v4/
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

(GitHub Desktop or VS Code's git panel work identically here — just point them at the repo root
folder, not `v4/` itself.)

## Part 2 — Google Cloud Console: create the Sheets credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project
   (or pick an existing one) — top-left project dropdown → **New Project**.
2. In the search bar, find **Google Sheets API** and click **Enable**. Do the same for
   **Google Drive API** (needed for the service account to open the sheet by ID).
3. Go to **APIs & Services → Credentials → Create Credentials → Service account**.
   - Give it any name, e.g. `mortgage-dashboard-sync`.
   - Skip granting it project roles (not needed) and click **Done**.
4. Click into the service account you just created → **Keys** tab → **Add Key → Create new key**
   → type **JSON** → **Create**. A `.json` file downloads — keep it somewhere safe, it's a
   credential, not something to commit to GitHub.
5. Note the service account's email address (looks like
   `mortgage-dashboard-sync@your-project.iam.gserviceaccount.com`) — you'll need it next.

## Part 3 — Create the Google Sheet and share it with the service account

1. Go to [sheets.google.com](https://sheets.google.com) and create a new blank spreadsheet —
   name it whatever you like, e.g. "Mortgage Dashboard Sessions".
2. Click **Share** (top right) and share it with the service account's email address from step 5
   above, with **Editor** access. Uncheck "notify people" — it's not a real inbox.
3. Copy the sheet's ID from its URL: `https://docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`.

## Part 4 — Wire the credentials into the app

Open the downloaded JSON key file and the app's secrets template
(`.streamlit/secrets.toml.example`) side by side. Copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and fill in each field from the JSON key:

| secrets.toml field | JSON key field |
|---|---|
| `SHEET_ID` | (from the sheet's URL, Part 3.3) |
| `project_id` | `project_id` |
| `private_key_id` | `private_key_id` |
| `private_key` | `private_key` (keep the `\n` line breaks — paste it as-is inside the `"""..."""` block) |
| `client_email` | `client_email` |
| `client_id` | `client_id` |
| `client_x509_cert_url` | `client_x509_cert_url` |

`.streamlit/secrets.toml` is gitignored — it will never be committed. Run the app locally
(`./.venv/bin/streamlit run app_v4.py`) and check the sidebar's "Sessions" section: it should now
say **"☁️ Google Sheets (synced)"** instead of "💾 Local file". Save a session and check it appears
as a new row in your Google Sheet.

## Part 5 — Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **Create app** → pick your repo → set **Main file path** to `v4/app_v4.py` (the app lives in
   the `v4/` subfolder of the repo).
3. Before deploying, click **Advanced settings → Secrets** and paste the *entire contents* of
   your local `.streamlit/secrets.toml` into the box (this is the cloud equivalent of that file —
   it's stored encrypted by Streamlit, not in your repo).
4. Click **Deploy**. Once it's live, anyone with the link can use the calculators, and every
   session saved from any device will sync through the same Google Sheet.

## Notes

- The app falls back to local-file storage automatically if the Sheets credentials are missing or
  a request to Google fails (e.g. quota, network) — you'll see a warning banner but the app keeps
  working.
- Sessions saved locally (before you set up Sheets) won't automatically migrate — use "Export
  current session (.json)" before switching over, then "Import session (.json)" afterward if you
  want to keep them.
- Anyone who can edit the Google Sheet can see/change saved sessions (loan amounts, etc.) — treat
  the sheet's sharing settings as you would any other personal document.
