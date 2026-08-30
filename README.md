# Ecommerce Analytics Dashboard

A production-shaped analytics dashboard over a **real** Kaggle dataset: Flask + SQLite
(stdlib `sqlite3`) + Chart.js, with a transparent rule-based AI analyst that only answers
from aggregates it can actually compute.

Every number on screen is a live SQL aggregate over the bundled dataset — nothing is mocked,
hardcoded, or estimated. When a question cannot be answered from the data, the app says so.

---

## Dataset

| | |
|---|---|
| Bundled file | [`data/Ecommerce.csv`](data/Ecommerce.csv) — 2,500,899 bytes, **25,000 rows × 29 columns** |
| sha256 | `5cfee9033b4cc4144e2bf5df64e0916657f47232…` (recorded in the derived DB, shown in the sidebar) |
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
normalised to `yyyy-mm-dd`, plus label columns (`category_label`, `device_label`, …) and a
per-column quality profile table. 25,000 × 40 rows, indexed, ~8 MB. It is committed so that
read-only serverless filesystems (Vercel) never have to build it; if it is missing,
`data/loader.py` rebuilds it automatically on first request.

### Verified facts about the real file (the Kaggle description is wrong in places)

* 0 nulls, 0 duplicate rows, CRLF line endings, `visit_date` is **`DD-MM-YYYY` text**.
* 25,000 unique `session_id`s, 8,442 unique customers, 899 products.
* `revenue = unit_price × quantity − discount_amount` **only when `purchased = 1`**, otherwise `0`.
* `discount_amount = round(unit_price × quantity × discount_percent / 100, 2)`.
* `unit_price` 50.05–1999.83 · `quantity` 1–4 · `discount_percent` 0–30.
* `rating` is `4` on **every** non-purchase row (a placeholder). Every rating metric in this app is
  therefore restricted to `purchased = 1`.
* `device_type`, `user_type`, `marketing_channel`, `payment_method`, `product_category`, `location`
  and `review_text` are label-encoded and **not** documented by the dataset. They are shown as
  `Category 2`, `Payment 3`, … — the app never invents friendly names for them.
* Decodable, and proven from the data itself: `visit_weekday` (0 = Mon … 6 = Sun),
  `visit_season` (0 = Sep–Nov, 1 = Mar–May, 2 = Jun–Aug, 3 = Dec–Feb),
  `session_duration_bucket` (quartiles of `time_on_site_sec`), `revenue_normalized = revenue / 7889.36`.

### Headline numbers (unfiltered, as computed by the running app)

25,000 sessions · 8,442 customers · 5,616 purchases · ₹10,116,169.06 revenue · ₹1,801.31 AOV ·
22.46 % conversion · 62,226 units · 9.0 % average discount · 3.77 ★ average post-purchase rating ·
16,117 carts added, 10,501 abandoned (65.2 %) · 2024-01-01 → 2024-12-30.

---

## Pages

| Route | What it does |
|---|---|
| `/` | redirects to `/dashboard` |
| `/dashboard` | Overview — 8 KPI cards, 6 auto-generated insight cards, revenue/traffic trend, category performance, payment mix, discount-vs-conversion, plus the top-of-page JSON report |
| `/sales` | Sales & Products — category table (sessions, purchases, conversion, revenue, AOV, rating, units, share), price bands, discounts, payment methods, seasonality, and the **interactive product table** (search, sort, pagination, rows-per-page) |
| `/customers` | Customers — High / Medium / Low value segmentation with the exact thresholds and rule shown, repeat-purchase mix, per-segment behaviour, geography of revenue and spend |
| `/journey` (alias `/funnel`) | Sessions → add-to-cart → purchase, with drop-off counts, plus device/user-type/channel behaviour charts |
| `/data-quality` | rows, columns, missing cells, duplicate rows, dtypes, distinct counts, IQR outliers, per-column profile (29 rows), semantic checks, provenance |
| `/ai-analyst` | Ask-the-data box with example questions; each answer ships with the SQL used, the evidence table/chart and its limitations |

### JSON APIs (same filters)

| Endpoint | Purpose |
|---|---|
| `GET /api/summary` | `{ready, totals, status}` — 29 aggregate metrics for the current filter range |
| `GET /api/products?q&sort&dir&page&per` | product aggregation for the interactive table |
| `POST /api/ask` (`?q=` also works) | analyst answer: `answer, detail, evidence, chart, method, limitations, confidence, followups` |
| `GET /api/export` | JSON report of the current view: source provenance (file, sha256, built_at), active filters, totals, auto-insights, customer segments and the quality profile |
| `GET /healthz` | `{ok, rows, status, version}` |

