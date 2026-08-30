"""Sales & product analytics: KPIs, trends, category / discount / payment views."""
from __future__ import annotations

from analytics import common as C
from analytics import products as P
from core import format as F

TOTAL_METRICS = ["sessions", "revenue", "purchases", "aov", "units", "conversion", "avg_discount",
                 "discount_value", "cart_rate", "abandon_rate", "rating", "customers", "buyers",
                 "gross", "revenue_per_customer", "products", "carts", "abandoned", "avg_price"]


# --------------------------------------------------------------------- trends
GRANULARITY = {
    "day": ("visit_date", "MAX(visit_date)"),
    "week": ("strftime('%Y-W%W', visit_date)", "MIN(visit_date)"),
    "month": ("strftime('%Y-%m', visit_date)", "MIN(visit_date)"),
}


def trend(store, where: str, params: tuple, metrics=("revenue", "sessions", "purchases"), forced=None):
    """Revenue / sessions over time. Granularity adapts to the date span so the
    chart is never 365 unreadable bars nor a single smeared month."""
    span = store.row(f"SELECT CAST(julianday(MAX(visit_date)) - julianday(MIN(visit_date)) AS INT) AS days,"
                     f" COUNT(DISTINCT visit_date) AS days_present FROM sessions WHERE 1=1 {where}", params)
    days = span.get("days") or 0
    if forced in GRANULARITY:
        gran = forced
    elif days <= 40:
        gran = "day"
    elif days <= 240:
        gran = "week"
    else:
        gran = "month"
    key_expr, label_expr = GRANULARITY[gran]
    sql = (f"SELECT {key_expr} AS key, {label_expr} AS raw_label, {C.metric_sql(metrics)} "
           f"FROM sessions WHERE 1=1 {where} GROUP BY key ORDER BY key ASC")
    rows = store.rows(sql, params)
    for row in rows:
        row["label"] = _label(gran, row.get("raw_label"), row.get("key"))
    return rows, gran


def _label(gran: str, raw, key) -> str:
    text = str(raw or key or "")
    try:
        year, month, day = text.split("-")
        if gran == "month":
            return f"{F.MONTHS[int(month) - 1]} {year[2:]}"
        return f"{int(day)} {F.MONTHS[int(month) - 1]}"
    except Exception:
        return text


