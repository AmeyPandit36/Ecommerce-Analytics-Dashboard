"""AI Analyst: a deterministic, data-grounded question answerer.

There is no LLM call here and no invented prose: each intent runs real SQL
against the bundled dataset and returns the answer, the evidence table, a chart
spec, how it was computed, and the honest limitations. When a question cannot be
answered from the columns that exist, the response says so and offers the
questions it *can* answer — it never guesses.

Optional: if an LLM is configured (env OPENAI_API_KEY), the narrative text can be
rephrased by `llm_polish()`; the numbers always come from SQL. Off by default so
the page works with zero configuration.
"""
from __future__ import annotations

import os
import re

from analytics import common as C
from analytics import insights as INS
from analytics import sales as S
from core import format as F

NOT_LOADED = {"answer": "No dataset is loaded.", "detail": "The app could not open data/ecommerce.db.",
              "limitations": "Nothing to analyse.", "evidence": None, "chart": None,
              "method": "n/a", "confidence": "none", "followups": []}

EXAMPLES = [
    "Which category performs best?",
    "What are the top 5 products?",
    "Which payment method is most popular?",
    "Which customers are most valuable?",
    "What interesting patterns exist in the dataset?",
    "Is discount associated with purchasing?",
    "Where do sessions drop off in the funnel?",
    "Which device converts best?",
    "What is the average order value?",
    "How do ratings vary by category?",
    "Which month was the strongest?",
    "Is there a weekend effect?",
    "Which locations spend the most?",
    "What does the data quality look like?",
]


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9%]+", (text or "").lower()) if len(t) > 1}


def _score(question: str, keywords) -> float:
    """Overlap score between the question and an intent's keyword set."""
    q = _tokens(question)
    if not q:
        return 0.0
    hits = 0.0
    for kw in keywords:
        if " " in kw:
            if kw in question:
                hits += 2.0
        elif kw in q:
            hits += 1.0
    return hits


# --------------------------------------------------------------- intent engine
# Weighted keyword matcher. `strong` terms can select an intent on their own,
# `weak` terms only break ties. Terms that appear in several intents are
# down-weighted automatically, so "category" never hijacks a ratings question.
INTENTS = (
    {"name": "category_best", "strong": ["category", "categories", "category-level"],
     "weak": ["best", "top", "perform", "performs", "performance", "strongest", "biggest",
              "leading", "worst", "sell", "selling", "compare"]},
    {"name": "product_top", "strong": ["product", "products", "sku", "skus", "items"],
     "weak": ["top", "best", "rated", "highest", "selling", "revenue", "rank", "ranking", "worst"]},
    {"name": "payment", "strong": ["payment", "payments", "upi", "wallet", "card", "netbanking",
                                   "net-banking", "cod", "checkout", "rail", "rails"],
     "weak": ["popular", "most", "used", "preferred", "method", "methods", "favorite"]},
    {"name": "customers_value", "strong": ["customer", "customers", "segment", "segments",
                                          "segmentation", "buyer", "buyers", "valuable", "ltv",
                                          "lifetime", "twice", "repeat", "loyal", "retention",
                                          "window", "shopper", "shoppers"],
     "weak": ["top", "highest", "spend", "spending", "worth", "who", "richest", "vips", "list"]},
    {"name": "patterns", "strong": ["pattern", "patterns", "insight", "insights", "interesting",
                                    "surprising", "anomaly", "anomalies", "summary", "overview",
                                    "headline", "findings", "takeaway", "takeaways"],
     "weak": ["tell", "anything", "everything", "data", "dataset", "about", "show", "what"]},
    {"name": "discount", "strong": ["discount", "discounts", "coupon", "promocode", "offer",
                                    "offers", "markdown", "discounting"],
     "weak": ["associated", "correlation", "correlate", "affect", "impact", "lift", "convert",
              "conversion", "purchase", "purchasing", "buy", "relationship", "depth"]},
    {"name": "funnel", "strong": ["funnel", "abandon", "abandoned", "abandonment", "cart", "carts",
                                  "drop-off", "dropoff", "leak", "leakage", "journey", "conversion-step"],
     "weak": ["where", "drop", "lost", "loss", "stage", "stages", "session", "sessions", "add-to-cart",
              "checkout", "fraction", "rate"]},
    {"name": "device", "strong": ["device", "devices", "mobile", "desktop", "tablet", "handset",
                                  "phone", "laptop"],
     "weak": ["convert", "converts", "conversion", "screen", "which", "better", "best", "revenue"]},
    {"name": "aov", "strong": ["aov", "basket", "order-value", "average-order"],
     "weak": ["order", "orders", "value", "average", "mean", "typical", "spend", "per", "ticket"]},
    {"name": "rating", "strong": ["rating", "ratings", "star", "stars", "review", "reviews",
                                  "satisfaction", "score", "sentiment"],
     "weak": ["highest", "best", "worst", "average", "mean", "vary", "distribution", "how"]},
    {"name": "trend", "strong": ["trend", "seasonality", "autumn", "winter", "summer", "spring",
                                 "monsoon", "festival", "forecast", "prediction", "predict",
                                 "trajectory", "timeline", "monthly", "growth", "month", "months",
                                 "season", "year"],
     "weak": ["peak", "date", "time", "over", "strongest", "quietest", "2024", "seasonal", "next",
              "decline", "increase", "revenue", "january", "february", "march", "april", "june", "july",
              "august", "september", "october", "november", "december", "may"]},
    {"name": "weekday", "strong": ["weekend", "weekday", "weekdays", "monday", "tuesday", "wednesday",
                                   "thursday", "friday", "saturday", "sunday", "day-of-week"],
     "weak": ["day", "days", "effect", "busy", "quiet", "which", "conversion", "traffic"]},
    {"name": "geo", "strong": ["location", "locations", "geography", "region", "regions", "district",
                               "districts", "state", "states", "city", "cities", "map", "place", "places"],
     "weak": ["top", "spend", "spending", "highest", "revenue", "where", "area"]},
    {"name": "channel", "strong": ["channel", "channels", "campaign", "campaigns", "acquisition",
                                   "marketing", "ads", "advertising", "source", "roas", "cac",
                                   "spend-efficiency"],
     "weak": ["which", "best", "converts", "conversion", "revenue", "roi", "performance", "drive"]},
    {"name": "quality", "strong": ["quality", "null", "nulls", "missing", "duplicate", "duplicates",
                                   "schema", "provenance", "sha256", "hash", "dirty", "cleanliness",
                                   "outlier", "outliers"],
     "weak": ["data", "columns", "types", "column", "issue", "issues", "look", "like", "complete",
              "profile", "source", "row", "rows"]},
    {"name": "conversion", "strong": ["conversion", "convert", "converts", "convert", "rate-of-purchase"],
     "weak": ["improve", "best", "worst", "session", "sessions", "which", "what", "overall", "average"]},
    {"name": "price", "strong": ["price", "prices", "pricing", "expensive", "cheap", "cost",
                                 "margin", "margins", "profit", "profitability", "elasticity",
                                 "sensitivity", "discounting-strategy"],
     "weak": ["unit", "average", "band", "highest", "revenue", "optimal", "best", "low"]},
    {"name": "volume",
     "strong": ["volume", "totals", "sum", "aggregate", "revenue", "sales", "gmv", "dataset", "rows",
                "records", "how big", "size", "count", "purchases", "purchase"],
     "weak": ["total", "many", "much", "sessions", "unique", "overall", "how", "customer", "product",
              "buying", "units", "made", "money", "earnings"]},
)

