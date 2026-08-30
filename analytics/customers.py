"""Customer analytics: value segmentation (transparent tertiles), behaviour, spend."""
from __future__ import annotations

from analytics import common as C
from analytics import geography as GEO
from core import format as F

SEGMENT_ORDER = ["High value", "Medium value", "Low value", "Window shoppers"]
SEGMENT_COLORS = {"High value": "cyan", "Medium value": "violet", "Low value": "amber",
                  "Window shoppers": "slate"}

CUSTOMER_AGG = """
WITH c AS (
    SELECT customer_id,
           COUNT(*)                                     AS sessions,
           COALESCE(SUM(purchased), 0)                  AS purchases,
           COALESCE(SUM(revenue), 0)                    AS revenue,
           COALESCE(SUM(quantity * purchased), 0)       AS units,
           COALESCE(SUM(discount_amount), 0)            AS discount,
           AVG(CASE WHEN purchased = 1 THEN rating END) AS rating,
           AVG(time_on_site_sec)                        AS avg_time,
           AVG(pages_viewed)                            AS avg_pages,
           100.0 * SUM(purchased) / COUNT(*)            AS conversion
    FROM sessions WHERE 1=1 {where}
    GROUP BY customer_id
)
"""

CASE_TEMPLATE = ("CASE WHEN purchases = 0 THEN 'Window shoppers' "
                 "WHEN revenue >= ? THEN 'High value' "
                 "WHEN revenue >= ? THEN 'Medium value' "
                 "ELSE 'Low value' END")


