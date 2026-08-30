# E-Commerce Customer Behavior & Purchase Analysis

A professional, **Power BI-style interactive analytics report** over a real Kaggle dataset
(Flask + SQLite stdlib + Chart.js). It presents the *data analysis* — not a software product:
customer behavior, conversion, revenue concentration, category performance and purchase patterns.

Every number on screen is a live SQL aggregate over the bundled dataset — nothing is mocked,
hardcoded, or estimated. SKU-level analysis is deliberately excluded because `product_id` does not
behave as a stable product identifier in the source data.

---

## Dataset

| | |
|---|---|
| Bundled file | [`data/Ecommerce.csv`](data/Ecommerce.csv) — 2,500,899 bytes, **25,000 rows × 29 columns** |
| Source | Kaggle `kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase`, CC BY 4.0, synthetic |
| Runtime dependency | **none** — the app reads the committed CSV/SQLite file. Kaggle is *not* contacted at runtime |
| Refresh (dev only) | `python scripts/download_dataset.py` (uses `kagglehub`), then `python scripts/build_dataset.py` |

The 29 columns, in file order:

```
customer_id, session_id, visit_date, device_type, user_type, marketing_channel, product_id,
product_category, unit_price, quantity, discount_percent, discount_amount, revenue, pages_viewed,
time_on_site_sec, added_to_cart, purchased, cart_abandoned, rating, review_text,
review_helpful_votes, payment_method, visit_day, visit_month, visit_weekday, visit_season,
session_duration_bucket, revenue_normalized, location
```

`data/ecommerce.db` is a **derived** artifact: the CSV parsed once into SQLite with `visit_date`
normalised to `yyyy-mm-dd`, plus label columns (`category_label`, `device_label`, …). It is
committed so read-only serverless filesystems (Vercel) never have to build it; if missing,
`data/loader.py` rebuilds it automatically on first request.

### Verified facts about the real file (the Kaggle description is wrong in places)

* 0 nulls, 0 duplicate rows, CRLF line endings, `visit_date` is **`DD-MM-YYYY` text**.
* 25,000 unique `session_id`s, 8,442 unique customers, 899 products.
* **`product_id` is not a stable SKU**: all 899 ids appear across all 8 categories. This is why the
  report works at the category / segment / price-band level and never at SKU level.
* `revenue = unit_price × quantity − discount_amount` **only when `purchased = 1`**, otherwise `0`.
* `rating` is `4` on **every** non-purchase row (a placeholder); all rating metrics are restricted
  to `purchased = 1`.
* `device_type`, `user_type`, `marketing_channel`, `payment_method`, `product_category`, `location`
  and `review_text` are label-encoded and **not** documented by the dataset. They are shown as
  `Category 2`, `Payment 3`, … — the report never invents friendly names for them.

### Headline numbers (unfiltered, as computed by the running app)

25,000 sessions · 8,442 customers · 5,616 purchases · ₹10,116,169.06 revenue · ₹1,801 AOV ·
22.46 % conversion · 16,117 carts added, 10,501 abandoned (65.15 %) · 50.53 % of customers never
purchased · high-value segment = 836 customers (9.90 %) contributing 47.21 % of revenue ·
27.75 % repeat purchase rate.

---

## Report pages

| Route | Page |
|---|---|
| `/` | redirects to `/overview` |
| `/overview` (alias `/dashboard`) | **Executive overview** — 6 headline KPIs, business-at-a-glance visuals, purchase funnel, key findings |
| `/customers` | **Customer behavior & value** — Pareto segmentation, revenue contribution, purchase frequency, user-type comparison |
| `/conversion` (alias `/journey`, `/funnel`) | **Conversion & purchase behavior** — funnel, funnel by user type, session duration, discount analysis |
| `/categories` (alias `/category-price`) | **Category & price performance** — revenue vs conversion by category, price bands, payment mix, data-quality note |

### JSON APIs (same slicers)