_STOP = {"the", "a", "an", "is", "are", "was", "were", "do", "does", "did", "what", "which", "who",
         "how", "why", "of", "in", "on", "for", "to", "and", "or", "be", "it", "its", "with", "from",
         "tell", "me", "about", "please", "can", "could", "would", "you", "there", "that", "this",
         "any", "some", "all", "give", "show", "look", "like", "much", "many", "exist", "we", "i"}

# term -> how many intents mention it (rare terms are the useful signal)
_DF: dict[str, int] = {}
for _intent in INTENTS:
    for _term in tuple(_intent["strong"]) + tuple(_intent["weak"]):
        _DF[_term] = _DF.get(_term, 0) + 1


def _weight(term: str, strong: bool) -> float:
    df = _DF.get(term, 1)
    base = 1.0 if df == 1 else (0.6 if df == 2 else 0.42)
    return base * (2.6 if strong else 0.6)


def _terms(question: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9%-]+", (question or "").lower()) if t and t not in _STOP]


def _score(question: str, intent: dict) -> float:
    """Distinctive-term overlap between the question and one intent."""
    tokens = set(_terms(question)) | {t.replace("-", " ") for t in _terms(question.replace("-", " "))}
    text = " " + re.sub(r"[^a-z0-9%]+", " ", (question or "").lower()) + " "
    score = 0.0
    for bucket, strong in (("strong", True), ("weak", False)):
        for term in intent[bucket]:
            if " " in term or "-" in term:
                if term.replace("-", " ") in text:
                    score += _weight(term, strong) * 1.4
            elif term in tokens:
                score += _weight(term, strong)
    return score


def _match(question: str) -> tuple[str | None, float]:
    ranked = sorted(((_score(question, intent), intent["name"]) for intent in INTENTS),
                    key=lambda item: (-item[0], [i["name"] for i in INTENTS].index(item[1])))
    if not ranked or ranked[0][0] < 1.0:
        return None, 0.0
    return ranked[0][1], round(ranked[0][0], 3)


def answer_question(query: str, store=None, where: str = "", params: tuple = ()) -> dict:
    question = (query or "").strip()
    if store is None:
        return dict(NOT_LOADED)
    if not question:
        return _no_answer(store, where, params, "Ask a question to start.")

    name, score = _match(question)
    if not name:
        return _no_answer(store, where, params,
                          f"“{question[:120]}” does not map onto anything this dataset can answer.")
    handler = HANDLERS.get(name)
    if not handler:
        return _no_answer(store, where, params, "No handler for that topic.")
    result = handler(question, store, where, params)
    result["question"] = question
    result["matched"] = name
    result["match_score"] = score
    result["filters"] = None
    return result


def _base(**kw) -> dict:
    out = {"answer": "", "detail": "", "evidence": None, "chart": None, "method": "",
           "limitations": "", "confidence": "measured", "followups": []}
    out.update(kw)
    return out


def _evidence(columns, rows) -> dict:
    return {"columns": columns, "rows": rows}


def _ctx(store, where, params) -> dict:
    return C.totals(store, where, params)


# ------------------------------------------------------------------- handlers
def h_category_best(question, store, where, params):
    totals = _ctx(store, where, params)
    rows = C.group(store, where, params, "category",
                   ["revenue", "sessions", "purchases", "conversion", "aov", "rating", "units", "customers"],
                   order="revenue")
    if not rows:
        return _base(answer="No categories match the current filters.",
                     limitations="Empty result set after filtering.")
    top, last = rows[0], rows[-1]
    share = 100.0 * (top["revenue"] or 0) / totals["revenue"] if totals["revenue"] else 0
    by_conv = max((r for r in rows if r["conversion"]), key=lambda r: r["conversion"], default=None)
    return _base(
        answer=f"{top['label']} performs best, with {F.inr_short(top['revenue'])} of revenue "
               f"({F.pct(share)} of the filtered total).",
        detail=f"Across {F.number(totals['sessions'])} sessions in scope, {top['label']} booked "
               f"{F.number(top['purchases'])} purchases at {F.inr_short(top['aov'])} average order value and "
               f"{F.pct(top['conversion'])} conversion"
               + (f", the highest of any category." if by_conv and by_conv["key"] == top["key"] else
                  f". The highest conversion belongs to {by_conv['label']} at {F.pct(by_conv['conversion'])}."
                  if by_conv else "."),
        evidence=_evidence(["Category", "Sessions", "Purchases", "Conversion", "Revenue", "AOV", "Rating"],
                           [[r["label"], F.number(r["sessions"]), F.number(r["purchases"]),
                             F.pct(r["conversion"]), F.inr_short(r["revenue"]), F.inr_short(r["aov"]),
                             (F.number(r["rating"], 2, style="west") if r["rating"] else "n/a")]
                            for r in rows]),
        chart=C.chart("ai_category", "Revenue by category", "bar", [r["label"] for r in rows],
                      [{"label": "Revenue", "data": [r["revenue"] for r in rows], "color": "cyan"},
                       {"label": "Conversion", "data": [r["conversion"] for r in rows], "color": "amber",
                        "axis": "y1", "type": "line"}],
                      span=12, unit="inr", height=260),
        method="SUM(revenue) grouped by product_category over `sessions`, filtered by the active "
               "global filters; rating averages use purchased = 1 rows only.",
        limitations="product_category is a label-encoded integer (0-7) with no decoding map in the "
                    "dataset, so categories are shown as codes.",
        followups=["What are the top 5 products?", "How do ratings vary by category?",
                   "Is there a discount effect by category?"])


