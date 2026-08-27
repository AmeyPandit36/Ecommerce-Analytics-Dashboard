"""Dataset access for the dashboard.

Runtime reads the *bundled* dataset only:

    data/ecommerce.db   <- built from data/Ecommerce.csv by scripts/build_dataset.py
    data/Ecommerce.csv  <- the real Kaggle file, committed to the repo

There is deliberately NO kagglehub / Kaggle API call here: a deployed (serverless)
instance must not re-download 2.5 MB per cold start, and must work with no Kaggle
credentials. `scripts/download_dataset.py` is a separate, developer-only tool.
"""
from __future__ import annotations

import os
import sqlite3

from core.store import Store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_NAME = "Ecommerce.csv"
DB_NAME = "ecommerce.db"


def _candidate_paths(filename: str) -> list[str]:
    """Look for the data file next to the app, in the repo, and in the
    locations used by serverless bundlers (e.g. Vercel's /var/task)."""
    raw = os.environ.get("DATA_DIR")
    ordered = [os.path.join(DATA_DIR, filename)]
    if raw:
        ordered.insert(0, os.path.join(raw, filename))
    here = os.path.dirname(os.path.abspath(__file__))
    ordered += [
        os.path.join(here, filename),
        os.path.join(os.getcwd(), "data", filename),
        os.path.join(os.getcwd(), filename),
        "/var/task/data/" + filename,
        "/tmp/data/" + filename,
    ]
    seen, out = set(), []
    for path in ordered:
        path = os.path.normpath(path)
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def find_file(filename: str) -> str | None:
    for path in _candidate_paths(filename):
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    return None


def _writable_dir() -> str | None:
    """First directory we may create files in, for the cold-start safety net.

    Serverless filesystems (Vercel's ``/var/task``) are read-only, so ``DATA_DIR``
    and ``/tmp`` are tried before the repo copy.
    """
    candidates = []
    raw = os.environ.get("DATA_DIR")
    if raw:
        candidates.append(raw)
    candidates += [DATA_DIR, "/tmp/data"]
    for folder in candidates:
        try:
            if os.makedirs(folder, exist_ok=True) or True:
                if os.access(folder, os.W_OK):
                    return folder
        except OSError:
            continue
    return None


def _build_db_from_csv(csv_path: str, db_path: str) -> bool:
    """Regenerate the SQLite store from the CSV (dev convenience / safety net)."""
    try:
        import sys

        scripts = os.path.join(BASE_DIR, "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from build_dataset import main as build_main  # type: ignore

        build_main(csv_path, db_path)
        return True
    except Exception as exc:  # pragma: no cover - depends on local env
        print(f"[loader] could not rebuild {db_path}: {exc}")
        return False


def _usable(path: str) -> bool:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        conn.close()
        return rows > 0
    except sqlite3.Error:
        return False


def load_store() -> tuple[Store | None, str]:
    """Return (store, human status). Never raises: the UI degrades gracefully."""
    db_path = find_file(DB_NAME)
    if not db_path:
        csv_path = find_file(CSV_NAME)
        folder = _writable_dir() if csv_path else None
        if folder:
            target = os.path.join(folder, DB_NAME)
            if _build_db_from_csv(csv_path, target):
                db_path = target
        if not db_path:
            return None, ("Analytics store missing. Run: python scripts/build_dataset.py")

    if not _usable(db_path):
        return None, f"Analytics store at {db_path} is unreadable or empty."

    store = Store(db_path)
    rows = store.scalar("SELECT COUNT(*) FROM sessions", (), 0)
    columns = len(store.columns)
    meta = store.meta or {}
    status = f"{rows:,} sessions × {columns} analytics columns • built {meta.get('generated_utc', 'n/a')}"
    return store, status


# ------------------------------------------------------------------ legacy API
def load_dataset():
    """Backwards-compatible helper (old code called load_dataset() -> (df, status))."""
    store, status = load_store()
    return store, status
