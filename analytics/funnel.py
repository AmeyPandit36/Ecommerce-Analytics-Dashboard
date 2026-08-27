"""Customer journey: sessions -> cart -> purchase, and what moves conversion."""
from __future__ import annotations

from analytics import common as C
from core import format as F


def compute(store, where: str, params: tuple) -> dict:
    totals = C.overall(store, where, params, [
        "sessions", "carts", "purchases", "abandoned", "cart_rate", "conversion", "abandon_rate",
        "revenue", "avg_time", "avg_pages", "rating", "customers", "avg_discount"])

    sessions = int(totals["sessions"] or 0)
    carts = int(totals["carts"] or 0)
    purchases = int(totals["purchases"] or 0)
    abandoned = int(totals["abandoned"] or 0)

    steps = [
        {"name": "Sessions", "value": sessions, "pct": 100.0,
         "note": "every row in the dataset is one session", "color": "cyan"},
        {"name": "Added to cart", "value": carts, "pct": 100.0 * carts / sessions if sessions else 0,
         "note": "added_to_cart = 1", "color": "blue"},
        {"name": "Purchased", "value": purchases, "pct": 100.0 * purchases / sessions if sessions else 0,
         "note": "purchased = 1", "color": "emerald"},
    ]
    dropoffs = [
        {"name": "Session → cart", "value": sessions - carts,
         "pct": 100.0 * (sessions - carts) / sessions if sessions else 0, "color": "slate"},
        {"name": "Cart → purchase", "value": carts - purchases,
         "pct": 100.0 * (carts - purchases) / carts if carts else 0, "color": "rose"},
    ]

    devices = C.group(store, where, params, "device", ["sessions", "cart_rate", "conversion",
                                                        "abandon_rate", "revenue", "avg_time"])
    channels = C.group(store, where, params, "channel", ["sessions", "purchases", "conversion",
                                                          "revenue", "cart_rate", "abandon_rate", "aov"])
    buckets = C.group(store, where, params, "duration", ["sessions", "cart_rate", "conversion",
                                                          "abandon_rate", "avg_time", "revenue"])
    buckets = sorted(buckets, key=lambda b: {"Very Short": 0, "Short": 1, "Long": 2,
                                             "Very Long": 3}.get(b["label"], 9))
    pages = C.group(store, where, params, "pages_band", ["sessions", "conversion", "cart_rate"])
    pages = sorted(pages, key=lambda p: (p["key"] is None, p["key"]))
    times = C.group(store, where, params, "time_band", ["sessions", "conversion", "cart_rate"])
    times = sorted(times, key=lambda t: (t["key"] is None, t["key"]))
    user_type = C.group(store, where, params, "user_type", ["sessions", "conversion", "cart_rate",
                                                            "abandon_rate", "revenue", "avg_time"])

    charts = [
        C.chart("journey", "Conversion journey", "hbar", [s["name"] for s in steps],
                [{"label": "Sessions", "data": [s["value"] for s in steps],
                  "colors": [s["color"] for s in steps]}],
                subtitle=f"{F.pct(totals['conversion'])} of sessions end in a purchase • "
                         f"{F.pct(totals['abandon_rate'])} of carts are abandoned",
                span=6, unit="count", height=260),
        C.chart("dropoff", "Where sessions are lost", "bar", [d["name"] for d in dropoffs],
                [{"label": "Sessions lost", "data": [d["value"] for d in dropoffs],
                  "colors": [d["color"] for d in dropoffs]}],
                subtitle=f"{F.pct(dropoffs[0]['pct'])} never reach a cart • "
                         f"{F.pct(dropoffs[1]['pct'])} of carts never convert",
                span=6, unit="count", height=260),
        C.chart("device_funnel", "Funnel by device", "bar", [d["label"] for d in devices],
                [{"label": "Add-to-cart", "data": [d["cart_rate"] for d in devices], "color": "blue"},
                 {"label": "Conversion", "data": [d["conversion"] for d in devices], "color": "emerald"},
                 {"label": "Abandonment", "data": [d["abandon_rate"] for d in devices], "color": "rose"}],
                subtitle="device_type codes: rates are session-level", span=6, unit="pct",
                height=280),
        C.chart("channel_perf", "Marketing channel performance", "combo",
                [c["label"] for c in channels],
                [{"label": "Revenue", "data": [c["revenue"] for c in channels], "type": "bar",
                  "color": "violet"},
                 {"label": "Conversion", "data": [c["conversion"] for c in channels], "type": "line",
                  "axis": "y1", "color": "amber"}],
                subtitle="marketing_channel codes 0-5 — revenue bars, conversion line",
                span=6, unit="inr", height=280),
        C.chart("duration_effect", "Session length vs conversion", "combo",
                [b["label"] for b in buckets],
                [{"label": "Conversion", "data": [b["conversion"] for b in buckets], "type": "bar",
                  "color": "cyan"},
                 {"label": "Add-to-cart", "data": [b["cart_rate"] for b in buckets], "type": "bar",
                  "color": "blue"},
                 {"label": "Abandonment", "data": [b["abandon_rate"] for b in buckets], "type": "line",
                  "color": "rose"}],
                subtitle="session_duration_bucket (Very Short → Very Long) — do longer visits buy more?",
                span=6, unit="pct", height=280),
        C.chart("pages_effect", "Pages viewed vs conversion", "line",
                [p["label"] for p in pages],
                [{"label": "Conversion", "data": [p["conversion"] for p in pages], "color": "emerald",
                  "fill": True},
                 {"label": "Add-to-cart", "data": [p["cart_rate"] for p in pages], "color": "cyan",
                  "dash": [4, 4]}],
                subtitle="Grouped in 5-page bands of pages_viewed", span=3, unit="pct", height=260),
        C.chart("time_effect", "Time on site vs conversion", "line",
                [t["label"] for t in times],
                [{"label": "Conversion", "data": [t["conversion"] for t in times], "color": "violet",
                  "fill": True},
                 {"label": "Add-to-cart", "data": [t["cart_rate"] for t in times], "color": "amber",
                  "dash": [4, 4]}],
                subtitle="5-minute bands of time_on_site_sec", span=3, unit="pct", height=260),
    ]

    def rate_rows(groups, metric="conversion", columns=None):
        """Shared renderer; groups may not carry every metric, so read defensively."""
        return [{
            "label": g.get("label"), "sessions": F.number(g.get("sessions")),
            "cart_rate": F.pct(g.get("cart_rate")), "conversion": F.pct(g.get("conversion")),
            "abandon_rate": F.pct(g.get("abandon_rate")), "revenue": F.inr_short(g.get("revenue")),
            "aov": F.inr_short(g.get("aov")), "avg_time": F.seconds_to_mmss(g.get("avg_time")),
            "bar": round(float(g.get(metric) or 0), 2),
        } for g in groups]

    return {
        "ready": bool(int(totals["sessions"] or 0)),
        "reason": "No sessions fall inside this filter combination.",
        "totals": totals,
        "steps": steps,
        "dropoffs": dropoffs,
        "kpis": [
            C.kpi("Sessions", sessions, "count", "Rows in the dataset within filters", "default", "activity"),
            C.kpi("Carts created", carts, "count", "Sessions with added_to_cart = 1", "default", "cart"),
            C.kpi("Purchases", purchases, "count", "Sessions with purchased = 1", "positive", "check"),
            C.kpi("Carts abandoned", abandoned, "count", "Sessions with cart_abandoned = 1", "warn", "warning"),
            C.kpi("Add-to-cart rate", totals["cart_rate"], "pct", "Carts ÷ sessions", "default", "target"),
            C.kpi("Cart → purchase", (100.0 * purchases / carts) if carts else None, "pct",
                  "Purchases ÷ carts", "positive", "bolt"),
            C.kpi("Abandonment", totals["abandon_rate"], "pct", "Abandoned ÷ carts", "warn", "clock"),
            C.kpi("Avg session", totals["avg_time"], "sec", "Mean time_on_site_sec", "default", "timer"),
        ],
        "charts": charts,
        "tables": [
            C.table("Channel detail", [
                {"key": "label", "label": "Channel", "align": "left"},
                {"key": "sessions", "label": "Sessions", "align": "right"},
                {"key": "cart_rate", "label": "Add-to-cart", "align": "right"},
                {"key": "conversion", "label": "Conversion", "align": "right"},
                {"key": "abandon_rate", "label": "Abandonment", "align": "right"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
                {"key": "bar", "label": "Conv. %", "align": "right", "bar": True},
            ], rate_rows(channels), subtitle="Ordered by conversion", span=12),
            C.table("Device & user-type detail", [
                {"key": "label", "label": "Segment", "align": "left"},
                {"key": "sessions", "label": "Sessions", "align": "right"},
                {"key": "cart_rate", "label": "Add-to-cart", "align": "right"},
                {"key": "conversion", "label": "Conversion", "align": "right"},
                {"key": "abandon_rate", "label": "Abandonment", "align": "right"},
                {"key": "avg_time", "label": "Avg time", "align": "right"},
                {"key": "revenue", "label": "Revenue", "align": "right"},
            ], rate_rows(devices) + rate_rows(user_type), span=12,
                note="device_type / user_type are integer codes in the source dataset; "
                     "the dashboard deliberately does not guess their meaning."),
        ],
    }