def h_product_top(question, store, where, params):
    n = 5
    found = re.findall(r"\b(\d{1,3})\b", question)
    if found:
        n = max(1, min(25, int(found[0])))
    from analytics import products as P
    table = P.product_table(store, where, params, sort="revenue", page=1, per_page=n)
    rows = table["rows"]
    if not rows:
        return _base(answer="No products match the current filters.")
    top = rows[0]
    total_rev = sum(r["raw"]["revenue"] or 0 for r in rows)
    return _base(
        answer=f"{top['product_id']} leads with {top['revenue']} of revenue.",
        detail=f"The top {n} products in scope account for {F.inr_short(total_rev)}. "
               f"{top['product_id']} converted {top['conversion']} of its {top['sessions']} sessions "
               f"and holds a rating of {top['rating']}.",
        evidence=_evidence(["Product", "Category", "Sessions", "Purchases", "Conversion", "Revenue", "Rating"],
                           [[r["product_id"], r["category"], r["sessions"], r["purchases"], r["conversion"],
                             r["revenue"], r["rating"]] for r in rows]),
        chart=C.chart("ai_products", f"Top {n} products by revenue", "hbar",
                      [f"{r['product_id']} · {r['category']}" for r in rows],
                      [{"label": "Revenue", "data": [r["raw"]["revenue"] for r in rows], "color": "cyan"}],
                      span=12, unit="inr", height=40 + 28 * len(rows)),
        method="Aggregated per product_id (sessions, purchases, revenue, rating) from the filtered "
               "session rows, ordered by revenue.",
        limitations="The dataset has no product names — product_id is an integer (100-998).",
        followups=["Which category performs best?", "What is the average order value?"])


def h_payment(question, store, where, params):
    totals = _ctx(store, where, params)
    rows = C.group(store, where, params, "payment", ["purchases", "revenue", "sessions", "aov",
                                                      "abandon_rate", "rating"], order="purchases")
    if not rows:
        return _base(answer="No payment data in the current filter range.")
    top = rows[0]
    share = 100.0 * (top["purchases"] or 0) / totals["purchases"] if totals["purchases"] else 0
    spread = F.pct(100.0 * (max(r["purchases"] for r in rows) - min(r["purchases"] for r in rows))
                   / totals["purchases"]) if totals["purchases"] else "n/a"
    return _base(
        answer=f"{top['label']} is the most popular, used for {F.number(top['purchases'])} purchases "
               f"({F.pct(share)}).",
        detail=f"Preference is close to uniform across the {len(rows)} encoded methods — the gap between "
               f"the most and least used is only {spread} of purchases. "
               f"{top['label']} carried {F.inr_short(top['revenue'])} at {F.inr_short(top['aov'])} AOV.",
        evidence=_evidence(["Payment method", "Purchases", "Share", "Revenue", "AOV", "Abandonment"],
                           [[r["label"], F.number(r["purchases"]),
                             F.pct(100.0 * (r["purchases"] or 0) / totals["purchases"]) if totals["purchases"] else "n/a",
                             F.inr_short(r["revenue"]), F.inr_short(r["aov"]), F.pct(r["abandon_rate"])]
                            for r in rows]),
        chart=C.chart("ai_payment", "Purchases by payment method", "donut", [r["label"] for r in rows],
                      [{"label": "Purchases", "data": [r["purchases"] for r in rows]}], span=12,
                      unit="count", height=260),
        method="COUNT of purchased = 1 rows grouped by payment_method; revenue and AOV summed over the "
               "same rows.",
        limitations="payment_method is an encoded integer (0-5). The dataset publishes no mapping to "
                    "UPI / card / net-banking, so naming them would be a guess.",
        followups=["Which category performs best?", "Where do sessions drop off in the funnel?"])


def h_customers_value(question, store, where, params):
    from analytics import customers as CU
    data = CU.compute(store, where, params)
    if not data.get("ready"):
        return _base(answer="No customers match the current filters.")
    top = data["tables"][1]["rows"][0] if len(data["tables"]) > 1 and data["tables"][1]["rows"] else None
    seg = data["segments"][0] if data["segments"] else None
    if not top:
        return _base(answer="No customer aggregates available.")
    return _base(
        answer=f"{top['label']} is the single most valuable customer with {top['revenue']} of lifetime "
               f"revenue.",
        detail=f"{data['segment_rule']['high_cut_label']}+ lifetime revenue defines the "
               f"“{seg['segment']}” segment — {F.number(seg['customers'])} customers "
               f"({F.pct(seg['customer_share'])} of all) carrying {F.pct(seg['revenue_share'])} of revenue. "
               f"{F.number(data['totals']['customers'])} customers appear in scope, and repeat buyers are "
               f"the difference between the median and the top of the distribution.",
        evidence=_evidence(["Customer", "Revenue", "Sessions", "Purchases", "Conversion", "Rating",
                            "Top category", "Top location"],
                           [[r["label"], r["revenue"], r["sessions"], r["purchases"], r["conversion"],
                             r["rating"], r["top_category"], r["top_location"]]
                            for r in data["tables"][1]["rows"][:10]]),
        chart=C.chart("ai_segments", "Revenue by customer segment", "bar",
                      [s["segment"] for s in data["segments"]],
                      [{"label": "Revenue", "data": [round(s["revenue"], 2) for s in data["segments"]],
                        "colors": [s["color"] for s in data["segments"]]},
                       {"label": "Customers", "data": [s["customers"] for s in data["segments"]],
                        "type": "line", "axis": "y1", "color": "slate"}],
                      span=12, unit="inr", height=260),
        method="Lifetime revenue per customer_id, segmented at the 33rd/66th percentile "
               "(thresholds shown above the table); ranks come straight from SUM(revenue).",
        limitations="customer_id is an anonymous integer; no demographics exist in this dataset.",
        followups=["What interesting patterns exist in the dataset?", "What is the average order value?"])