# ----------------------------------------------------------------- page data
def compute(store, where: str, params: tuple) -> dict:
    totals = C.totals(store, where, params)

    trend_rows, gran = trend(store, where, params)
    t_labels = [r["label"] for r in trend_rows]
    charts = [
        C.chart("revenue_trend", "Revenue & traffic over time", "area", t_labels,
                [{"label": "Revenue", "data": [r["revenue"] for r in trend_rows], "axis": "y",
                  "color": "cyan"},
                 {"label": "Purchases", "data": [r["purchases"] for r in trend_rows], "axis": "y1",
                  "color": "violet"},
                 {"label": "Sessions", "data": [r["sessions"] for r in trend_rows], "axis": "y1",
                  "color": "slate", "dash": [4, 4]}],
                subtitle=f"{'daily' if gran == 'day' else ('weekly' if gran == 'week' else 'monthly')} "
                         f"buckets • revenue (₹, left) vs sessions & purchases (right)",
                span=12, unit="inr", height=300,
                note="Revenue is only booked on sessions where purchased = 1."),
    ]

    cats = C.group(store, where, params, "category",
                  ["revenue", "sessions", "purchases", "conversion", "aov", "rating", "units",
                   "avg_discount", "abandon_rate"], order="revenue")
    charts.append(
        C.chart("category_perf", "Category performance", "combo", [c["label"] for c in cats],
                [{"label": "Revenue", "data": [c["revenue"] for c in cats], "type": "bar", "axis": "y",
                  "color": "cyan"},
                 {"label": "Conversion", "data": [c["conversion"] for c in cats], "type": "line",
                  "axis": "y1", "color": "amber"}],
                subtitle="Revenue per category (₹, left) with conversion rate overlay (%, right)",
                span=6, unit="inr", height=280))

    pays = C.group(store, where, params, "payment", ["purchases", "revenue", "sessions"],
                  order="purchases")
    charts.append(
        C.chart("payment_mix", "Payment method mix", "donut",
                [p["label"] for p in pays],
                [{"label": "Purchases", "data": [p["purchases"] for p in pays]}],
                subtitle="Completed purchases by payment method", span=6, unit="count",
                height=280))

    disc = C.group(store, where, params, "discount_band",
                   ["sessions", "purchases", "conversion", "revenue", "avg_discount"], order="key",
                   asc=True)
    disc = sorted(disc, key=lambda r: (r["key"] is None, r["key"]))
    charts.append(
        C.chart("discount_effect", "Discount depth vs conversion", "combo",
                [d["label"] for d in disc],
                [{"label": "Sessions", "data": [d["sessions"] for d in disc], "type": "bar",
                  "color": "slate"},
                 {"label": "Conversion", "data": [d["conversion"] for d in disc], "type": "line",
                  "axis": "y1", "color": "emerald"}],
                subtitle="Do deeper discounts actually convert better? (bars = sessions, line = conversion %)",
                span=6, unit="count", height=280,
                note="Bands are 5-point buckets of discount_percent."))

    price = C.group(store, where, params, "price_band", ["sessions", "conversion", "revenue", "rating"])
    price = sorted(price, key=lambda r: (r["key"] is None, r["key"]))
    charts.append(
        C.chart("price_band", "Price band vs conversion", "bar", [p["label"] for p in price],
                [{"label": "Sessions", "data": [p["sessions"] for p in price], "color": "violet"},
                 {"label": "Revenue", "data": [p["revenue"] for p in price], "color": "cyan",
                  "axis": "y1"}],
                subtitle="₹250-wide unit price bands", span=6, unit="count", height=280))

    ratings = C.group(store, where, params, "rating", ["rating_count", "sessions"],
                      order="key", asc=True)
    charts.append(
        C.chart("rating_dist", "Post-purchase rating distribution", "bar",
                [f"{int(r['key'])} ★" for r in ratings],
                [{"label": "Rated purchases", "data": [r["rating_count"] for r in ratings],
                  "color": "amber"}],
                subtitle="Ratings on sessions that purchased (non-purchase rows carry a "
                         "placeholder rating in this dataset, so they are excluded)",
                span=6, unit="count", height=260))

    month = C.group(store, where, params, "month", ["revenue", "sessions", "conversion"],
                    order="key", asc=True)
    charts.append(
        C.chart("seasonality", "Month-by-month demand", "bar",
                [m["label"] for m in month],
                [{"label": "Revenue", "data": [m["revenue"] for m in month], "color": "cyan"},
                 {"label": "Sessions", "data": [m["sessions"] for m in month], "color": "slate",
                  "axis": "y1"}],
                subtitle="Revenue and traffic for each calendar month in range", span=6, unit="inr",
                height=260))

    kpi_row = [
        C.kpi("Revenue", totals["revenue"], "inr", "Sum of revenue on purchased sessions",
              "positive", "rupee"),
        C.kpi("Purchases", totals["purchases"], "count", "Sessions with purchased = 1",
              "default", "cart"),
        C.kpi("Avg order value", totals["aov"], "inr",
              "Revenue ÷ purchases (not per session)", "default", "receipt"),
        C.kpi("Conversion", totals["conversion"], "pct", "Purchases ÷ sessions",
              "default", "target"),
        C.kpi("Units sold", totals["units"], "count", "Sum of quantity on purchased sessions",
              "default", "box"),
        C.kpi("Avg discount", totals["avg_discount"], "pct", "Mean of discount_percent",
              "default", "percent"),
        C.kpi("Discount given", totals["discount_value"], "inr",
              "Sum of discount_amount across all sessions", "default", "tags"),
        C.kpi("Avg rating", totals["rating"], "num1", "Mean rating on purchased sessions",
              "default", "star"),
    ]

    total_rev = totals["revenue"] or 0
    table_rows = [{
        "label": c["label"], "sessions": c["sessions"], "purchases": c["purchases"],
        "conversion": F.pct(c["conversion"]), "revenue": F.inr_short(c["revenue"]),
        "aov": F.inr_short(c["aov"]), "rating": F.number(c["rating"], 2, style="west") if c["rating"] else "n/a",
        "units": F.number(c["units"]), "share": F.pct(100.0 * (c["revenue"] or 0) / total_rev) if total_rev else "n/a",
        "bar": round(100.0 * (c["revenue"] or 0) / total_rev, 1) if total_rev else 0,
    } for c in cats]

    return {
        "ready": bool(int(totals["sessions"] or 0)),
        "reason": "No sessions fall inside this filter combination.",
        "totals": totals,
        "kpis": kpi_row,
        "charts": charts,
        "tables": [
            C.table("Category performance", [
                {"key": "label", "label": "Category", "align": "left"},
                {"key": "sessions", "label": "Sessions", "align": "right", "raw": True},
                {"key": "purchases", "label": "Purchases", "align": "right", "raw": True},
                {"key": "conversion", "label": "Conv.", "align": "right"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
                {"key": "aov", "label": "AOV", "align": "right"},
                {"key": "rating", "label": "Rating", "align": "right"},
                {"key": "share", "label": "Rev. share", "align": "right"},
                {"key": "bar", "label": "", "align": "right", "bar": True},
            ], table_rows, subtitle="Every category in the current filter range", span=12,
                note="Categories are label-encoded in the source dataset (no decoding map is shipped), "
                     "so codes are shown as-is instead of guessed names."),
        ],
        "trend_granularity": gran,
        "products": P.summary(store, where, params),
    }

