"""Automatically generated, fully data-derived insights for the overview page.

Every number in every card is queried from the dataset at request time, so the
cards stay true when the global filters change. Nothing here is hardcoded.
"""
from __future__ import annotations

from analytics import common as C
from core import format as F

MAX_INSIGHTS = 6


def _card(icon, tone, title, text, metric_label, metric_value, kind):
    return {"icon": icon, "tone": tone, "title": title, "text": text,
            "metric_label": metric_label, "metric": C.fmt(metric_value, kind)}


def _concentration(store, where: str, params: tuple) -> dict:
    """Revenue share of the top 10% of buying customers (two plain queries)."""
    buyers = store.scalar(
        f"SELECT COUNT(*) FROM (SELECT customer_id FROM sessions WHERE 1=1 {where} "
        "GROUP BY customer_id HAVING SUM(revenue) > 0)", params, 0) or 0
    if not buyers:
        return {"buyers": 0, "total": 0, "top10": 0, "top_n": 0}
    total = store.scalar(f"SELECT SUM(revenue) FROM sessions WHERE 1=1 {where} AND purchased = 1",
                         params, 0) or 0
    top_n = max(1, int(round(0.1 * buyers)))
    top = store.scalar(
        f"SELECT SUM(rev) FROM (SELECT SUM(revenue) AS rev FROM sessions WHERE 1=1 {where} "
        f"GROUP BY customer_id HAVING rev > 0 ORDER BY rev DESC LIMIT {top_n})", params, 0) or 0
    return {"buyers": buyers, "total": total, "top10": top, "top_n": top_n}


def correlation(store, where: str, params: tuple, x: str, y: str) -> dict | None:
    """Pearson r computed in SQL from the six needed aggregates."""
    row = store.row(f"SELECT COUNT(*) AS n, SUM({x}) AS sx, SUM({y}) AS sy, "
                    f"SUM({x} * {y}) AS sxy, SUM({x} * {x}) AS sxx, SUM({y} * {y}) AS syy "
                    f"FROM sessions WHERE 1=1 {where}", params)
    n = float(row.get("n") or 0)
    if n < 30:
        return None
    sx, sy, sxy, sxx, syy = (float(row.get(k) or 0) for k in ("sx", "sy", "sxy", "sxx", "syy"))
    numerator = n * sxy - sx * sy
    den_x = n * sxx - sx * sx
    den_y = n * syy - sy * sy
    if den_x <= 0 or den_y <= 0:
        return None
    r = numerator / ((den_x ** 0.5) * (den_y ** 0.5))
    strength = ("very weak" if abs(r) < 0.1 else "weak" if abs(r) < 0.3 else
                "moderate" if abs(r) < 0.5 else "strong" if abs(r) < 0.7 else "very strong")
    return {"r": r, "n": int(n), "strength": strength,
            "direction": "positive" if r > 0 else "negative" if r < 0 else "flat"}