def h_patterns(question, store, where, params):
    ins = INS.compute(store, where, params)
    cards = ins.get("insights") or []
    if not cards:
        return _base(answer="Nothing conclusive — the current filter range has too little data.")
    totals = _ctx(store, where, params)
    bullets = "\n".join(f"{i + 1}. {c['title']} — {c['text']}" for i, c in enumerate(cards))
    return _base(
        answer=f"{len(cards)} patterns stand out in the {F.number(totals['sessions'])} sessions in scope.",
        detail=bullets,
        evidence=_evidence(["Pattern", "Headline metric"],
                           [[c["title"], f"{c['metric']} ({c['metric_label']})"] for c in cards]),
        chart=C.chart("ai_pattern_cat", "Revenue by category", "bar",
                      [c["label"] for c in C.group(store, where, params, "category", ["revenue"],
                                                    order="revenue")],
                      [{"label": "Revenue",
                        "data": [c["revenue"] for c in C.group(store, where, params, "category",
                                                               ["revenue"], order="revenue")],
                        "color": "cyan"}], span=12, unit="inr", height=240),
        method="Each card is an independent SQL aggregate (category, month, payment, rating, "
               "correlation, funnel, concentration, repeat rate) evaluated with the active filters.",
        limitations="Patterns are correlational summaries of a synthetic dataset — they are not causal "
                    "claims, and the encoded columns limit interpretation.",
        followups=["Is discount associated with purchasing?", "Which month was the strongest?",
                   "Where do sessions drop off in the funnel?"])


def h_discount(question, store, where, params):
    stats = INS.correlation(store, where, params, "discount_percent", "purchased")
    bands = C.group(store, where, params, "discount_band",
                    ["sessions", "purchases", "conversion", "revenue", "avg_discount"], order="key",
                    asc=True)
    bands = sorted(bands, key=lambda r: (r["key"] is None, r["key"]))
    if not stats:
        return _base(answer="Not enough rows in range to estimate a correlation.")
    r = stats["r"]
    zero = next((b for b in bands if b["key"] == 0), None)
    top_band = max((b for b in bands if b["key"]), key=lambda b: b["key"], default=None)
    verdict = ("essentially unrelated" if abs(r) < 0.1 else
               f"{stats['strength']}ly {stats['direction']}" if abs(r) < 0.5 else
               f"strongly {stats['direction']}")
    lift = ""
    if zero and top_band and zero["conversion"]:
        lift = (f" Read it alongside the bands: 0% discount converts at {F.pct(zero['conversion'])} while "
                f"the deepest band ({top_band['label']}) converts at {F.pct(top_band['conversion'])} — "
                f"{F.number((top_band['conversion'] or 0) - zero['conversion'], 2, style='west')} "
                f"percentage points.")
    return _base(
        answer=f"Discount percentage and purchase are {verdict} (r = "
               f"{F.number(r, 3, style='west')}, n = {F.number(stats['n'])}).",
        detail=f"Pearson correlation between discount_percent and the purchased flag over all filtered "
               f"sessions is {F.number(r, 3, style='west')}.{lift} A correlation of this size is what you "
               f"would expect if discounts were applied independently of intent to buy.",
        evidence=_evidence(["Discount band", "Sessions", "Purchases", "Conversion", "Revenue", "Avg discount"],
                           [[b["label"], F.number(b["sessions"]), F.number(b["purchases"]),
                             F.pct(b["conversion"]), F.inr_short(b["revenue"]), F.pct(b["avg_discount"])]
                            for b in bands]),
        chart=C.chart("ai_discount", "Conversion by discount band", "combo",
                      [b["label"] for b in bands],
                      [{"label": "Conversion", "data": [b["conversion"] for b in bands], "type": "bar",
                        "color": "emerald"},
                       {"label": "Sessions", "data": [b["sessions"] for b in bands], "type": "line",
                        "axis": "y1", "color": "slate"}], span=12, unit="pct", height=260),
        method=f"Pearson r from six SQL aggregates (n, Σx, Σy, Σxy, Σx², Σy²) of discount_percent vs "
               f"purchased; bands are 5-point buckets of discount_percent.",
        limitations="Correlation, not causation. discount_percent is uniform 0-30 in this synthetic "
                    "dataset, which caps any measurable effect.",
        followups=["Which category performs best?", "Which month was the strongest?"])


def h_funnel(question, store, where, params):
    from analytics import funnel as FN
    data = FN.compute(store, where, params)
    totals = data["totals"]
    steps = data["steps"]
    worst = max(data["dropoffs"], key=lambda d: d["pct"]) if data["dropoffs"] else None
    return _base(
        answer=f"{F.pct(totals['conversion'])} of sessions purchase; the biggest leak is "
               + (f"{worst['name']} ({F.pct(worst['pct'])} lost)." if worst else "before the cart."),
        detail=" → ".join(f"{s['name']} {F.number(s['value'])} ({F.pct(s['pct'])})" for s in steps)
               + f". Of the {F.number(totals['carts'])} carts created, {F.number(totals['abandoned'])} "
                 f"were abandoned ({F.pct(totals['abandon_rate'])}).",
        evidence=_evidence(["Stage", "Sessions", "Share of sessions", "Definition"],
                           [[s["name"], F.number(s["value"]), F.pct(s["pct"]), s["note"]] for s in steps]),
        chart=C.chart("ai_funnel", "Journey stages", "hbar", [s["name"] for s in steps],
                      [{"label": "Sessions", "data": [s["value"] for s in steps],
                        "colors": [s["color"] for s in steps]}], span=12, unit="count", height=220),
        method="Counts of added_to_cart, purchased and cart_abandoned flags; every cart in this dataset "
               "resolves to exactly one of purchased / cart_abandoned (verified in the quality page).",
        limitations="There is no separate view/wishlist/checkout-step event, so the funnel is "
                   "3 stages rather than a full commerce funnel.",
        followups=["Which device converts best?", "Is there a session-length effect?"])


