#!/usr/bin/env python3
"""End-to-end verification for the BI report.

    python scripts/smoke_test.py                  # against the in-process app
    python scripts/smoke_test.py http://127.0.0.1:5050   # against a running server

Checks, in order:
  1. every report page returns 200 and renders
  2. static assets resolve (CSS / JS / Chart.js)
  3. the embedded chart payload is valid JSON and every canvas has a spec
  4. slicer parameters actually change the numbers
  5. headline KPIs recomputed straight from data/Ecommerce.csv match the API
  6. the verified headline figures from the analysis are reproduced exactly
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

PAGES = ["/", "/overview", "/customers", "/conversion", "/categories",
         "/healthz", "/api/summary", "/api/export",
         "/static/app.css", "/static/app.js", "/static/vendor/chart.umd.min.js"]
REPORT_PAGES = ["/overview", "/customers", "/conversion", "/categories"]
QUERIES = ["?cat=2", "?pay=1", "?dev=0", "?utype=1", "?chan=4", "?loc=46", "?bucket=Long",
           "?purch=1", "?purch=0", "?month=11", "?rmin=4", "?dmin=15", "?dmax=0",
           "?from=2024-03-01", "?to=15-06-2024", "?cat=2&pay=1&month=6", "?cat=99",
           "?loc=not-a-real-value", "?month=0"]


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


def csv_totals(query: str) -> dict:
    """Recompute headline metrics from the raw CSV, independently of the app."""
    args = urllib.parse.parse_qs(urllib.parse.urlparse(query).query)
    wanted = {key: values[0] for key, values in args.items() if values}

    def iso_bound(raw: str) -> str:
        day, month, year = (raw.split("-") + ["", "", ""])[:3]
        if len(day) == 4:
            return raw
        return f"{year}-{int(month):02d}-{int(day):02d}"

    sessions = revenue = purchases = 0
    customers = set()
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
            customers.add(row["customer_id"])
            purchased = int(row["purchased"])
            purchases += purchased
            revenue += float(row["revenue"])
    return {"sessions": sessions, "purchases": purchases, "revenue": round(revenue, 2),
            "customers": len(customers)}


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
        if path in REPORT_PAGES:
            check(f"render {path}", "Customer Behavior" in text or "Analysis" in text,
                  "missing app shell")
            check(f"no traceback in {path}", "Traceback" not in text and "hit an error" not in text)

    print("2/6 static asset sizes")
    for path, minimum in (("/static/app.css", 4000), ("/static/app.js", 8000),
                          ("/static/vendor/chart.umd.min.js", 100000)):
        status, body = client.get(path)
        check(f"{path} size", status == 200 and len(body) >= minimum, f"→ {len(body)} bytes")

    print("3/6 chart payloads")
    charts_total = 0
    for path in REPORT_PAGES:
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

    print("4/6 slicers change the numbers")
    baseline = json.loads(client.get("/api/summary")[1].decode())
    for query in QUERIES:
        status, body = client.get("/api/summary" + query)
        check(f"GET /api/summary{query}", status == 200, f"→ HTTP {status}")
        data = json.loads(body.decode())
        check(f"filtered{query} differs from baseline",
              data.get("totals") != baseline.get("totals")
              or query in ("?cat=99", "?loc=not-a-real-value", "?month=0"),
              "identical totals → filter ignored")
        if query == "?cat=2":
            check("cat=2 revenue < total revenue",
                  (data.get("totals") or {}).get("revenue", 0) < (baseline.get("totals") or {}).get("revenue", 0))
            check("cat=99 is empty",
                  json.loads(client.get("/api/summary?cat=99")[1].decode())["totals"]["sessions"] == 0)

    print("5/6 KPIs match a recomputation from the raw CSV")
    for query in ["", "?cat=2", "?pay=1", "?purch=0", "?month=11", "?bucket=Long",
                  "?from=2024-03-01&to=31-03-2024"]:
        status, body = client.get("/api/summary" + query)
        got = json.loads(body.decode())["totals"]
        expected = csv_totals(query)
        check(f"sessions{query or ' (all)'}", got["sessions"] == expected["sessions"],
              f"{got['sessions']} vs {expected['sessions']}")
        check(f"purchases{query or ' (all)'}", got["purchases"] == expected["purchases"],
              f"{got['purchases']} vs {expected['purchases']}")
        check(f"revenue{query or ' (all)'}", abs(got["revenue"] - expected["revenue"]) < 1,
              f"₹{got['revenue']:,.2f} vs ₹{expected['revenue']:,.2f}")
        check(f"customers{query or ' (all)'}", got["customers"] == expected["customers"],
              f"{got['customers']} vs {expected['customers']}")

    print("6/6 verified headline figures from the analysis")
    totals = baseline["totals"]
    check("sessions = 25,000", totals["sessions"] == 25000, f"{totals['sessions']}")
    check("customers = 8,442", totals["customers"] == 8442, f"{totals['customers']}")
    check("conversion ≈ 22.46%", abs(totals["conversion"] - 22.464) < 0.01, f"{totals['conversion']}")
    check("AOV ≈ ₹1,801", abs(totals["aov"] - 1801.31) < 1, f"{totals['aov']}")
    check("abandonment ≈ 65.15%", abs(totals["abandon_rate"] - 65.1548) < 0.01,
          f"{totals['abandon_rate']}")
    check("revenue ≈ ₹10.12M", abs(totals["revenue"] - 10116169.06) < 1, f"{totals['revenue']}")

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
