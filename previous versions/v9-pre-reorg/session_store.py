"""Session storage backend: Google Sheets when configured via st.secrets, otherwise a local JSON
file. This lets the app run immediately with zero setup (local file) and transparently switch to
synced cloud storage once Google Sheets credentials are added — no code changes needed either way.
"""

import json
from pathlib import Path

import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_HEADERS = ["name", "comment", "saved_at", "currency", "visible_calcs", "state"]


def _secrets_available() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "SHEET_ID" in st.secrets
    except Exception:
        return False


def is_cloud_configured() -> bool:
    return _secrets_available()


def storage_label() -> str:
    return "☁️ Google Sheets (synced)" if is_cloud_configured() else "💾 Local file (this device only)"


@st.cache_resource(show_spinner=False)
def _get_worksheet():
    import gspread
    from google.oauth2.service_account import Credentials

    creds_info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(st.secrets["SHEET_ID"])
    try:
        ws = spreadsheet.worksheet("sessions")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="sessions", rows=100, cols=len(SHEET_HEADERS))
        ws.append_row(SHEET_HEADERS)
    return ws


def _load_from_sheet() -> list[dict]:
    ws = _get_worksheet()
    rows = ws.get_all_records()
    sessions = []
    for r in rows:
        if not r.get("name"):
            continue
        sessions.append({
            "name": r["name"],
            "comment": r.get("comment", ""),
            "saved_at": r.get("saved_at", ""),
            "currency": r.get("currency", ""),
            "visible_calcs": json.loads(r["visible_calcs"]) if r.get("visible_calcs") else [],
            "state": json.loads(r["state"]) if r.get("state") else {},
        })
    return sessions


def _write_to_sheet(sessions: list[dict]):
    ws = _get_worksheet()
    ws.clear()
    ws.append_row(SHEET_HEADERS)
    rows = [
        [
            s["name"], s.get("comment", ""), s.get("saved_at", ""), s.get("currency", ""),
            json.dumps(s.get("visible_calcs", [])), json.dumps(s.get("state", {})),
        ]
        for s in sessions
    ]
    if rows:
        ws.append_rows(rows)


def _load_from_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _write_to_file(path: Path, sessions: list[dict]):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(sessions, indent=2))


def load_all_sessions(local_path: Path) -> list[dict]:
    """Reads the session library from Google Sheets if configured, else the local JSON file.
    Falls back to the local file (with a warning) if the Sheets call fails for any reason."""
    if is_cloud_configured():
        try:
            return _load_from_sheet()
        except Exception as e:
            st.warning(f"Couldn't reach Google Sheets ({e}) — showing local sessions instead.")
    return _load_from_file(local_path)


def write_all_sessions(sessions: list[dict], local_path: Path):
    """Writes the full session library to Google Sheets if configured, else the local JSON file.
    Falls back to writing locally (with a warning) if the Sheets call fails for any reason."""
    if is_cloud_configured():
        try:
            _write_to_sheet(sessions)
            return
        except Exception as e:
            st.warning(f"Couldn't save to Google Sheets ({e}) — saved locally instead.")
    _write_to_file(local_path, sessions)