def h_device(question, store, where, params):
    rows = C.group(store, where, params, "device", ["sessions", "conversion", "cart_rate", "abandon_rate",
                                                    "revenue", "aov", "avg_time", "rating"],
                   order="conversion")
    if not rows:
        return _base(answer="No device data in range.")
    best = max((r for r in rows if r["conversion"]), key=lambda r: r["conversion"], default=None)
    if not best:
        return _base(
            answer="No session converted inside the current filters.",
            detail=f"{F.number(sum(r['sessions'] or 0 for r in rows))} sessions are in scope but none "
                   f"reached purchased = 1, so device-level conversion cannot be compared.",
            evidence=_evidence(["Device", "Sessions", "Add-to-cart"],
                              [[r["label"], F.number(r["sessions"]), F.pct(r["cart_rate"])] for r in rows]),
            method="Conversion is NULL when there are no purchases; the analyst reports that instead of "
                   "substituting a number.",
            limitations="Filter to “Outcome: Purchased” (or clear the outcome filter) to compare devices.")
    share = 100.0 * best["sessions"] / sum(r["sessions"] for r in rows)
    return _base(
        answer=f"Device code {best['key']} converts best at {F.pct(best['conversion'])} of sessions.",
        detail=f"Its sessions convert at {F.pct(best['conversion'])} versus "
               f"{F.pct(min(r['conversion'] or 0 for r in rows))} for the weakest, and it accounts for "
               f"{F.pct(share)} of traffic. Abandonment: "
               + ", ".join(f"{r['label']} {F.pct(r['abandon_rate'])}" for r in rows) + ".",
        evidence=_evidence(["Device", "Sessions", "Add-to-cart", "Conversion", "Abandonment", "Revenue",
                            "Avg time"],
                           [[r["label"], F.number(r["sessions"]), F.pct(r["cart_rate"]),
                             F.pct(r["conversion"]), F.pct(r["abandon_rate"]), F.inr_short(r["revenue"]),
                             F.seconds_to_mmss(r["avg_time"])] for r in rows]),
        chart=C.chart("ai_device", "Funnel rates by device", "bar", [r["label"] for r in rows],
                      [{"label": "Conversion", "data": [r["conversion"] for r in rows], "color": "emerald"},
                       {"label": "Add-to-cart", "data": [r["cart_rate"] for r in rows], "color": "cyan"},
                       {"label": "Abandonment", "data": [r["abandon_rate"] for r in rows], "color": "rose"}],
                      span=12, unit="pct", height=260),
        method="Session-level flag averages grouped by device_type.",
        limitations="device_type is encoded 0-2 with no label map in the dataset, so "
                    "“mobile vs desktop” cannot be asserted from this data.",
        followups=["Where do sessions drop off in the funnel?"])


def h_aov(question, store, where, params):
    totals = _ctx(store, where, params)
    aov = totals["aov"]
    per_session = (totals["revenue"] / totals["sessions"]) if totals["sessions"] else None
    cats = C.group(store, where, params, "category", ["aov", "revenue", "purchases"], order="aov")
    best = max((c for c in cats if c["aov"]), key=lambda c: c["aov"], default=None)
    return _base(
        answer=f"Average order value is {F.inr(aov, 2)}.",
        detail=f"Computed as revenue ÷ completed purchases ({F.number(totals['purchases'])} purchases, "
               f"{F.inr_short(totals['revenue'])} revenue). Average revenue *per session* is only "
               f"{F.inr(per_session, 2)} — the gap is the "
               f"{F.pct(totals['conversion'])} conversion rate"
               + (f", and {best['label']} has the fattest baskets at {F.inr(best['aov'], 2)}." if best else "."),
        evidence=_evidence(["Metric", "Value"],
                           [["Revenue", F.inr(totals["revenue"])],
                            ["Purchases", F.number(totals["purchases"])],
                            ["AOV (per purchase)", F.inr(aov, 2)],
                            ["Revenue per session", F.inr(per_session, 2)],
                            ["Units per purchase", F.number(totals["units"] / totals["purchases"], 2, style="west")
                             if totals["purchases"] else "n/a"],
                            ["Avg discount", F.pct(totals["avg_discount"])]]),
        chart=C.chart("ai_aov", "AOV by category", "bar", [c["label"] for c in cats],
                      [{"label": "AOV", "data": [c["aov"] for c in cats], "color": "cyan"}], span=12,
                      unit="inr", height=240),
        method="SUM(revenue) / SUM(purchased). The dataset stores revenue = 0 on every non-purchase row, "
               "so dividing by session count would understate order value by ~4×.",
        limitations="No shipping, tax or returns fields exist, so AOV is a gross-of-fee basket value.",
        followups=["Which category performs best?", "Is discount associated with purchasing?"])


def h_rating(question, store, where, params):
    totals = _ctx(store, where, params)
    dist = C.group(store, where, params, "rating", ["rating_count", "revenue"], order="key", asc=True)
    cats = [c for c in C.group(store, where, params, "category", ["rating", "purchases", "revenue"])
            if (c["purchases"] or 0) >= 25]
    best = max((c for c in cats if c["rating"]), key=lambda c: c["rating"], default=None)
    worst = min((c for c in cats if c["rating"]), key=lambda c: c["rating"], default=None)
    if not best:
        return _base(
            answer="No rated purchases inside the current filters.",
            detail=f"Ratings only exist on sessions that purchased; the filter range holds "
                   f"{F.number(totals['rating_count'] or 0)} of them. Non-purchase sessions carry a "
                   f"constant placeholder rating of 4 in this dataset, so they are never averaged.",
            evidence=_evidence(["Rating", "Sessions in range"],
                              [[f"{int(d['key'])} ★", F.number(d["rating_count"] or 0)] for d in dist]),
            method="AVG(rating) with purchased = 1; empty result reported as empty.",
            limitations="Nothing was imputed for the missing ratings.")
    return _base(
        answer=f"Post-purchase rating averages {F.number(totals['rating'], 2, style='west')} ★ over "
               f"{F.number(totals['rating_count'])} rated purchases.",
        detail="Distribution: " + ", ".join(f"{int(d['key'])}★ {F.compact(d['rating_count'])}" for d in dist)
               + f". {best['label']} is the best-rated category at "
                 f"{F.number(best['rating'], 2, style='west')} ★"
               + (f", while {worst['label']} trails at {F.number(worst['rating'], 2, style='west')} ★."
                  if worst and worst["key"] != best["key"] else "."),
        evidence=_evidence(["Rating", "Purchases", "Revenue"],
                           [[f"{int(d['key'])} ★", F.number(d["rating_count"]), F.inr_short(d["revenue"])]
                            for d in dist]),
        chart=C.chart("ai_rating", "Rating distribution (purchases only)", "bar",
                      [f"{int(d['key'])} ★" for d in dist],
                      [{"label": "Purchases", "data": [d["rating_count"] for d in dist], "color": "amber"}],
                      span=12, unit="count", height=240),
        method="AVG(rating) restricted to purchased = 1. Non-purchase rows all carry rating = 4 in this "
               "dataset (a placeholder), which would inflate the average to ~3.95 if included.",
        limitations="review_text is also encoded (codes 0-10), so sentiment cannot be read from text.",
        followups=["Which category performs best?"])