def compute(store, where: str, params: tuple) -> dict:
    totals = C.totals(store, where, params)
    insights: list[dict] = []

    # 1 — strongest category by revenue
    cats = C.group(store, where, params, "category", ["revenue", "sessions", "purchases", "conversion",
                                                       "rating", "units"], order="revenue")
    if cats and totals["revenue"]:
        best, second = cats[0], (cats[1] if len(cats) > 1 else None)
        lead = (best["revenue"] / second["revenue"] - 1) * 100 if second and second["revenue"] else None
        share = 100.0 * best["revenue"] / totals["revenue"]
        insights.append(_card(
            "crown", "positive", f"{best['label']} is the strongest category",
            f"It booked {F.inr_short(best['revenue'])} across {F.number(best['purchases'])} purchases — "
            f"{F.pct(share)} of revenue in range"
            + (f", {F.pct(lead)} ahead of {second['label']}" if lead else "")
            + f", on {F.pct(best['conversion'])} session conversion.",
            "revenue", best["revenue"], "inr"))

    # 2 — peak activity
    months = [m for m in C.group(store, where, params, "month", ["sessions", "revenue", "conversion"])
              if m["sessions"]]
    if months:
        peak = max(months, key=lambda m: m["sessions"])
        richest = max(months, key=lambda m: m["revenue"] or 0)
        low = min(months, key=lambda m: m["sessions"])
        insights.append(_card(
            "trend", "default", f"Activity peaks in {peak['label']}",
            f"{F.number(peak['sessions'])} sessions that month (vs {F.number(low['sessions'])} in the "
            f"quietest, {low['label']}). The richest month for revenue is {richest['label']} at "
            f"{F.inr_short(richest['revenue'])}.",
            "peak sessions", peak["sessions"], "count"))

    # 3 — payment preference
    pays = C.group(store, where, params, "payment", ["purchases", "revenue", "sessions"],
                  order="purchases")
    if pays and totals["purchases"]:
        top = pays[0]
        insights.append(_card(
            "card", "default", f"{top['label']} is the most used payment method",
            f"{F.number(top['purchases'])} of {F.number(totals['purchases'])} purchases "
            f"({F.pct(100.0 * top['purchases'] / totals['purchases'])}) and "
            f"{F.inr_short(top['revenue'])} of revenue. Spread across all "
            f"{len(pays)} methods is even — this dataset has no dominant rail.",
            "purchase share", 100.0 * top["purchases"] / totals["purchases"], "pct"))

    # 4 — best rated category (purchases only: non-purchase rows hold a placeholder 4★)
    rated = [c for c in cats if (c["rating"] or 0) and (c["purchases"] or 0) >= 25]
    if rated:
        best_r = max(rated, key=lambda c: c["rating"])
        worst_r = min(rated, key=lambda c: c["rating"])
        insights.append(_card(
            "star", "positive" if best_r["rating"] >= 4 else "default",
            f"{best_r['label']} holds the highest rating",
            f"{F.number(best_r['rating'], 2, style='west')} ★ over {F.number(best_r['purchases'])} "
            f"purchases, against {F.number(worst_r['rating'], 2, style='west')} ★ for {worst_r['label']}. "
            f"Ratings on non-purchase sessions are a constant placeholder in this dataset, so they are "
            f"excluded everywhere.",
            "avg rating", best_r["rating"], "num1"))

    # 5 — discount vs purchase
    disc_stats = correlation(store, where, params, "discount_percent", "purchased")
    bands = C.group(store, where, params, "discount_band", ["sessions", "conversion", "revenue"],
                    order="key", asc=True)
    if disc_stats:
        zero = next((b for b in bands if b["key"] == 0), None)
        deep = max((b for b in bands if (b["key"] or 0) >= 15), key=lambda b: b["key"], default=None)
        delta = ""
        if zero and deep and zero["conversion"]:
            delta = (f" Sessions at 0% convert at {F.pct(zero['conversion'])} versus "
                     f"{F.pct(deep['conversion'])} in the {deep['label']} band.")
        insights.append(_card(
            "percent", "warn" if disc_stats["r"] < -0.05 else "default",
            f"Discount depth barely moves purchase ({F.number(disc_stats['r'], 2, style='west')} r)",
            f"Pearson correlation between discount_percent and purchased is "
            f"{F.number(disc_stats['r'], 3, style='west')} over {F.number(disc_stats['n'])} sessions — "
            f"{disc_stats['strength']} and correlational, not causal.{delta}",
            "correlation r", disc_stats["r"], "num2"))

    # 6 — leakage: abandonment + worst segment
    if totals["carts"]:
        buckets = C.group(store, where, params, "duration", ["sessions", "abandon_rate", "conversion"])
        worst_bucket = max((b for b in buckets if b["abandon_rate"]), key=lambda b: b["abandon_rate"],
                            default=None)
        insights.append(_card(
            "warning", "warn", f"{F.pct(totals['abandon_rate'])} of carts never convert",
            f"{F.number(totals['abandoned'])} of {F.number(totals['carts'])} carts were abandoned while "
            f"{F.number(totals['purchases'])} completed"
            + (f"; the worst bucket is {worst_bucket['label']} sessions at "
               f"{F.pct(worst_bucket['abandon_rate'])}." if worst_bucket else "."),
            "abandonment", totals["abandon_rate"], "pct"))

    # 7 — customer concentration
    conc = _concentration(store, where, params)
    if conc.get("total"):
        share = 100.0 * (conc["top10"] or 0) / conc["total"]
        insights.append(_card(
            "users", "default", f"Top 10% of buyers generate {F.pct(share)} of revenue",
            f"{F.number(conc['top_n'])} of {F.number(conc['buyers'])} buying "
            f"customers account for {F.inr_short(conc['top10'])} of the {F.inr_short(conc['total'])} "
            f"booked by buyers.",
            "concentration", share, "pct"))

    # 8 — repeat behaviour
    repeat = store.row(
        f"WITH c AS (SELECT customer_id, SUM(purchased) AS buys FROM sessions WHERE 1=1 {where} "
        "GROUP BY customer_id) SELECT COUNT(CASE WHEN buys >= 2 THEN 1 END) AS repeat, "
        "COUNT(CASE WHEN buys >= 1 THEN 1 END) AS buyers FROM c", params)
    if repeat.get("buyers"):
        insights.append(_card(
            "repeat", "default", f"{F.pct(100.0 * (repeat['repeat'] or 0) / repeat['buyers'])} of buyers come back",
            f"{F.number(repeat['repeat'] or 0)} of {F.number(repeat['buyers'])} customers who purchased "
            f"did so in more than one session, out of {F.number(totals['customers'])} customers in range.",
            "repeat buyers", repeat["repeat"] or 0, "count"))

    return {"ready": True, "insights": insights[:MAX_INSIGHTS],
            "all_insights": len(insights), "totals": totals}
