"""Vercel entrypoint.

Vercel's zero-config Python runtime looks for a top-level WSGI `app` in files such as
`api/index.py`. The real application lives in ../app.py (repo root) so local
development (`python app.py`) and Vercel share one code path.

Static assets are served by Vercel's CDN from `public/` and the dataset lives in
`data/` (both are bundled with the deployment).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402  (Vercel exposes `app` as the WSGI handler)

handler = app  # alias for runtimes that look for `handler`

__all__ = ["app", "handler"]
