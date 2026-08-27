"""Product-level analytics: rankings, ratings, concentration and the interactive table."""
from __future__ import annotations

from analytics import common as C
from core import format as F

# Whitelisted sort keys for the product table (never taken from user input raw).
SORTS = {
    "revenue": "revenue",
    "sessions": "sessions",
    "purchases": "purchases",
    "conversion": "conversion",
    "aov": "aov",
    "rating": "rating",
    "units": "units",
    "avg_price": "avg_price",
    "product_id": "product_id",
}

BASE_CTE = """
WITH p AS (
    SELECT product_id,
           MAX(product_category)                                   AS category,
           MAX(category_label)                                     AS category_label,
           COUNT(*)                                                AS sessions,
           COUNT(DISTINCT customer_id)                             AS customers,
           COALESCE(SUM(purchased), 0)                             AS purchases,
           COALESCE(SUM(quantity), 0)                              AS units,
           COALESCE(SUM(revenue), 0)                               AS revenue,
           SUM(revenue) * 1.0 / NULLIF(SUM(purchased), 0)          AS aov,
           AVG(unit_price)                                         AS avg_price,
           AVG(discount_percent)                                   AS avg_discount,
           AVG(CASE WHEN purchased = 1 THEN rating END)            AS rating,
           SUM(CASE WHEN purchased = 1 THEN review_helpful_votes ELSE 0 END) AS helpful,
           100.0 * SUM(purchased) / NULLIF(COUNT(*), 0)            AS conversion,
           100.0 * SUM(cart_abandoned) / NULLIF(SUM(added_to_cart), 0)       AS abandon_rate
    FROM sessions
    WHERE 1=1 {where}
    GROUP BY product_id
)
"""


def summary(store, where: str, params: tuple) -> dict:
    """Charts + headline numbers about the product catalogue."""
    top = store.rows(BASE_CTE.format(where=where) +
                     "SELECT * FROM p ORDER BY revenue DESC LIMIT 10", params)
    rated = store.rows(BASE_CTE.format(where=where) +
                       "SELECT * FROM p WHERE purchases >= 8 ORDER BY rating DESC, revenue DESC LIMIT 8",
                       params)
    concentration = store.row(
        "WITH r AS (SELECT product_id, SUM(revenue) rev FROM sessions WHERE purchased = 1 {w}"
        " GROUP BY product_id ORDER BY rev DESC) "
        "SELECT (SELECT COUNT(*) FROM r) AS ranked_products, "
        "       (SELECT COALESCE(SUM(rev),0) FROM r) AS total_revenue, "
        "       (SELECT COALESCE(SUM(rev),0) FROM (SELECT rev FROM r LIMIT 50)) AS top50_revenue, "
        "       (SELECT COALESCE(SUM(rev),0) FROM (SELECT rev FROM r LIMIT 100)) AS top100_revenue".format(
            w=where), params)

    charts = [
        C.chart("top_products", "Top products by revenue", "hbar",
                [f"Product #{r['product_id']} · {r['category_label']}" for r in top],
                [{"label": "Revenue", "data": [F.clean(r["revenue"]) for r in top], "color": "cyan"}],
                subtitle="Highest revenue products inside the current filters", span=6, unit="inr",
                height=320),
        C.chart("product_breadth", "Revenue concentration", "bar",
                ["Top 50", "Top 100", "All products"],
                [{"label": "Revenue", "data": [concentration.get("top50_revenue"),
                                               concentration.get("top100_revenue"),
                                               concentration.get("total_revenue")],
                  "color": "violet"}],
                subtitle=f"How much of revenue sits in a handful of the "
                         f"{F.number(concentration.get('ranked_products'))} purchased products",
                span=6, unit="inr", height=320),
    ]
    highlights = {
        "products": len(top),
        "ranked_products": concentration.get("ranked_products") or 0,
        "top50_share": (100.0 * concentration["top50_revenue"] / concentration["total_revenue"]
                        if concentration.get("total_revenue") else None),
        "best_rated": {
            "product_id": rated[0]["product_id"], "rating": rated[0]["rating"],
            "purchases": rated[0]["purchases"], "revenue": rated[0]["revenue"],
        } if rated else None,
    }
    return {"charts": charts, "highlights": highlights,
            "best_rated_rows": [{
                "label": f"Product #{r['product_id']}", "category": r["category_label"],
                "rating": F.number(r["rating"], 2, style="west"), "purchases": F.number(r["purchases"]),
                "revenue": F.inr_short(r["revenue"]),
            } for r in rated]}