| Endpoint | Purpose |
|---|---|
| `GET /api/summary` | `{ready, totals, status}` — headline aggregates for the current filter range |
| `GET /api/export` | JSON report of the current view: source provenance, active filters, totals and segments |
| `GET /healthz` | `{ok, rows, status, version}` |

---

## Slicers (global filters)

Built only from columns that exist in the dataset; the same `SPECS` drive the UI, the SQL builder
and the chip bar, so they cannot drift apart. Every page, chart, table, KPI and API respects them.

| Param | Column | Control |
|---|---|---|
| `from`, `to` | `visit_date` | date |
| `month` | `visit_month` | select |
| `cat` | `product_category` | select |
| `pay` | `payment_method` | select |
| `dev` | `device_type` | select |
| `utype` | `user_type` | select |
| `chan` | `marketing_channel` | select |
| `loc` | `location` | select |
| `bucket` | `session_duration_bucket` | select |
| `purch` | `purchased` | select (outcome) |
| `seg` | customer segment | select (High / Mid / Core / Window) |
| `dbucket` | discount bucket | select (0% · 5–10% · 11–20% · 21–30%) |
| `pband` | price band | select (≤ ₹500 … ₹1,501–2,000) |
| `rmin` | `rating` | preset select |
| `dmin`, `dmax` | `discount_percent` | preset selects |

The `seg`, `dbucket` and `pband` slicers are derived columns (customer value segment,
discount depth, unit-price band) built from fixed SQL expressions — never from user input.

A filter combination that matches nothing renders a single clear "No rows match these filters" note
instead of a page of zeros or a stack trace. **Reset Filters** clears everything.

---

## Customer segmentation (Pareto rule)

Segments are computed transparently from lifetime revenue per customer — not from a fixed quota:

* **High value** — top 20% of buyers (836 customers, 9.90% of all, 47.21% of revenue)
* **Mid value** — next 30% of buyers
* **Core value** — remaining 50% of buyers
* **Window shoppers** — never purchased (50.53% of customers)

The rule reproduces the verified headline: *"High-value customers represent 9.90% of customers and
47.21% of revenue."*

---

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # Flask only; analytics use stdlib sqlite3
python app.py                            # → http://127.0.0.1:5050
```

`python3 --version` must be ≥ 3.10. The DB builds itself from `data/Ecommerce.csv` on first run.

```bash
python scripts/build_dataset.py          # rebuild data/ecommerce.db from the CSV
python scripts/smoke_test.py             # 171 checks: routes, charts, slicers, CSV cross-check
npm i jsdom && node scripts/frontend_dom_test.mjs   # (optional) headless DOM/JS checks
```

`scripts/smoke_test.py` re-derives sessions, purchases, revenue and customers straight from the CSV
with the stdlib `csv` module and compares them against `/api/summary`, so the report is verified
against the raw data rather than against itself.

## Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)** (Vercel). Short version:

```bash
npx vercel --prod        # zero-config Python; app.py exposes module-level `app`
```

## Project layout

```
app.py                  create_app(): routes, slicer state, page payload, APIs
api/index.py            Vercel entrypoint (re-exports the same `app`)
data/loader.py          finds the DB, builds it from the CSV if absent
data/Ecommerce.csv      the source of truth (committed)
data/ecommerce.db       derived SQLite store (committed; regenerable)
core/store.py           read-only, per-thread sqlite3 connection + memoisation
core/filters.py         SPECS: one definition for slicer UI, validation and SQL
core/format.py          ₹ / % / compact / date formatting (Indian digit groupings)
analytics/common.py     METRICS + DIMENSIONS, group/overall/totals, chart & table specs
analytics/report.py     the four report pages: overview, customers, conversion, categories
templates/              base, page (section renderer), offline, _macros, _filters, _icons
public/static/          app.css, app.js, vendor/chart.umd.min.js (vendored, no CDN)
scripts/                download_dataset, build_dataset, smoke_test, frontend_dom_test
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5050` | local dev server port |
| `FLASK_DEBUG` | unset | set to `1` for debug reloader |
| `DATA_DIR` | `data/` | where to look for `ecommerce.db` / `Ecommerce.csv` |
