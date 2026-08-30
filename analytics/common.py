"""Shared SQL building blocks for the analytics modules.

Everything here is a real aggregation over the `sessions` table built from
data/Ecommerce.csv. Metrics are declared once so a KPI means the same thing on
every page (e.g. rating is always the post-purchase rating, AOV is always
revenue / completed purchases - never revenue / all sessions).
"""
from __future__ import annotations

from core import format as F

# metric key -> (SQL expression, formatter kind)
METRICS: dict[str, tuple[str, str]] = {
    "sessions": ("COUNT(*)", "count"),
    "customers": ("COUNT(DISTINCT customer_id)", "count"),
    "purchases": ("SUM(purchased)", "count"),
    "buyers": ("COUNT(DISTINCT CASE WHEN purchased = 1 THEN customer_id END)", "count"),
    "browsers": ("COUNT(DISTINCT CASE WHEN purchased = 0 THEN customer_id END)", "count"),
    "revenue": ("COALESCE(SUM(revenue), 0)", "inr"),
    "gross": ("COALESCE(SUM(gross_value), 0)", "inr"),
    "discount_value": ("COALESCE(SUM(discount_amount), 0)", "inr"),
    "units": ("COALESCE(SUM(quantity), 0)", "count"),
    "aov": ("SUM(revenue) * 1.0 / NULLIF(SUM(purchased), 0)", "inr"),
    "avg_price": ("AVG(unit_price)", "inr"),
    "conversion": ("100.0 * SUM(purchased) / NULLIF(COUNT(*), 0)", "pct"),
    "cart_rate": ("100.0 * SUM(added_to_cart) / NULLIF(COUNT(*), 0)", "pct"),
    "abandon_rate": ("100.0 * SUM(cart_abandoned) / NULLIF(SUM(added_to_cart), 0)", "pct"),
    "carts": ("SUM(added_to_cart)", "count"),
    "abandoned": ("SUM(cart_abandoned)", "count"),
    "avg_discount": ("AVG(discount_percent)", "pct"),
    "rating": ("AVG(CASE WHEN purchased = 1 THEN rating END)", "num1"),
    "rating_count": ("SUM(CASE WHEN purchased = 1 THEN 1 ELSE 0 END)", "count"),
    "helpful_votes": ("COALESCE(SUM(CASE WHEN purchased = 1 THEN review_helpful_votes ELSE 0 END), 0)", "count"),
    "avg_time": ("AVG(time_on_site_sec)", "sec"),
    "avg_pages": ("AVG(pages_viewed)", "num1"),
    "revenue_per_customer": ("SUM(revenue) * 1.0 / NULLIF(COUNT(DISTINCT customer_id), 0)", "inr"),
    "sessions_per_customer": ("COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT customer_id), 0)", "num1"),
    "purchases_per_buyer": ("SUM(purchased) * 1.0 / NULLIF(COUNT(DISTINCT CASE WHEN purchased = 1 THEN customer_id END), 0)", "num2"),
    "products": ("COUNT(DISTINCT product_id)", "count"),
    "max_revenue": ("MAX(revenue)", "inr"),
}

