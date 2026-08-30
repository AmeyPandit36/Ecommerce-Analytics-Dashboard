"""Query engine for the dashboard: a read-only SQLite store over the bundled dataset.

SQLite (stdlib) is deliberately used instead of pandas so that the Vercel
function bundle stays small and cold starts stay fast, while every number on
every page is still computed from the real dataset rows.
"""
from __future__ import annotations

import os
import sqlite3
import threading

_MAX_CACHE = 4000


class Store:
    """Read-only SQLite store with per-process memoisation of aggregate queries."""

    def __init__(self, path: str, meta: dict | None = None):
        self.path = path
        self._local = threading.local()
        self._cache: dict[tuple, list] = {}
        self.meta = meta or self._read_meta(path)
        self._columns: list[str] | None = None
        self._option_cache: dict[str, list] = {}

    # ------------------------------------------------------------------ conn
    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA mmap_size = 67108864")
            self._local.conn = conn
        return conn

    def _connect(self) -> sqlite3.Connection:
        try:
            return sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
        except sqlite3.OperationalError:
            # Read-only filesystem (serverless): run from a temp copy instead.
            import shutil
            import tempfile

            tmp = os.path.join(tempfile.gettempdir(), os.path.basename(self.path))
            if not os.path.exists(tmp) or os.path.getsize(tmp) != os.path.getsize(self.path):
                shutil.copyfile(self.path, tmp)
            return sqlite3.connect(f"file:{tmp}?mode=ro", uri=True, check_same_thread=False)

    @staticmethod
    def _read_meta(path: str) -> dict:
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            out = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            conn.close()
            return out
        except Exception:
            return {}

    # --------------------------------------------------------------- queries
    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        key = (sql, params)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            data = [dict(r) for r in self.conn.execute(sql, params).fetchall()]
        except sqlite3.Error:
            data = []
        if len(self._cache) >= _MAX_CACHE:
            self._cache.clear()
        self._cache[key] = data
        return data

    def row(self, sql: str, params: tuple = ()) -> dict:
        found = self.rows(sql, params)
        return found[0] if found else {}

    def scalar(self, sql: str, params: tuple = (), default=None):
        found = self.rows(sql, params)
        if not found:
            return default
        values = list(found[0].values())
        if not values or values[0] is None:
            return default
        return values[0]

    def series(self, sql: str, label_col: str, value_col: str, params: tuple = ()):
        data = self.rows(sql, params)
        return [r[label_col] for r in data], [r[value_col] for r in data]

    # ---------------------------------------------------------------- schema
    @property
    def columns(self) -> list[str]:
        if self._columns is None:
            self._columns = [r["name"] for r in self.rows("PRAGMA table_info(sessions)")]
        return self._columns

    def has(self, column: str) -> bool:
        return column in self.columns

    def distinct(self, column: str, label_expr: str | None = None) -> list[dict]:
        """Real values present in the data - used to build the filter bar.

        `label_expr` is chosen from a fixed internal set (never user input).
        """
        cache_key = f"{column}:{label_expr}"
        if cache_key in self._option_cache:
            return self._option_cache[cache_key]
        if column not in self.columns:
            return []
        label = label_expr or f"CAST({column} AS TEXT)"
        sql = (f"SELECT {column} AS value, {label} AS label, COUNT(*) AS n "
               f"FROM sessions WHERE {column} IS NOT NULL "
               f"GROUP BY {column} ORDER BY value")
        out = [{"value": r["value"], "label": str(r["label"]), "n": r["n"]}
               for r in self.rows(sql)]
        self._option_cache[cache_key] = out
        return out

    # ------------------------------------------------------------- lifecycle
    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None
