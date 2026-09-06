# Going online: GitHub + Streamlit Community Cloud + Google Sheets sync

This app already works with zero setup, saving sessions to a local JSON file. This guide covers
the two things only you can do (they need your own accounts): publishing the code on GitHub, and
switching session storage over to Google Sheets so it syncs across devices/browsers instead of
being stuck on one machine. I can't create your Google Cloud project or push to your GitHub for
you, but everything below is written so you can just follow it step by step — ping me if any step
errors out and I'll help debug it.

## Part 1 — Push the code to GitHub

The local repo is already initialized and committed — this `v2/` folder is a subfolder of it, not
its own repo (`git log` from the repo root shows the commit history). Push the whole repo root:

On github.com: create a new **public** repository named whatever you like (don't check
"Add a README" — we already have files, and that would conflict). Then, from the repo root
(one level up from this `v2/` folder):

```bash
cd ..   # back to the mortgage-dashboard repo root, if you're currently inside v2/
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

(GitHub Desktop or VS Code's git panel work identically here — just point them at the repo root
folder, not `v2/` itself.)

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

## Part 2a — Set up Google login (so sessions are private per-person)

The app requires signing in with a Google account before it'll show or save anything — this is
what keeps one person's saved mortgages from being visible or editable by anyone else who opens
the app. It uses Streamlit's built-in login (no extra service to run), which needs an OAuth
client from the same Google Cloud project as Part 2:

1. **Configure the consent screen** (first time only): **APIs & Services → OAuth consent screen**.
   Choose **External**, fill in an app name (e.g. "Mortgage Dashboard") and your email for the
   support/contact fields, then save through the remaining steps (scopes and test users can be
   left at their defaults while the app is small/personal-use).
2. **Create the OAuth client**: **APIs & Services → Credentials → Create Credentials → OAuth
   client ID**. Application type: **Web application**. Name it anything.
3. Under **Authorized redirect URIs**, add both of these (you can add the second one later, once
   you have a deployed URL from Part 5):
   - `http://localhost:8501/oauth2callback`
   - `https://<your-app>.streamlit.app/oauth2callback`
4. Click **Create**. Copy the **Client ID** and **Client secret** shown.
5. Open `.streamlit/secrets.toml` and paste them into the `[auth]` section, replacing the two
   `TODO-...` placeholders (`client_id` and `client_secret`). The `cookie_secret` and
   `redirect_uri` fields are already filled in for local dev — leave `cookie_secret` as-is (it's
   just a random signing key), but you'll need to add a *second copy* of the `[auth]` block with
   `redirect_uri` set to your `streamlit.app` URL when you paste secrets into Streamlit Cloud in
   Part 5 (Streamlit only reads one `redirect_uri`, so local dev and the deployed app need their
   secrets configured separately with the URI that matches where they're actually running).
6. Run the app locally — you should now see a "Log in with Google" screen before anything else
   loads. Once signed in, your saved sessions are tied to your Google account email and nobody
   else can see or delete them.

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
(`./.venv/bin/streamlit run app.py`) and check the sidebar's "Sessions" section: it should now
say **"☁️ Google Sheets (synced)"** instead of "💾 Local file". Save a session and check it appears
as a new row in your Google Sheet.

## Part 5 — Deploy on Streamlit Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **Create app** → pick your repo. The repo has a `streamlit_app.py` at its root, which Streamlit
   Cloud auto-detects as the entry point (it just runs the real app in `v2/`), so you can usually
   leave **Main file path** on its default. If it doesn't auto-fill, set it to `streamlit_app.py`
   explicitly.
3. Before deploying, click **Advanced settings → Secrets** and paste the *entire contents* of
   your local `.streamlit/secrets.toml` into the box (this is the cloud equivalent of that file —
   it's stored encrypted by Streamlit, not in your repo) — except change `[auth]`'s `redirect_uri`
   to `https://<your-app>.streamlit.app/oauth2callback` (must match the app's real deployed URL,
   not localhost).
4. Click **Deploy**. Once it's live, anyone with the link can use the calculators, and every
   session saved from any device will sync through the same Google Sheet.
5. Copy the app's URL (looks like `https://<something>.streamlit.app`).

## Part 6 — Optional: a github.io landing page

GitHub Pages can only serve static HTML — it can't run the Streamlit app itself (that needs a
live Python process, which is what Part 5 sets up). What it *can* do is give you a short,
memorable URL that redirects to the real app.

1. Open `index.html` at the repo root and replace both occurrences of
   `https://REPLACE-WITH-YOUR-APP.streamlit.app` with the real URL from Part 5, step 5.
2. Commit and push that change.
3. On GitHub: repo **Settings → Pages → Build and deployment → Source: Deploy from a branch**,
   branch `main`, folder `/ (root)` → **Save**.
4. After a minute or two, `https://<your-username>.github.io/<repo-name>/` will redirect straight
   to the live app.

## Notes

- The app falls back to local-file storage automatically if the Sheets credentials are missing or
  a request to Google fails (e.g. quota, network) — you'll see a warning banner but the app keeps
  working.
- Sessions saved locally (before you set up Sheets) won't automatically migrate — use "Export
  current session (.json)" before switching over, then "Import session (.json)" afterward if you
  want to keep them.
- Anyone who can edit the Google Sheet directly (not through the app) can see/change everyone's
  saved sessions — treat the sheet's sharing settings as you would any other personal document.
  The app itself only ever shows/edits the signed-in user's own rows.
- To remove a saved session, sign in, open **💾 Sessions & settings** (or the sidebar's "Sessions"
  section), and click the 🗑️ button next to that session in the list.
