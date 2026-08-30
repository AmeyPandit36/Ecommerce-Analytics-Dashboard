"""Geography block: the dataset's `location` column is an encoded district-like id."""
from __future__ import annotations

from analytics import common as C
from core import format as F

TOP_LOCATIONS = 12


def compute(store, where: str, params: tuple) -> dict:
    by_rev = C.group(store, where, params, "location",
                     ["revenue", "sessions", "purchases", "customers", "conversion", "rating"],
                     order="revenue", limit=TOP_LOCATIONS)
    by_customers = C.group(store, where, params, "location", ["customers", "revenue"],
                           order="customers", limit=TOP_LOCATIONS)
    spread = store.row(f"SELECT COUNT(DISTINCT location) AS locations, "
                       f"COUNT(DISTINCT CASE WHEN purchased = 1 THEN location END) AS buying "
                       f"FROM sessions WHERE 1=1 {where}", params)
    return {"ready": True, "by_revenue": by_rev, "by_customers": by_customers,
            "charts": charts(store, where, params), "spread": spread}


def charts(store, where: str, params: tuple) -> list[dict]:
    by_rev = C.group(store, where, params, "location",
                     ["revenue", "customers", "conversion", "sessions"], order="revenue",
                     limit=TOP_LOCATIONS)
    out = [
        C.chart("geo_revenue", "Top locations by revenue", "hbar",
                [g["label"] for g in by_rev],
                [{"label": "Revenue", "data": [g["revenue"] for g in by_rev], "color": "blue"},
                 {"label": "Customers", "data": [g["customers"] for g in by_rev], "color": "teal",
                  "axis": "y1"}],
                subtitle="`location` is an encoded id (0-224) in the source dataset — no place names "
                         "are published with it, so codes are shown verbatim",
                span=6, unit="inr", height=340),
    ]
    if by_rev:
        best = max(by_rev, key=lambda g: (g["conversion"] or 0))
        worst = min(by_rev, key=lambda g: (g["conversion"] or 99))
        out.append(C.chart("geo_conversion", "Conversion by location", "bar",
                           [g["label"] for g in by_rev],
                           [{"label": "Conversion", "data": [g["conversion"] for g in by_rev],
                             "color": "emerald"}],
                           subtitle=f"Best: {best['label']} at {F.pct(best['conversion'])} • "
                                    f"Weakest: {worst['label']} at {F.pct(worst['conversion'])}",
                           span=6, unit="pct", height=340))
    return out
