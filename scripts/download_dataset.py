#!/usr/bin/env python3
"""
DEV-ONLY helper: refresh `data/Ecommerce.csv` from Kaggle.

The deployed application NEVER calls this. `data/Ecommerce.csv` (and the
derived `data/ecommerce.db`) are committed to the repository, so Vercel
serves the dashboard without any Kaggle access at runtime.

    pip install kagglehub          # only needed to refresh the data
    python scripts/download_dataset.py
    python scripts/build_dataset.py

Needs `KAGGLE_USERNAME` / `KAGGLE_KEY` (or `kagglehub` cached auth) because
Kaggle requires an account for dataset downloads.
"""
from __future__ import annotations

import os
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_TARGET = os.path.join(DATA_DIR, "Ecommerce.csv")
DATASET_SLUG = "kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase"
WANTED = "Ecommerce.csv"


def main() -> int:
    try:
        import kagglehub  # noqa: WPS433 (intentional: dev-only dependency)
    except ImportError:
        print("kagglehub is not installed. Run: pip install kagglehub", file=sys.stderr)
        return 1

    path = kagglehub.dataset_download(DATASET_SLUG)
    print("Path to dataset files:", path)

    found = None
    for root, _dirs, files in os.walk(path):
        for name in files:
            if name.lower() == WANTED.lower():
                found = os.path.join(root, name)
                break
        if found:
            break
    if not found:
        for root, _dirs, files in os.walk(path):
            for name in files:
                if name.lower().endswith((".csv", ".xlsx")):
                    found = os.path.join(root, name)
                    break
            if found:
                break

    if not found:
        print(f"No CSV/XLSX found under {path}", file=sys.stderr)
        return 2

    os.makedirs(DATA_DIR, exist_ok=True)
    shutil.copyfile(found, CSV_TARGET)
    size = os.path.getsize(CSV_TARGET)
    print(f"Copied {found}\n  -> {CSV_TARGET} ({size:,} bytes)")
    print("Now rebuild the analytics store:  python scripts/build_dataset.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