---

## Global filters

Built only from columns that exist in the dataset; the same `SPECS` drive the UI, the SQL builder
and the chip bar, so they cannot drift apart. Every page, chart, table, KPI and API respects them.

| Param | Column | Control |
|---|---|---|
| `from`, `to` | `visit_date` (accepts `yyyy-mm-dd` or the file's `dd-mm-yyyy`) | date |
| `month` | `visit_month` | select |
| `cat` | `product_category` | select |
| `pay` | `payment_method` | select |
| `dev` | `device_type` | select |
| `utype` | `user_type` | select |
| `chan` | `marketing_channel` | select |
| `loc` | `location` | select |
| `bucket` | `session_duration_bucket` | select |
| `purch` | `purchased` | select (outcome) |
| `rmin` | `rating` | preset select (★) |
| `dmin`, `dmax` | `discount_percent` | preset selects |

Bad or non-numeric values are ignored rather than injected, unknown keys are dropped, and
`/api/products` whitelists its `sort` column. A filter combination that matches nothing renders a
single clear "No rows match these filters" note instead of a page of zeros or a stack trace.

---

## AI analyst

`analytics/ai_analyst.py` holds 18 intents. A question is matched with inverse-document-frequency
weighted term scoring (strong terms ×2.6, weak ×0.6, accept ≥ 1.0); each handler then runs real
SQL through the same filter state as the page.

* **Never fabricates.** Unmatched questions get an explicit refusal plus the list of what it can do.
* **Shows its work.** Each answer carries the SQL/method, the evidence table, an optional chart,
  and a "limitations" note (e.g. encoded category labels, the rating placeholder).
* **Correlation ≠ causation** is stated where the data only supports association.
* Optional LLM polish is **off by default**; set `ANALYST_LLM=1` and `OPENAI_API_KEY` to have a model
  rephrase the narrative — numbers, tables and charts are always the app's own.

---

## Run locally

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # Flask only; analytics use stdlib sqlite3
python app.py                            # → http://127.0.0.1:5050
```

`python3 --version` must be ≥ 3.10 (uses `X | None` typing). The DB builds itself from
`data/Ecommerce.csv` on first run, so a fresh clone works with no extra steps.

```bash
pip install -r requirements-dev.txt      # pandas / kagglehub / gunicorn, dev only
python scripts/build_dataset.py          # rebuild data/ecommerce.db from the CSV
python scripts/smoke_test.py             # 231 checks: routes, charts, filters, CSV cross-check
npm i jsdom && node scripts/frontend_dom_test.mjs   # (optional) headless DOM/JS checks
```

`scripts/smoke_test.py` re-derives sessions, purchases and revenue straight from the CSV with the
stdlib `csv` module and compares them against `/api/summary`, so the dashboard is verified against
the raw data rather than against itself.

## Deploying

See **[DEPLOYMENT.md](DEPLOYMENT.md)** (Vercel). Short version:

```bash
npx vercel --prod        # zero-config Python; app.py exposes module-level `app`
```

## Project layout

```
app.py                  create_app(): routes, filter state, page payload, APIs
api/index.py            Vercel entrypoint (re-exports the same `app`)
data/loader.py          finds the DB, builds it from the CSV if absent
data/Ecommerce.csv       the source of truth (committed)
data/ecommerce.db        derived SQLite store (committed; regenerable)
core/store.py            read-only, per-thread sqlite3 connection + memoisation
core/filters.py          SPECS: one definition for filter UI, validation and SQL
core/format.py           ₹ / % / compact / date formatting (Indian digit groupings)
analytics/common.py      METRICS + DIMENSIONS, group/overall/totals, chart & table specs
analytics/{sales,products,customers,geography,funnel,quality,insights,ai_analyst}.py
templates/               base, page (section renderer), analyst, offline, _macros, _filters, _icons
public/static/           app.css, app.js, vendor/chart.umd.min.js (vendored, no CDN)
scripts/                 download_dataset, build_dataset, smoke_test
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5050` | local dev server port |
| `FLASK_DEBUG` | unset | set to `1` for debug reloader + raw analyst errors |
| `DATA_DIR` | `data/` | where to look for `ecommerce.db` / `Ecommerce.csv` |
| `ANALYST_LLM` | unset | `1` enables LLM rephrasing of analyst prose |
| `ANALYST_LLM_MODEL` | `gpt-4o-mini` | model used for that polish |
| `OPENAI_API_KEY` | unset | required by the polish path (never required otherwise) |