# dimension key -> (group expression, label expression)
DIMENSIONS: dict[str, tuple[str, str]] = {
    "category": ("product_category", "category_label"),
    "payment": ("payment_method", "payment_label"),
    "device": ("device_type", "device_label"),
    "user_type": ("user_type", "user_type_label"),
    "channel": ("marketing_channel", "channel_label"),
    "location": ("location", "location_label"),
    "month": ("visit_month", "month_name"),
    "weekday": ("weekday", "weekday_name"),
    "season": ("season", "season_name"),
    "duration": ("duration_bucket", "duration_bucket"),
    "rating": ("rating", "CAST(rating AS TEXT) || ' star'"),
    "date": ("visit_date", "visit_date"),
    "product": ("product_id", "'Product #' || product_id"),
    "discount_band": (
        "CASE WHEN discount_percent = 0 THEN 0 ELSE (discount_percent / 5) * 5 END",
        "CASE WHEN discount_percent = 0 THEN 'No discount' "
        "ELSE (discount_percent / 5) * 5 || '%-' || ((discount_percent / 5) * 5 + 4) || '%' END",
    ),
    # Analysis-aligned discount buckets (values in the dataset are 0,5,10,15,20,25,30)
    "discount_bucket": (
        "CASE WHEN discount_percent = 0 THEN 0 WHEN discount_percent <= 10 THEN 1 "
        "WHEN discount_percent <= 20 THEN 2 ELSE 3 END",
        "CASE WHEN discount_percent = 0 THEN '0% (no discount)' "
        "WHEN discount_percent <= 10 THEN '5\u201310%' "
        "WHEN discount_percent <= 20 THEN '11\u201320%' ELSE '21\u201330%' END",
    ),
    # ₹500 price bands, aligned with the analysis ("₹501–₹1,500 = 63.6% of revenue")
    "price_band": (
        "CASE WHEN unit_price <= 500 THEN 0 WHEN unit_price <= 1000 THEN 1 "
        "WHEN unit_price <= 1500 THEN 2 ELSE 3 END",
        "CASE WHEN unit_price <= 500 THEN '\u2264 \u20b9500' "
        "WHEN unit_price <= 1000 THEN '\u20b9501\u20131,000' "
        "WHEN unit_price <= 1500 THEN '\u20b91,001\u20131,500' ELSE '\u20b91,501\u20132,000' END",
    ),
    "time_band": (
        "(CAST(time_on_site_sec / 300 AS INT)) * 300",
        "CAST(CAST(time_on_site_sec / 300 AS INT) * 300 / 60 AS TEXT) || 'm'",
    ),
    "pages_band": (
        "CAST(pages_viewed / 5 AS INT) * 5",
        "CAST(CAST(pages_viewed / 5 AS INT) * 5 + 1 AS TEXT) || '-' || "
        "CAST(CAST(pages_viewed / 5 AS INT) * 5 + 5 AS TEXT) || ' pages'",
    ),
}

# dimensions whose natural order is numeric/temporal, not "biggest first"
ORDER_BY_KEY = {"month", "weekday", "season", "rating", "date", "discount_band",
                "discount_bucket", "price_band", "time_band", "pages_band", "duration"}

PALETTE = ["cyan", "violet", "blue", "teal", "emerald", "amber", "slate", "rose", "orange"]


def metric_sql(metrics) -> str:
    return ", ".join(f'{METRICS[m][0]} AS "{m}"' for m in metrics)


def group(store, where: str, params: tuple, dim: str, metrics, limit: int | None = None,
          order: str = "revenue", asc: bool = False) -> list[dict]:
    """Aggregate `metrics` per `dim` value, with the dataset's own label."""
    if dim not in DIMENSIONS:
        return []
    expr, label = DIMENSIONS[dim]
    sql = (f"SELECT {expr} AS key, MAX({label}) AS label, {metric_sql(metrics)} "
           f"FROM sessions WHERE 1=1 {where} GROUP BY {expr}")
    if dim in ORDER_BY_KEY:
        sql += " ORDER BY key ASC"
    else:
        direction = "ASC" if asc else "DESC"
        if order == "key":
            sql += f" ORDER BY key {direction}"
        else:
            sql += f" ORDER BY {METRICS.get(order, ('revenue', ''))[0]} {direction}"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return store.rows(sql, params)


def overall(store, where: str, params: tuple, metrics) -> dict:
    row = store.row(f"SELECT {metric_sql(metrics)} FROM sessions WHERE 1=1 {where}", params)
    out = {}
    for metric in metrics:
        value = row.get(metric)
        out[metric] = float(value) if isinstance(value, (int, float)) else (0.0 if value is None else value)
    return out