def quantile(values: list[float], q: float):
    """Linear-interpolated quantile (stdlib only, same idea as numpy's default)."""
    if not values:
        return None
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    pos = (len(data) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    frac = pos - lo
    return float(data[lo] * (1 - frac) + data[hi] * frac)


def compute(store, where: str, params: tuple) -> dict:
    totals = C.overall(store, where, params, [
        "sessions", "customers", "buyers", "purchases", "revenue", "aov", "conversion",
        "cart_rate", "abandon_rate", "rating", "units", "avg_discount", "avg_time", "avg_pages",
        "revenue_per_customer", "sessions_per_customer", "gross", "discount_value"])

    agg = store.rows(CUSTOMER_AGG.format(where=where) + "SELECT * FROM c ORDER BY revenue DESC", params)
    if not agg:
        return {"ready": False, "reason": "No customers match the current filters."}

    revenues = [float(r["revenue"] or 0) for r in agg]
    buyer_revenues = [v for v in revenues if v > 0]
    high_cut = quantile(buyer_revenues, 2 / 3)
    low_cut = quantile(buyer_revenues, 1 / 3)
    cuts = [v for v in (high_cut, low_cut) if v is not None]

    def segment_of(row):
        revenue = float(row["revenue"] or 0)
        if revenue <= 0:
            return "Window shoppers"
        if len(cuts) == 2 and revenue >= cuts[0]:
            return "High value"
        if len(cuts) == 2 and revenue >= cuts[1]:
            return "Medium value"
        return "Low value"

    buckets: dict[str, list] = {name: [] for name in SEGMENT_ORDER}
    for row in agg:
        buckets[segment_of(row)].append(row)

    segments = []
    total_customers = len(agg)
    total_revenue = sum(revenues) or 0
    for name in SEGMENT_ORDER:
        rows = buckets[name]
        if not rows:
            continue
        rev = sum(float(r["revenue"] or 0) for r in rows)
        ratings = [float(r["rating"]) for r in rows if r["rating"] is not None]
        segments.append({
            "segment": name, "color": SEGMENT_COLORS[name],
            "customers": len(rows),
            "customer_share": 100.0 * len(rows) / total_customers,
            "revenue": rev,
            "revenue_share": (100.0 * rev / total_revenue) if total_revenue else 0,
            "avg_revenue": rev / len(rows),
            "median_revenue": quantile([float(r["revenue"] or 0) for r in rows], 0.5),
            "avg_sessions": sum(int(r["sessions"]) for r in rows) / len(rows),
            "avg_purchases": sum(int(r["purchases"]) for r in rows) / len(rows),
            "conversion": 100.0 * sum(int(r["purchases"]) for r in rows) / max(1, sum(int(r["sessions"]) for r in rows)),
            "avg_rating": (sum(ratings) / len(ratings)) if ratings else None,
            "avg_time": sum(float(r["avg_time"] or 0) for r in rows) / len(rows),
            "threshold": (F.inr_short(cuts[0]) + "+") if name == "High value" and cuts else
                         (F.inr_short(cuts[1]) + " – " + F.inr_short(cuts[0]) if name == "Medium value" and len(cuts) == 2
                          else ("under " + F.inr_short(cuts[1]) if name == "Low value" and len(cuts) == 2
                                else "no purchases")),
        })

    repeat = sum(1 for r in agg if int(r["purchases"] or 0) >= 2)
    buyers = sum(1 for r in agg if int(r["purchases"] or 0) >= 1)

    # Revenue-per-customer histogram (0 included, so window shoppers are visible)
    edges = [0, 250, 750, 1500, 2500, 4000, 6000, 9000, 13000, 10 ** 9]
    hist_labels, hist_counts, hist_revenue = [], [0] * (len(edges) - 1), [0.0] * (len(edges) - 1)
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        hist_labels.append("₹0" if i == 0 else (f"₹{F.compact(lo, 0)}+" if hi > 10 ** 8 else f"₹{F.compact(lo, 0)}–{F.compact(hi, 0)}"))
    for row in agg:
        rev = float(row["revenue"] or 0)
        slot = 0
        for i in range(len(edges) - 1):
            if rev >= edges[i] and rev < edges[i + 1]:
                slot = i
                break
        hist_counts[slot] += 1
        hist_revenue[slot] += rev

    # Session-level behaviour, split by the dataset's user_type code
    user_type = C.group(store, where, params, "user_type",
                        ["sessions", "purchases", "conversion", "revenue", "abandon_rate",
                         "cart_rate", "avg_time", "rating", "customers"])

    # Payment preference per segment (SQL keeps segment definition identical to above)
    seg_params = tuple(params) + (cuts[0] if len(cuts) == 2 else 1e18, cuts[1] if len(cuts) == 2 else 1e18)
    pay_sql = (CUSTOMER_AGG.format(where=where) +
               f"SELECT {CASE_TEMPLATE} AS segment, s.payment_label AS label, "
               "COUNT(*) AS sessions, COALESCE(SUM(s.revenue),0) AS revenue, "
               "COUNT(DISTINCT s.customer_id) AS customers "
               "FROM c JOIN sessions s ON s.customer_id = c.customer_id "
               f"WHERE 1=1 {where} GROUP BY segment, label ORDER BY revenue DESC")
    pay_rows = store.rows(pay_sql, seg_params)
    pay_pivot: dict[str, list] = {}
    for row in pay_rows:
        pay_pivot.setdefault(row["segment"], []).append(row)
    pay_table = []
    for name in SEGMENT_ORDER:
        rows = pay_pivot.get(name) or []
        if not rows:
            continue
        top = max(rows, key=lambda r: r["revenue"] or 0)
        pay_table.append({
            "segment": name,
            "customers": F.number(sum(r["customers"] for r in rows)),
            "revenue": F.inr_short(sum(r["revenue"] or 0 for r in rows)),
            "top_payment": top["label"],
            "top_payment_share": F.pct(100.0 * (top["revenue"] or 0) / max(1e-9, sum(r["revenue"] or 0 for r in rows))),
            "detail": ", ".join(f"{r['label']} {F.pct(100.0 * (r['revenue'] or 0) / max(1e-9, sum(x['revenue'] or 0 for x in rows)), 0)}"
                                for r in rows[:3]),
        })

    # Most valuable customers + their modal category / location
    top_rows = agg[:12]
    ids = [int(r["customer_id"]) for r in top_rows if r["customer_id"] is not None]
    modal = {"category": {}, "location": {}}
    if ids:
        marks = ",".join("?" * len(ids))
        for field, column, label in (("category", "product_category", "category_label"),
                                     ("location", "location", "location_label")):
            found = store.rows(
                f"SELECT customer_id, {label} AS label, SUM(revenue) AS revenue FROM sessions "
                f"WHERE customer_id IN ({marks}) GROUP BY customer_id, {column} ORDER BY revenue DESC",
                tuple(ids))
            for row in found:
                modal[field].setdefault(row["customer_id"], row["label"])

    customers_table = [{
        "label": f"Customer #{int(r['customer_id'])}",
        "sessions": F.number(r["sessions"]),
        "purchases": F.number(r["purchases"]),
        "revenue": F.inr(r["revenue"]),
        "units": F.number(r["units"]),
        "conversion": F.pct(r["conversion"]),
        "rating": (F.number(r["rating"], 1, style="west") + " ★") if r["rating"] is not None else "n/a",
        "top_category": modal["category"].get(int(r["customer_id"]), "n/a"),
        "top_location": modal["location"].get(int(r["customer_id"]), "n/a"),
    } for r in top_rows]

    session_hist = store.rows("SELECT n AS sessions, COUNT(*) AS customers FROM "
                              f"(SELECT customer_id, COUNT(*) AS n FROM sessions WHERE 1=1 {where} "
                              "GROUP BY customer_id) GROUP BY n ORDER BY n LIMIT 12", params)

    charts = [
        C.chart("customer_value", "Lifetime revenue per customer", "bar", hist_labels,
                [{"label": "Customers", "data": hist_counts, "color": "cyan"},
                 {"label": "Revenue", "data": hist_revenue, "color": "amber", "axis": "y1"}],
                subtitle="Distribution of spend across the customers in range — the long tail of "
                         "₹0 (window shoppers) is real, not missing data",
                span=6, unit="count", height=280),
        C.chart("segment_mix", "Customer segments", "donut",
                [s["segment"] for s in segments],
                [{"label": "Customers", "data": [s["customers"] for s in segments],
                  "colors": [s["color"] for s in segments]}],
                subtitle="Tertiles of lifetime revenue per customer (thresholds below)",
                span=3, unit="count", height=280),
        C.chart("segment_revenue", "Revenue by segment", "bar",
                [s["segment"] for s in segments],
                [{"label": "Revenue", "data": [s["revenue"] for s in segments],
                  "colors": [s["color"] for s in segments]}],
                subtitle="Where the money actually comes from", span=6, unit="inr", height=280),
        C.chart("user_type_behaviour", "Behaviour by user type (session level)", "combo",
                [u["label"] for u in user_type],
                [{"label": "Conversion", "data": [u["conversion"] for u in user_type], "type": "bar",
                  "color": "emerald"},
                 {"label": "Cart abandonment", "data": [u["abandon_rate"] for u in user_type],
                  "type": "bar", "color": "rose"},
                 {"label": "Revenue", "data": [u["revenue"] for u in user_type], "type": "line",
                  "axis": "y1", "color": "cyan"}],
                subtitle="user_type is recorded per session in this dataset, so it is compared "
                         "at session level", span=6, unit="pct", height=300),
        C.chart("session_depth", "Sessions per customer", "bar",
                [str(r["sessions"]) for r in session_hist],
                [{"label": "Customers", "data": [r["customers"] for r in session_hist],
                  "color": "violet"}],
                subtitle="How many visits each customer logged (1 = one-off visitor)",
                span=6, unit="count", height=280),
    ]
    charts.extend(GEO.charts(store, where, params))

    segment_table = [{
        "segment": s["segment"], "rule": s["threshold"],
        "customers": F.number(s["customers"]),
        "share": F.pct(s["customer_share"]),
        "revenue": F.inr_short(s["revenue"]),
        "revenue_share": F.pct(s["revenue_share"]),
        "avg_revenue": F.inr_short(s["avg_revenue"]),
        "avg_sessions": F.number(s["avg_sessions"], 1, style="west"),
        "conversion": F.pct(s["conversion"]),
        "rating": (F.number(s["avg_rating"], 2, style="west") + " ★") if s["avg_rating"] else "n/a",
    } for s in segments]

    kpi_row = [
        C.kpi("Customers", totals["customers"], "count", "Distinct customer_id in range",
              "default", "users"),
        C.kpi("Buyers", buyers, "count", "Customers with at least one purchase", "positive", "cart"),
        C.kpi("Window shoppers", totals["customers"] - buyers, "count",
              "Customers with sessions but no purchase", "warn", "eye"),
        C.kpi("Revenue / customer", totals["revenue_per_customer"], "inr",
              "Total revenue ÷ customers", "default", "rupee"),
        C.kpi("Repeat buyers", repeat, "count",
              f"{F.pct(100.0 * repeat / buyers) if buyers else 'n/a'} of buyers purchased twice or more",
              "default", "repeat"),
        C.kpi("Sessions / customer", totals["sessions_per_customer"], "num1",
              "Mean visits per customer", "default", "activity"),
        C.kpi("Avg rating", totals["rating"], "num1", "Mean rating on purchased sessions",
              "default", "star"),
        C.kpi("Avg cart abandonment", totals["abandon_rate"], "pct",
              "Abandoned ÷ carts created", "warn", "warning"),
    ]

    return {
        "ready": True,
        "totals": totals,
        "kpis": kpi_row,
        "charts": charts,
        "segments": segments,
        "segment_rule": {
            "method": "33rd / 66th percentile (linear interpolation) of lifetime revenue per customer, "
                      "computed on the rows matching the current filters",
            "high_cut": F.clean(high_cut), "low_cut": F.clean(low_cut),
            "high_cut_label": F.inr(high_cut) if high_cut is not None else "n/a",
            "low_cut_label": F.inr(low_cut) if low_cut is not None else "n/a",
            "buyers": len(buyer_revenues), "customers": total_customers,
        },
        "tables": [
            C.table("Value segments", [
                {"key": "segment", "label": "Segment", "align": "left"},
                {"key": "rule", "label": "Rule", "align": "left"},
                {"key": "customers", "label": "Customers", "align": "right"},
                {"key": "share", "label": "% of all", "align": "right"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
                {"key": "revenue_share", "label": "% of rev.", "align": "right"},
                {"key": "avg_revenue", "label": "Avg revenue", "align": "right"},
                {"key": "avg_sessions", "label": "Sessions", "align": "right"},
                {"key": "conversion", "label": "Conv.", "align": "right"},
                {"key": "rating", "label": "Rating", "align": "right"},
            ], segment_table, subtitle="Segment sizes come from the data, not from a fixed quota",
                span=12),
            C.table("Most valuable customers", [
                {"key": "label", "label": "Customer", "align": "left"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
                {"key": "sessions", "label": "Sessions", "align": "right"},
                {"key": "purchases", "label": "Purchases", "align": "right"},
                {"key": "units", "label": "Units", "align": "right"},
                {"key": "conversion", "label": "Conv.", "align": "right"},
                {"key": "rating", "label": "Rating", "align": "right"},
                {"key": "top_category", "label": "Top category", "align": "left"},
                {"key": "top_location", "label": "Most frequent location", "align": "left"},
            ], customers_table, subtitle="Ranked by lifetime revenue inside the current filters",
                span=12),
            C.table("Payment preference by segment", [
                {"key": "segment", "label": "Segment", "align": "left"},
                {"key": "customers", "label": "Customers", "align": "right"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
                {"key": "top_payment", "label": "Top payment", "align": "left"},
                {"key": "top_payment_share", "label": "Share of segment revenue", "align": "right"},
                {"key": "detail", "label": "Top 3 methods", "align": "left"},
            ], pay_table, span=12,
                note="Payment methods are encoded (0-5) in the source dataset."),
        ],
    }
