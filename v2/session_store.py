"""Session storage backend: Google Sheets when configured via st.secrets, otherwise a local JSON
file. This lets the app run immediately with zero setup (local file) and transparently switch to
synced cloud storage once Google Sheets credentials are added — no code changes needed either way.

Sessions are namespaced by `owner` (the logged-in user's email from st.user). The Sheet holds
every user's rows in one place, so writes always merge against the full sheet rather than
overwriting it outright — otherwise one user saving would silently delete everyone else's rows.
"""

import json
from pathlib import Path

import streamlit as st

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_HEADERS = ["owner", "name", "comment", "saved_at", "currency", "visible_calcs", "state"]


def _secrets_available() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "SHEET_ID" in st.secrets
    except Exception:
        return False


def is_cloud_configured() -> bool:
    return _secrets_available()


def storage_label() -> str:
    return "☁️ Google Sheets (synced)" if is_cloud_configured() else "💾 Local file (this device only)"


def auth_configured() -> bool:
    """Whether Google login is fully set up: all required [auth] keys present in secrets, and
    client_id/client_secret don't still hold the unfilled TODO placeholder from the example."""
    try:
        auth = st.secrets.get("auth", {})
        if not all(k in auth for k in ("client_id", "client_secret", "redirect_uri", "cookie_secret")):
            return False
        return not str(auth["client_id"]).startswith("TODO") and not str(auth["client_secret"]).startswith("TODO")
    except Exception:
        return False


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


def _load_all_rows_from_sheet() -> list[dict]:
    """Every session for every user — used internally so writes can merge instead of clobber."""
    ws = _get_worksheet()
    rows = ws.get_all_records()
    sessions = []
    for r in rows:
        if not r.get("name"):
            continue
        sessions.append({
            "owner": r.get("owner", ""),
            "name": r["name"],
            "comment": r.get("comment", ""),
            "saved_at": r.get("saved_at", ""),
            "currency": r.get("currency", ""),
            "visible_calcs": json.loads(r["visible_calcs"]) if r.get("visible_calcs") else [],
            "state": json.loads(r["state"]) if r.get("state") else {},
        })
    return sessions


def _rows_for_sheet(sessions: list[dict]) -> list[list]:
    return [
        [
            s.get("owner", ""), s["name"], s.get("comment", ""), s.get("saved_at", ""),
            s.get("currency", ""), json.dumps(s.get("visible_calcs", [])), json.dumps(s.get("state", {})),
        ]
        for s in sessions
    ]


def _load_from_sheet(owner: str) -> list[dict]:
    return [s for s in _load_all_rows_from_sheet() if s.get("owner") == owner]


def _write_to_sheet(owner: str, owner_sessions: list[dict]):
    others = [s for s in _load_all_rows_from_sheet() if s.get("owner") != owner]
    merged = others + owner_sessions
    ws = _get_worksheet()
    ws.clear()
    ws.append_row(SHEET_HEADERS)
    rows = _rows_for_sheet(merged)
    if rows:
        ws.append_rows(rows)


def _load_from_file(path: Path, owner: str) -> list[dict]:
    if not path.exists():
        return []
    all_sessions = json.loads(path.read_text())
    return [s for s in all_sessions if s.get("owner") == owner]


def _write_to_file(path: Path, owner: str, owner_sessions: list[dict]):
    all_sessions = json.loads(path.read_text()) if path.exists() else []
    others = [s for s in all_sessions if s.get("owner") != owner]
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(others + owner_sessions, indent=2))


def _describe_error(e: Exception) -> str:
    """gspread sometimes re-raises a bare PermissionError() with no message, hiding the actual
    API error in __cause__. Walk the chain so the real reason (e.g. an API not being enabled
    yet) actually reaches the UI instead of a blank, undiagnosable message."""
    seen = e
    while str(seen) == "" and seen.__cause__ is not None:
        seen = seen.__cause__
    return str(seen) or repr(e)


def load_all_sessions(local_path: Path, owner: str) -> list[dict]:
    """Reads this user's sessions from Google Sheets if configured, else the local JSON file.
    Falls back to the local file (with a warning) if the Sheets call fails for any reason."""
    if is_cloud_configured():
        try:
            return _load_from_sheet(owner)
        except Exception as e:
            st.warning(f"Couldn't reach Google Sheets ({_describe_error(e)}) — showing local sessions instead.")
    return _load_from_file(local_path, owner)


def write_all_sessions(sessions: list[dict], local_path: Path, owner: str):
    """Writes this user's sessions to Google Sheets if configured, else the local JSON file,
    leaving every other user's rows untouched. Falls back to writing locally (with a warning)
    if the Sheets call fails for any reason."""
    for s in sessions:
        s["owner"] = owner
    if is_cloud_configured():
        try:
            _write_to_sheet(owner, sessions)
            return
        except Exception as e:
            st.warning(f"Couldn't save to Google Sheets ({_describe_error(e)}) — saved locally instead.")
    _write_to_file(local_path, owner, sessions)
