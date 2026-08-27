#!/usr/bin/env python3
"""End-to-end verification for the dashboard.

    python scripts/smoke_test.py                  # against the in-process app
    python scripts/smoke_test.py http://127.0.0.1:5050   # against a running server

Checks, in order:
  1. every route returns 200 and renders
  2. static assets resolve (CSS / JS / Chart.js)
  3. the embedded chart payload is valid JSON and every canvas has a spec
  4. filter parameters actually change the numbers
  5. headline KPIs recomputed straight from data/Ecommerce.csv match the API
     (i.e. the dashboard is compared against the raw dataset, not against itself)
  6. the AI analyst answers every example question without errors
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "data", "Ecommerce.csv")

PAGES = ["/", "/dashboard", "/sales", "/customers", "/journey", "/funnel", "/data-quality",
         "/ai-analyst", "/healthz", "/api/summary", "/api/export", "/api/products",
         "/static/app.css", "/static/app.js", "/static/vendor/chart.umd.min.js"]
FILTERED = ["/dashboard", "/sales", "/customers", "/journey", "/api/summary", "/api/products"]
QUERIES = ["?cat=2", "?pay=1", "?dev=0", "?utype=1", "?chan=4", "?loc=46", "?bucket=Long",
           "?purch=1", "?purch=0", "?month=11", "?rmin=4", "?dmin=15", "?dmax=0",
           "?from=2024-03-01", "?to=15-06-2024", "?cat=2&pay=1&month=6", "?cat=99",
           "?loc=not-a-real-value", "?month=0"]
ANALYST_QUESTIONS = [
    "Which category performs best?", "What are the top 5 products?",
    "Which payment method is most popular?", "Which customers are most valuable?",
    "What interesting patterns exist in the dataset?", "Is discount associated with purchasing?",
    "Where do sessions drop off in the funnel?", "Which device converts best?",
    "What is the average order value?", "How do ratings vary by category?",
    "Which month was the strongest?", "Is there a weekend effect?",
    "Which locations spend the most?", "What does the data quality look like?",
    "who is the CEO", "",
]


class Client:
    """Thin wrapper so the same test runs in-process or over HTTP."""

    def __init__(self, base_url: str | None):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.app = None
        if not self.base_url:
            sys.path.insert(0, BASE_DIR)
            import app as module
            self.app = module.app.test_client()

    def get(self, path: str):
        if self.app is not None:
            response = self.app.get(path)
            return response.status_code, response.get_data()
        with urllib.request.urlopen(self.base_url + path, timeout=30) as resp:
            return resp.status, resp.read()

    def post_json(self, path: str, payload: dict):
        if self.app is not None:
            response = self.app.post(path, json=payload)
            return response.status_code, response.get_json()
        request = urllib.request.Request(
            self.base_url + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())


def csv_totals(query: str) -> dict:
    """Recompute headline metrics from the raw CSV, independently of the app."""
    args = urllib.parse.parse_qs(urllib.parse.urlparse(query).query)
    wanted = {key: values[0] for key, values in args.items() if values}

    def iso_bound(raw: str) -> str:
        day, month, year = (raw.split("-") + ["", "", ""])[:3]
        if len(day) == 4:                       # already yyyy-mm-dd
            return raw
        return f"{year}-{int(month):02d}-{int(day):02d}"
    sessions = revenue = purchases = 0
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if "cat" in wanted and row["product_category"] != wanted["cat"]:
                continue
            if "pay" in wanted and row["payment_method"] != wanted["pay"]:
                continue
            if "month" in wanted and row["visit_month"] != wanted["month"]:
                continue
            if "purch" in wanted and row["purchased"] != wanted["purch"]:
                continue
            if "bucket" in wanted and row["session_duration_bucket"] != wanted["bucket"]:
                continue
            if "dev" in wanted and row["device_type"] != wanted["dev"]:
                continue
            if "utype" in wanted and row["user_type"] != wanted["utype"]:
                continue
            if "chan" in wanted and row["marketing_channel"] != wanted["chan"]:
                continue
            if "loc" in wanted and row["location"] != wanted["loc"]:
                continue
            if "rmin" in wanted and float(row["rating"]) < float(wanted["rmin"]):
                continue
            if "dmin" in wanted and float(row["discount_percent"]) < float(wanted["dmin"]):
                continue
            if "dmax" in wanted and float(row["discount_percent"]) > float(wanted["dmax"]):
                continue
            if "from" in wanted or "to" in wanted:
                day, month, year = row["visit_date"].split("-")
                iso = f"{year}-{int(month):02d}-{int(day):02d}"
                if "from" in wanted and iso < iso_bound(wanted["from"]):
                    continue
                if "to" in wanted and iso > iso_bound(wanted["to"]):
                    continue
            sessions += 1
            purchased = int(row["purchased"])
            purchases += purchased
            revenue += float(row["revenue"])
    return {"sessions": sessions, "purchases": purchases, "revenue": round(revenue, 2)}


def main(base_url: str | None = None) -> int:
    client = Client(base_url)
    failures: list[str] = []
    checks = 0

    def check(label: str, condition: bool, detail: str = ""):
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(f"{label} {detail}".strip())
            print(f"  ✗ {label} {detail}")

    print(f"1/6 routes ({len(PAGES)})")
    for path in PAGES:
        status, body = client.get(path)
        check(f"GET {path}", status in (200, 302), f"→ HTTP {status}")
        text = body.decode("utf-8", "replace")
        if "text/html" in str(body[:200]) or path in ("/dashboard", "/sales", "/customers", "/journey",
                                                       "/data-quality", "/ai-analyst"):
            check(f"render {path}", "Ecommerce" in text or "Analytics" in text, "missing app shell")
            check(f"no traceback in {path}", "Traceback" not in text and "hit an error" not in text)

    print("2/6 static asset sizes")
    for path, minimum in (("/static/app.css", 4000), ("/static/app.js", 8000),
                          ("/static/vendor/chart.umd.min.js", 100000)):
        status, body = client.get(path)
        check(f"{path} size", status == 200 and len(body) >= minimum, f"→ {len(body)} bytes")

    print("3/6 chart payloads")
    charts_total = 0
    for path in ["/dashboard", "/sales", "/customers", "/journey", "/data-quality"]:
        status, body = client.get(path)
        text = body.decode("utf-8", "replace")
        match = re.search(r'<script id="page-data" type="application/json">(.*?)</script>', text, re.S)
        check(f"{path} payload present", bool(match))
        if not match:
            continue
        payload = json.loads(match.group(1))
        canvas_ids = set(re.findall(r'data-chart="([^"]+)"', text))
        check(f"{path} charts declared", canvas_ids <= set(payload.get("charts", {})),
              f"orphan canvases: {sorted(canvas_ids - set(payload.get('charts', {})))[:3]}")
        for chart_id, spec in payload.get("charts", {}).items():
            charts_total += 1
            if chart_id not in canvas_ids:
                continue
            check(f"{path}/{chart_id} has labels", bool(spec.get("labels")), "empty labels")
            check(f"{path}/{chart_id} has series", bool(spec.get("series")), "empty series")
            check(f"{path}/{chart_id} finite data",
                  all(v is None or isinstance(v, (int, float))
                      for s in spec.get("series", []) for v in s.get("data", [])), "non-numeric data")
        check(f"{path} icon refs resolve",
              all(f'id="i-{name}"' in text for name in
                  set(re.findall(r'<use href="#i-([a-z0-9-]+)"', text))))

    print("4/6 filters change the numbers")
    baseline = client.get("/api/summary")[1]
    base_totals = json.loads(baseline.decode()) if isinstance(baseline, bytes) else baseline
    for query in QUERIES:
        status, body = client.get("/api/summary" + query)
        check(f"GET /api/summary{query}", status == 200, f"→ HTTP {status}")
        data = json.loads(body.decode())
        check(f"filtered{query} differs from baseline",
              data.get("totals") != base_totals.get("totals") or query in ("?cat=99", "?loc=not-a-real-value", "?month=0"),
              "identical totals → filter ignored")
        if query == "?cat=2":
            check("cat=2 revenue < total revenue",
                  (data.get("totals") or {}).get("revenue", 0) < (base_totals.get("totals") or {}).get("revenue", 0))
            check("cat=99 is empty",
                  json.loads(client.get("/api/summary?cat=99")[1].decode())["totals"]["sessions"] == 0)

    print("5/6 KPIs match a recomputation from the raw CSV")
    for query in ["", "?cat=2", "?pay=1", "?purch=0", "?month=11", "?bucket=Long", "?from=2024-03-01&to=31-03-2024"]:
        status, body = client.get("/api/summary" + query)
        got = json.loads(body.decode())["totals"]
        expected = csv_totals(query)
        check(f"sessions{query or ' (all)'}", got["sessions"] == expected["sessions"],
              f"{got['sessions']} vs {expected['sessions']}")
        check(f"purchases{query or ' (all)'}", got["purchases"] == expected["purchases"],
              f"{got['purchases']} vs {expected['purchases']}")
        check(f"revenue{query or ' (all)'}", abs(got["revenue"] - expected["revenue"]) < 1,
              f"₹{got['revenue']:,.2f} vs ₹{expected['revenue']:,.2f}")

    print("6/6 analyst")
    for question in ANALYST_QUESTIONS:
        status, data = client.post_json("/api/ask?cat=2", {"question": question})
        check(f"ask {question[:34]!r}", status == 200 and bool(data.get("answer")),
              f"→ HTTP {status}")
        joined = json.dumps(data)
        check(f"ask {question[:24]!r} no leak", "Traceback" not in joined and "NoneType" not in joined)

    print()
    print(f"{checks} checks, {len(failures)} failures")
    if failures:
        print("FAILED:")
        for item in failures[:25]:
            print("  -", item)
        return 1
    print("ALL GOOD ✓")
    print(f"  charts validated: {charts_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