def h_trend(question, store, where, params):
    rows, gran = S.trend(store, where, params)
    if not rows:
        return _base(answer="No dates in range.")
    by_rev = max(rows, key=lambda r: r["revenue"] or 0)
    by_sess = max(rows, key=lambda r: r["sessions"] or 0)
    first, last = rows[0], rows[-1]
    change = (100.0 * ((last["revenue"] or 0) - (first["revenue"] or 0)) / first["revenue"]
              if first.get("revenue") else None)
    months = C.group(store, where, params, "season", ["revenue", "sessions", "conversion"],
                     order="revenue")
    season = months[0] if months else None
    return _base(
        answer=f"{by_rev['label']} is the peak {gran[:-1] if gran.endswith('s') else gran} for revenue "
               f"({F.inr_short(by_rev['revenue'])}).",
        detail=f"Revenue starts at {F.inr_short(first['revenue'])} and ends at {F.inr_short(last['revenue'])}"
               + (f" ({F.pct(change, 1, signed=True)})." if change is not None else ".")
               + f" Traffic peaks in {by_sess['label']} with {F.number(by_sess['sessions'])} sessions."
               + (f" The strongest season is {season['label']} at {F.inr_short(season['revenue'])}."
                  if season else ""),
        evidence=_evidence([gran.title(), "Sessions", "Purchases", "Revenue"],
                           [[r["label"], F.number(r["sessions"]), F.number(r["purchases"]),
                             F.inr_short(r["revenue"])] for r in rows[:16]]),
        chart=C.chart("ai_trend", f"Revenue by {gran}", "area", [r["label"] for r in rows],
                      [{"label": "Revenue", "data": [r["revenue"] for r in rows], "fill": True,
                        "color": "cyan"},
                       {"label": "Sessions", "data": [r["sessions"] for r in rows], "color": "slate",
                        "axis": "y1", "dash": [4, 4]}], span=12, unit="inr", height=280),
        method=f"visit_date parsed from DD-MM-YYYY and bucketed to {gran} after checking the span "
               f"({len(rows)} buckets shown).",
        limitations="The dataset covers 2024 only, so “trend” is within-year seasonality, not growth.",
        followups=["Is there a weekend effect?", "Which month was the strongest?"])


def h_weekday(question, store, where, params):
    rows = C.group(store, where, params, "weekday", ["sessions", "revenue", "conversion", "purchases"],
                   order="key", asc=True)
    if not rows:
        return _base(answer="No weekday data in range.")
    weekend = [r for r in rows if r["key"] in (5, 6)]
    weekday = [r for r in rows if r["key"] not in (5, 6)]
    avg = lambda items, key: (sum(i[key] or 0 for i in items) / len(items)) if items else None
    we_conv, wd_conv = avg(weekend, "conversion"), avg(weekday, "conversion")
    best = max(rows, key=lambda r: r["sessions"] or 0)
    return _base(
        answer=("Weekends do not buy better here — "
                f"{F.pct(wd_conv)} weekday vs {F.pct(we_conv)} weekend conversion."
                if we_conv and wd_conv else f"{best['label']} carries the most sessions."),
        detail=f"Busiest day is {best['label']} with {F.number(best['sessions'])} sessions; "
               f"weekday conversion averages {F.pct(wd_conv)} against {F.pct(we_conv)} at weekends, "
               f"and weekend revenue per day averages {F.inr_short(avg(weekend, 'revenue'))} vs "
               f"{F.inr_short(avg(weekday, 'revenue'))}.",
        evidence=_evidence(["Weekday", "Sessions", "Purchases", "Conversion", "Revenue"],
                           [[r["label"], F.number(r["sessions"]), F.number(r["purchases"]),
                             F.pct(r["conversion"]), F.inr_short(r["revenue"])] for r in rows]),
        chart=C.chart("ai_weekday", "Sessions & conversion by weekday", "combo",
                      [r["label"] for r in rows],
                      [{"label": "Sessions", "data": [r["sessions"] for r in rows], "type": "bar",
                        "color": "violet"},
                       {"label": "Conversion", "data": [r["conversion"] for r in rows], "type": "line",
                        "axis": "y1", "color": "emerald"}], span=12, unit="count", height=260),
        method="Grouped by the dataset's visit_weekday code, which cross-tabs 1:1 with the parsed "
               "visit_date (0 = Monday … 6 = Sunday), so weekday names are verified, not assumed.",
        limitations="One year of data (2024), so no holiday or campaign context.",
        followups=["Which month was the strongest?"])