def totals(store, where: str, params: tuple) -> dict:
    return overall(store, where, params, [
        "sessions", "customers", "purchases", "buyers", "revenue", "aov", "units",
        "gross", "discount_value", "avg_discount", "conversion", "cart_rate", "abandon_rate",
        "carts", "abandoned", "rating", "avg_time", "avg_pages", "revenue_per_customer",
        "sessions_per_customer", "products", "purchases_per_buyer", "helpful_votes",
        "rating_count", "max_revenue", "avg_price",
    ])


# --------------------------------------------------------------------- format
def fmt(value, kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "inr":
        return F.inr_short(value)
    if kind == "inr_m":
        return F.inr_m(value)
    if kind == "count":
        return F.number(value)
    if kind == "pct":
        return F.pct(value)
    if kind == "pct2":
        return F.pct(value, 2)
    if kind == "num1":
        return F.number(value, 1, style="west")
    if kind == "num2":
        return F.number(value, 2, style="west")
    if kind == "sec":
        return F.seconds_to_mmss(value)
    return str(value)


def kpi(label, value, kind="num", hint="", tone="default", icon="info", foot=""):
    """One KPI tile: raw value + formatted display, so JS can re-format too."""
    number_value = None
    if isinstance(value, (int, float)):
        number_value = round(float(value), 4)
    return {"label": label, "value": number_value if number_value is not None else value,
            "display": fmt(value, kind), "raw": value, "kind": kind, "hint": hint,
            "tone": tone, "icon": icon, "foot": foot}


def kpis(pairs, data: dict) -> list[dict]:
    """pairs: iterable of (label, metric_key, kind, hint, tone, icon)"""
    out = []
    for pair in pairs:
        label, metric = pair[0], pair[1]
        kind = pair[2] if len(pair) > 2 else METRICS.get(metric, ("", "num"))[1]
        hint = pair[3] if len(pair) > 3 else ""
        tone = pair[4] if len(pair) > 4 else "default"
        icon = pair[5] if len(pair) > 5 else "info"
        out.append(kpi(label, data.get(metric), kind, hint, tone, icon))
    return out


def chart(chart_id, title, type_, labels, series, *, subtitle="", span=6, unit="num",
          height=260, legend=None, note="", stacked=False, horizontal=False, max_ticks=None,
          callout=None):
    """Chart spec consumed by the Chart.js renderer in static/app.js.

    `callout` is an optional analytical annotation rendered beside the chart:
    {"text": "Highest conversion", "tone": "accent" | "warn" | "positive"}.
    """
    normalised = []
    for i, raw in enumerate(series):
        item = dict(raw)
        item.setdefault("color", PALETTE[i % len(PALETTE)])
        item.setdefault("type", "line" if type_ in ("line", "area", "combo") else "bar")
        if type_ == "area":
            item["type"] = "line"
            item["fill"] = True
        item["data"] = [None if v is None else (round(float(v), 4) if isinstance(v, (int, float)) else v)
                        for v in item.get("data", [])]
        normalised.append(item)
    return {"id": chart_id, "title": title, "subtitle": subtitle, "type": type_,
            "labels": [str(x) for x in labels], "series": normalised, "span": span,
            "unit": unit, "height": height, "note": note, "stacked": stacked,
            "horizontal": horizontal or type_ == "hbar",
            "legend": (len(normalised) > 1) if legend is None else legend,
            "maxTicks": max_ticks, "callout": callout}


def table(title, columns, rows, *, subtitle="", span=6, note="", kind="plain", empty="No rows match the current filters."):
    """Table spec. columns: [{"key","label","align","unit"}]"""
    return {"title": title, "subtitle": subtitle, "columns": columns, "rows": rows,
            "span": span, "note": note, "kind": kind, "empty": empty}


def column(labels_keys="label"):
    return {"key": "label", "label": labels_keys}