def product_table(store, where: str, params: tuple, *, q: str = "", sort: str = "revenue",
                  direction: str = "desc", page: int = 1, per_page: int = 12) -> dict:
    """Server-side search / sort / paginate over the product aggregate."""
    sort_col = SORTS.get(sort, "revenue")
    direction = "ASC" if str(direction).lower() == "asc" else "DESC"
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = min(50, max(5, int(per_page)))
    except (TypeError, ValueError):
        per_page = 12

    search = ""
    search_params: list = []
    needle = (q or "").strip()
    if needle:
        digits = "".join(ch for ch in needle if ch.isdigit())
        terms = ["CAST(product_id AS TEXT) LIKE ?"]
        search_params.append(f"%{digits or needle}%")
        if not digits:
            terms.append("category_label LIKE ?")
            search_params.append(f"%{needle}%")
        search = "AND (" + " OR ".join(terms) + ")"

    cte = BASE_CTE.format(where=where)
    total = store.scalar(cte + f"SELECT COUNT(*) FROM p WHERE 1=1 {search}",
                         tuple(params) + tuple(search_params), 0)
    offset = (page - 1) * per_page
    rows = store.rows(cte + f"SELECT * FROM p WHERE 1=1 {search} "
                            f"ORDER BY {sort_col} {direction}, revenue DESC "
                            f"LIMIT {per_page} OFFSET {offset}",
                      tuple(params) + tuple(search_params))

    out = []
    for r in rows:
        out.append({
            "product_id": f"#{r['product_id']}",
            "category": r["category_label"],
            "sessions": F.number(r["sessions"]),
            "customers": F.number(r["customers"]),
            "purchases": F.number(r["purchases"]),
            "units": F.number(r["units"]),
            "conversion": F.pct(r["conversion"]),
            "revenue": F.inr_short(r["revenue"]),
            "aov": F.inr_short(r["aov"]),
            "avg_price": F.inr(r["avg_price"], 2),
            "avg_discount": F.pct(r["avg_discount"]),
            "rating": (F.number(r["rating"], 2, style="west") + " ★") if r["rating"] else "n/a",
            "helpful": F.number(r["helpful"]),
            "raw": {"product_id": r["product_id"], "revenue": F.clean(r["revenue"]),
                    "sessions": r["sessions"], "purchases": r["purchases"],
                    "conversion": F.clean(r["conversion"], 3), "rating": F.clean(r["rating"], 3)},
        })
    pages = max(1, -(-total // per_page))
    return {"columns": [
        {"key": "product_id", "label": "Product", "align": "left", "sortable": True, "field": "product_id"},
        {"key": "category", "label": "Category", "align": "left"},
        {"key": "sessions", "label": "Sessions", "align": "right", "sortable": True, "field": "sessions"},
        {"key": "purchases", "label": "Purchases", "align": "right", "sortable": True, "field": "purchases"},
        {"key": "units", "label": "Units", "align": "right"},
        {"key": "conversion", "label": "Conv.", "align": "right", "sortable": True, "field": "conversion"},
        {"key": "revenue", "label": "Revenue", "align": "right", "sortable": True, "field": "revenue"},
        {"key": "aov", "label": "AOV", "align": "right"},
        {"key": "avg_price", "label": "Avg price", "align": "right", "sortable": True, "field": "avg_price"},
        {"key": "avg_discount", "label": "Disc.", "align": "right"},
        {"key": "rating", "label": "Rating", "align": "right", "sortable": True, "field": "rating"},
    ], "rows": out, "total": total, "page": min(page, pages), "pages": pages, "per_page": per_page,
        "sort": sort_col, "direction": direction.lower(), "q": needle}