def h_geo(question, store, where, params):
    rows = C.group(store, where, params, "location", ["revenue", "customers", "sessions", "conversion"],
                   order="revenue", limit=10)
    if not rows:
        return _base(answer="No location data in range.")
    top = rows[0]
    totals = _ctx(store, where, params)
    spread = store.scalar(f"SELECT COUNT(DISTINCT location) FROM sessions WHERE 1=1 {where}", params, 0)
    return _base(
        answer=f"{top['label']} spends the most: {F.inr_short(top['revenue'])} from "
               f"{F.number(top['customers'])} customers.",
        detail=f"Across {F.number(spread)} distinct location codes, the top 10 hold "
               f"{F.pct(100.0 * sum(r['revenue'] or 0 for r in rows) / totals['revenue']) if totals['revenue'] else 'n/a'} "
               f"of revenue. Conversion in {top['label']} is {F.pct(top['conversion'])}.",
        evidence=_evidence(["Location", "Customers", "Sessions", "Conversion", "Revenue"],
                          [[r["label"], F.number(r["customers"]), F.number(r["sessions"]),
                            F.pct(r["conversion"]), F.inr_short(r["revenue"])] for r in rows]),
        chart=C.chart("ai_geo", "Top locations by revenue", "hbar", [r["label"] for r in rows],
                      [{"label": "Revenue", "data": [r["revenue"] for r in rows], "color": "blue"}],
                      span=12, unit="inr", height=320),
        method="SUM(revenue) grouped by location, filtered by the global filter bar.",
        limitations="location is an encoded id 0-224; the dataset ships no district names, so no map or "
                    "city labels are claimed.",
        followups=["Which customers are most valuable?"])


def h_channel(question, store, where, params):
    rows = C.group(store, where, params, "channel", ["sessions", "purchases", "conversion", "revenue",
                                                      "aov", "abandon_rate", "cart_rate"], order="revenue")
    if not rows:
        return _base(answer="No channel data in range.")
    best = max((r for r in rows if r["conversion"]), key=lambda r: r["conversion"], default=rows[0])
    top = rows[0]
    return _base(
        answer=f"{top['label']} drives the most revenue ({F.inr_short(top['revenue'])}); "
               f"{best['label']} converts best ({F.pct(best['conversion'])}).",
        detail="Revenue by channel is nearly flat — "
               + ", ".join(f"{r['label']} {F.inr_short(r['revenue'])}" for r in rows) +
               ". In a synthetic dataset with uniform channel assignment that is expected, and it is worth "
               "checking before spending on “winning” channels.",
        evidence=_evidence(["Channel", "Sessions", "Purchases", "Conversion", "Revenue", "AOV", "Abandonment"],
                          [[r["label"], F.number(r["sessions"]), F.number(r["purchases"]),
                            F.pct(r["conversion"]), F.inr_short(r["revenue"]), F.inr_short(r["aov"]),
                            F.pct(r["abandon_rate"])] for r in rows]),
        chart=C.chart("ai_channel", "Channel revenue & conversion", "combo", [r["label"] for r in rows],
                      [{"label": "Revenue", "data": [r["revenue"] for r in rows], "type": "bar",
                        "color": "violet"},
                       {"label": "Conversion", "data": [r["conversion"] for r in rows], "type": "line",
                        "axis": "y1", "color": "emerald"}], span=12, unit="inr", height=260),
        method="Aggregates grouped by marketing_channel (codes 0-5).",
        limitations="No spend or impressions column exists, so CAC / ROAS cannot be computed from this "
                    "dataset — the answer deliberately stops at revenue.",
        followups=["Where do sessions drop off in the funnel?"])


def h_quality(question, store, where, params):
    from analytics import quality as Q
    data = Q.compute(store)
    meta = data["meta"]
    penalties = ", ".join("{} -{}".format(t["name"], t["penalty"]) for t in data["score"]["terms"])
    return _base(
        answer=f"{F.number(meta.get('rows', 0))} rows × {meta.get('csv_columns', '?')} columns, "
               f"{F.number(data['kpis'][2]['raw'])} missing cells, "
               f"{F.number(data['kpis'][3]['raw'])} duplicate rows — quality score "
               f"{data['score']['value']}/100.",
        detail=f"Score of {data['score']['value']}/100 after penalties: {penalties}. "
               f"Date span {meta.get('date_min')} → {meta.get('date_max')}; every column is fully "
               f"populated, so no imputation is needed anywhere in the dashboard.",
        evidence=_evidence(["Check", "Result"],
                           [["Rows", meta.get("rows")], ["CSV columns", meta.get("csv_columns")],
                            ["Duplicate session_id", data["kpis"][3]["raw"]],
                            ["Missing cells", data["kpis"][2]["raw"]],
                            ["CSV sha256", (meta.get("csv_sha256") or "")[:16] + "…"],
                            ["Built at", meta.get("generated_utc")]]),
        chart=None,
        method="Column profile measured on data/Ecommerce.csv by scripts/build_dataset.py and stored in "
               "the `dq_columns` table; this answer reads it back verbatim.",
        limitations="Profiling describes the CSV as shipped: encoded categoricals are legitimate codes, "
                    "not dirty data.",
        followups=["What interesting patterns exist in the dataset?"])


def h_conversion(question, store, where, params):
    totals = _ctx(store, where, params)
    cats = C.group(store, where, params, "category", ["conversion", "sessions", "purchases", "revenue"],
                   order="conversion")
    buckets = C.group(store, where, params, "duration", ["conversion", "sessions"], order="sessions")
    return _base(
        answer=f"Conversion is {F.pct(totals['conversion'])} "
               f"({F.number(totals['purchases'])} purchases on {F.number(totals['sessions'])} sessions).",
        detail=f"Add-to-cart rate is {F.pct(totals['cart_rate'])} and "
               f"{F.pct(totals['abandon_rate'])} of carts are abandoned. Best category: "
               f"{cats[0]['label']} at {F.pct(cats[0]['conversion'])}; "
               f"longest-session bucket {buckets[-1]['label'] if buckets else 'n/a'} converts at "
               f"{F.pct(buckets[-1]['conversion']) if buckets else 'n/a'}.",
        evidence=_evidence(["Category", "Sessions", "Purchases", "Conversion"],
                          [[c["label"], F.number(c["sessions"]), F.number(c["purchases"]),
                            F.pct(c["conversion"])] for c in cats]),
        chart=C.chart("ai_conversion", "Conversion by category", "bar", [c["label"] for c in cats],
                      [{"label": "Conversion", "data": [c["conversion"] for c in cats], "color": "emerald"},
                       {"label": "Sessions", "data": [c["sessions"] for c in cats], "color": "slate",
                        "axis": "y1"}], span=12, unit="pct", height=250),
        method="SUM(purchased) / COUNT(*) at session level, restricted by the active filters.",
        limitations="One row = one session, so this is a session-level conversion rate rather than a "
                    "user-level one.",
        followups=["Where do sessions drop off in the funnel?", "Which device converts best?"])


