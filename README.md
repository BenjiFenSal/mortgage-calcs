# Mortgage Dashboard

Interactive Streamlit dashboard with 8 mortgage calculators (basic repayment, compare mortgages,
overpayments, offset vs savings, deposit saving, compare fixed rates, ditch-your-fix, and
affordability), timeline features (rate changes, lump sums, milestones, deposit/upfront costs),
named saved sessions, and CSV/SVG export.

## Current version: `v2/`

The `v2/` folder is a **self-contained** copy of the app — its own venv, its own copy of
`engine.py`/`session_store.py`/`components/`, its own `requirements.txt` — so it can be run,
copied, or deployed independently of anything else in this repo.

```bash
cd v2
./.venv/bin/streamlit run app.py
```

Then open the URL it prints (usually http://localhost:8501). Or just double-click
`v2/Run Mortgage Dashboard.command`.

By default sessions save to a local JSON file. To turn on cross-device sync via Google Sheets,
see [`v2/SETUP.md`](v2/SETUP.md).

## Deploying online

`streamlit_app.py` at the repo root is the entry point Streamlit Community Cloud auto-detects —
it just runs `v2/app.py`. `index.html` at the root is a GitHub Pages redirect stub pointing at
the deployed Streamlit Cloud URL. Full walkthrough (GitHub, Google Cloud Console, Streamlit Cloud,
GitHub Pages) is in [`v2/SETUP.md`](v2/SETUP.md).

## Features

- Reducing-balance amortization, with a choice of interest accrual convention:
  - **Monthly (rate/12)** — the simple textbook method.
  - **Daily actual/365 (bank-style)** — accrues interest daily on the actual days in each month,
    matching how many UK lenders (trackers/SVR) actually calculate interest.
- Timeline features per mortgage: mid-term rate changes, lump-sum payments, milestones, and
  deposit/upfront costs — all reflected in the amortization and summary figures.
- Multi-scenario comparison: add more mortgages to any calculator and compare them side by side
  on the same charts.
- Named saved sessions with comments, listed in a sidebar library for quick reload.
- Export: per-scenario and combined CSV, plus SVG chart export.

## Repo layout

- `v2/` — the current, most recent version. Run this.
- `previous versions/` — archived historical snapshots (`v1` through `v9-pre-reorg`), kept for
  reference only. Not runnable as-is without recreating their own venvs.
- `streamlit_app.py`, `index.html`, root `requirements.txt` — deployment plumbing for Streamlit
  Community Cloud / GitHub Pages (see [`v2/SETUP.md`](v2/SETUP.md)). They point at `v2/`, not at
  any code of their own.
- `VERSION.md` — changelog across the app's whole history. Its internal "v1"–"v8" numbering
  predates and is unrelated to the `v2/` folder name used today.
