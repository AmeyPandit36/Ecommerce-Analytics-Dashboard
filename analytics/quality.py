"""Data-quality page. This always describes the *whole* bundled dataset
(a quality report should not change because you filtered to one category)."""
from __future__ import annotations

import json

from analytics import common as C
from core import format as F


def compute(store, where: str = "", params: tuple = ()) -> dict:
    meta = store.meta or {}
    rows = store.scalar("SELECT COUNT(*) FROM sessions", (), 0)
    distinct_dupes = store.scalar("SELECT COUNT(*) - COUNT(DISTINCT session_id) FROM sessions", (), 0)
    profile = store.rows("SELECT * FROM dq_columns ORDER BY position")
    columns = len(profile)

    missing_cells = sum(int(p["nulls"] or 0) for p in profile)
    numeric = [p for p in profile if p["dtype"] in ("integer", "float")]
    outlier_cells = sum(int(p["outliers"] or 0) for p in numeric)
    total_cells = max(1, rows * max(1, columns))

    # Transparent score: 100 minus each penalty, each term shown in the UI.
    missing_term = 100.0 * missing_cells / total_cells * 10
    dup_term = 100.0 * distinct_dupes / max(1, rows) * 5
    outlier_term = 100.0 * outlier_cells / total_cells * 2
    raw_score = 100 - missing_term - dup_term - outlier_term
    score = max(0.0, min(100.0, raw_score))

    dtype_counts: dict[str, int] = {}
    for p in profile:
        dtype_counts[p["dtype"]] = dtype_counts.get(p["dtype"], 0) + 1

    completeness = [{
        "label": p["name"],
        "pct": 100.0 * (p["not_nulls"] or 0) / max(1, rows),
        "nulls": p["nulls"] or 0,
        "distinct": p["distinct_n"] or 0,
    } for p in profile]
    outlier_rows = [{"label": p["name"], "outliers": p["outliers"] or 0,
                     "low": p["outlier_low"], "high": p["outlier_high"],
                     "pct": 100.0 * (p["outliers"] or 0) / max(1, rows)}
                    for p in numeric if (p["outliers"] or 0) > 0]

    try:
        findings = json.loads(meta.get("findings") or "[]")
    except json.JSONDecodeError:
        findings = []

    profile_table = []
    for p in profile:
        try:
            top = json.loads(p["top_values"] or "[]")
        except json.JSONDecodeError:
            top = []
        profile_table.append({
            "name": p["name"], "dtype": p["dtype"], "role": p["role"],
            "not_nulls": F.number(p["not_nulls"]), "nulls": F.number(p["nulls"]),
            "distinct": F.number(p["distinct_n"]),
            "min": (F.number(p["min_num"], 2, style="west") if p["min_num"] is not None
                    else str(p["min_str"] or "n/a")),
            "max": F.number(p["max_num"], 2, style="west") if p["max_num"] is not None else "",
            "mean": F.number(p["mean_num"], 2, style="west") if p["mean_num"] is not None else "",
            "median": F.number(p["median_num"], 2, style="west") if p["median_num"] is not None else "",
            "outliers": F.number(p["outliers"]) if p["outliers"] else "0",
            "top": ", ".join(f"{t['value']} ×{F.compact(t['count'])}" for t in top[:2]),
        })

    charts = [
        C.chart("completeness", "Completeness by column", "bar",
                [c["label"] for c in completeness],
                [{"label": "Populated", "data": [round(c["pct"], 2) for c in completeness],
                  "color": "teal"}],
                subtitle="Share of the 25,000 rows holding a non-empty value — every column is fully "
                         "populated in this dataset",
                span=12, unit="pct", height=220),
    ]
    if outlier_rows:
        charts.append(C.chart("outliers", "Rows outside 1.5 × IQR fences", "hbar",
                              [o["label"] for o in outlier_rows],
                              [{"label": "Flagged rows", "data": [o["outliers"] for o in outlier_rows],
                                "color": "orange"}],
                              subtitle="Fences are computed per numeric column (Q1-1.5·IQR, Q3+1.5·IQR); "
                                       "flags are observations, not errors — no rows were dropped",
                              span=6, unit="count", height=300))
    charts.append(C.chart("cardinality", "Distinct values per column", "hbar",
                          [c["label"] for c in sorted(completeness, key=lambda x: -x["distinct"])[:14]],
                          [{"label": "Distinct values", "data": [c["distinct"] for c in
                                                                 sorted(completeness, key=lambda x: -x["distinct"])[:14]],
                            "color": "violet"}],
                          subtitle="High-cardinality codes (product_id, location) need different "
                                   "treatment than low-cardinality codes (payment, device)",
                          span=6 if outlier_rows else 12, unit="count", height=300))

    return {
        "ready": True,
        "kpis": [
            C.kpi("Rows", rows, "count", "Sessions in data/Ecommerce.csv", "default", "database"),
            C.kpi("Columns", columns, "count", "Columns in the raw CSV", "default", "grid"),
            C.kpi("Missing cells", missing_cells, "count", "Empty values across every column",
                  "positive" if missing_cells == 0 else "warn", "droplet"),
            C.kpi("Duplicate rows", distinct_dupes, "count", "Rows repeating a session_id",
                  "positive" if not distinct_dupes else "warn", "copy"),
            C.kpi("Quality score", round(score, 1), "num1", "100 − completeness, duplicate and outlier penalties",
                  "positive" if score >= 90 else "warn", "shield"),
            C.kpi("Flagged outliers", outlier_cells, "count", "Numeric cells beyond IQR fences",
                  "warn" if outlier_cells else "default", "scatter"),
            C.kpi("Unique customers", meta.get("unique_customers", 0), "count", "Distinct customer_id",
                  "default", "users"),
            C.kpi("Date span", f"{meta.get('date_min', 'n/a')} → {meta.get('date_max', 'n/a')}",
                  None, "Parsed from visit_date (DD-MM-YYYY)", "default", "calendar"),
        ],
        "charts": charts,
        "score": {
            "value": round(score, 1),
            "terms": [
                {"name": "Completeness", "penalty": round(missing_term, 2),
                 "detail": f"{F.number(missing_cells)} empty cells of {F.number(total_cells)} "
                           f"({F.pct(100.0 * missing_cells / total_cells, 3)})"},
                {"name": "Duplicates", "penalty": round(dup_term, 2),
                 "detail": f"{F.number(distinct_dupes)} duplicated session_id values"},
                {"name": "Outliers", "penalty": round(outlier_term, 2),
                 "detail": f"{F.number(outlier_cells)} numeric cells beyond IQR fences"},
            ],
        },
        "dtype_counts": sorted(dtype_counts.items(), key=lambda kv: -kv[1]),
        "meta": meta,
        "findings": findings,
        "tables": [C.table("Column profile", [
            {"key": "name", "label": "Column", "align": "left"},
            {"key": "dtype", "label": "Type", "align": "left"},
            {"key": "role", "label": "Role in the dashboard", "align": "left"},
            {"key": "not_nulls", "label": "Populated", "align": "right"},
            {"key": "nulls", "label": "Missing", "align": "right"},
            {"key": "distinct", "label": "Distinct", "align": "right"},
            {"key": "min", "label": "Min", "align": "right"},
            {"key": "max", "label": "Max", "align": "right"},
            {"key": "mean", "label": "Mean", "align": "right"},
            {"key": "median", "label": "Median", "align": "right"},
            {"key": "outliers", "label": "Outliers", "align": "right"},
            {"key": "top", "label": "Most common values", "align": "left"},
        ], profile_table, span=12,
            subtitle="Measured on the raw CSV, materialised into data/ecommerce.db by "
                     "scripts/build_dataset.py",
            note="`revenue`, `purchased`, `added_to_cart`, `cart_abandoned`, `rating` and the derived "
                 "`gross_value` are recomputed per session; label-encoded columns keep their integer codes.")],
    }
