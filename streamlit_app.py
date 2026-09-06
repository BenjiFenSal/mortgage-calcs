"""Entry point for Streamlit Community Cloud (and any tool that auto-detects `streamlit_app.py`
at the repo root). The actual app lives in v2/ as a self-contained folder — this file just runs
it, adding v2/ to sys.path first so its `import engine` / `import session_store` resolve to the
copies inside v2/ rather than any older ones elsewhere in this repo.
"""

import sys
from pathlib import Path

APP_DIR = Path(__file__).parent / "v2"
sys.path.insert(0, str(APP_DIR))

app_file = APP_DIR / "app.py"
exec(compile(app_file.read_text(), str(app_file), "exec"))