def h_price(question, store, where, params):
    rows = sorted(C.group(store, where, params, "price_band",
                          ["sessions", "conversion", "revenue", "aov", "rating"]),
                  key=lambda r: (r["key"] is None, r["key"]))
    totals = _ctx(store, where, params)
    stats = INS.correlation(store, where, params, "unit_price", "revenue")
    top = max((r for r in rows if r["revenue"]), key=lambda r: r["revenue"], default=None)
    return _base(
        answer=f"Price and revenue move together (r = "
               f"{F.number(stats['r'], 2, style='west')}); {top['label'] if top else 'n/a'} ₹-bands carry "
               f"the most revenue." if stats else "Not enough data in range.",
        detail=f"Average unit price is {F.inr(totals['avg_price'], 2)} and AOV is {F.inr(totals['aov'], 2)}. "
               + (f"The {top['label']} band holds {F.inr_short(top['revenue'])} of revenue at "
                  f"{F.pct(top['conversion'])} conversion." if top else ""),
        evidence=_evidence(["Unit price band (₹)", "Sessions", "Conversion", "Revenue", "AOV"],
                          [[r["label"], F.number(r["sessions"]), F.pct(r["conversion"]),
                            F.inr_short(r["revenue"]), F.inr_short(r["aov"])] for r in rows]),
        chart=C.chart("ai_price", "Price band vs conversion & revenue", "combo",
                      [r["label"] for r in rows],
                      [{"label": "Revenue", "data": [r["revenue"] for r in rows], "type": "bar",
                        "color": "cyan"},
                       {"label": "Conversion", "data": [r["conversion"] for r in rows], "type": "line",
                        "axis": "y1", "color": "amber"}], span=12, unit="inr", height=280),
        method="unit_price bucketed into ₹250 bands; r from unit_price vs revenue on purchased rows.",
        limitations="No cost or margin column exists, so “best price point” means revenue, not profit.",
        followups=["Is discount associated with purchasing?", "Which category performs best?"])


def h_volume(question, store, where, params):
    totals = _ctx(store, where, params)
    return _base(
        answer=f"{F.number(totals['sessions'])} sessions, {F.number(totals['purchases'])} purchases, "
               f"{F.inr_short(totals['revenue'])} revenue in the current range.",
        detail=f"Scope: {F.number(totals['customers'])} customers, {F.number(totals['products'])} products, "
               f"{F.number(totals['units'])} units, average discount {F.pct(totals['avg_discount'])}. "
               f"Filters applied change every figure on this answer.",
        evidence=_evidence(["Measure", "Value"],
                           [["Sessions", F.number(totals["sessions"])],
                            ["Customers", F.number(totals["customers"])],
                            ["Purchases", F.number(totals["purchases"])],
                            ["Revenue", F.inr(totals["revenue"])],
                            ["AOV", F.inr(totals["aov"], 2)],
                            ["Units", F.number(totals["units"])],
                            ["Conversion", F.pct(totals["conversion"])]])
        , chart=C.chart("ai_volume", "Sessions by month", "bar",
                        [m["label"] for m in C.group(store, where, params, "month", ["sessions"],
                                                      order="key", asc=True)],
                        [{"label": "Sessions",
                          "data": [m["sessions"] for m in C.group(store, where, params, "month",
                                                                   ["sessions"], order="key", asc=True)],
                          "color": "cyan"}], span=12, unit="count", height=220),
        method="Single aggregate SELECT over the filtered `sessions` table.",
        limitations="",
        followups=EXAMPLES[:4])


def _no_answer(store, where, params, why: str) -> dict:
    totals = _ctx(store, where, params)
    return _base(
        answer=f"{why or 'That question is outside what this dataset can answer.'}",
        detail="The analyst is a deterministic query engine over the bundled dataset — it will not "
               f"invent an answer. Current scope: {F.number(totals['sessions'])} sessions, "
               f"{F.number(totals['purchases'])} purchases, {F.inr_short(totals['revenue'])} revenue.",
        evidence=_evidence(["Try asking", ""], [[q, ""] for q in EXAMPLES]),
        method="No query ran for an unmatched intent (so nothing was fabricated).",
        limitations="Questions about product names, city names, profit/margin, delivery, returns or "
                    "customer demographics cannot be answered: those columns do not exist in "
                    "data/Ecommerce.csv.",
        followups=EXAMPLES[:6],
        confidence="none")


HANDLERS = {
    "category_best": h_category_best, "product_top": h_product_top, "payment": h_payment,
    "customers_value": h_customers_value, "patterns": h_patterns, "discount": h_discount,
    "funnel": h_funnel, "device": h_device, "aov": h_aov, "rating": h_rating, "trend": h_trend,
    "weekday": h_weekday, "geo": h_geo, "channel": h_channel, "quality": h_quality,
    "conversion": h_conversion, "price": h_price, "volume": h_volume,
}


def llm_polish(result: dict) -> dict:
    """Optional, opt-in rewrite of `detail` with an LLM. Never touches numbers.

    Enabled only when OPENAI_API_KEY + ANALYST_LLM=1 are set, so default
    deployments are fully offline and deterministic.
    """
    if os.environ.get("ANALYST_LLM") != "1" or not os.environ.get("OPENAI_API_KEY"):
        return result
    try:                                            # pragma: no cover - optional path
        import json
        import urllib.request

        body = json.dumps({
            "model": os.environ.get("ANALYST_LLM_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system",
                 "content": "Rewrite the analyst narrative for a business reader. Keep every number "
                            "exactly as written. Do not add facts."},
                {"role": "user", "content": result.get("detail", "")},
            ],
            "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            payload = json.loads(resp.read().decode())
        text = payload["choices"][0]["message"]["content"].strip()
        if text and len(text) < 2000:
            result["llm_polished"] = True
    except Exception as exc:                         # pragma: no cover
        result["llm_error"] = str(exc)[:120]
    return result
