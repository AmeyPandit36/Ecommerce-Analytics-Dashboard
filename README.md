# 🛍️ E-Commerce Customer Behavior & Purchase Analysis

A polished, **Power BI-style interactive analytics dashboard** built with **Flask + SQLite + Chart.js** on a real Kaggle dataset.

> Every KPI, chart, and table is powered by live SQL aggregation over the bundled dataset. No mocked numbers.

---

## ✨ Quick navigation

- [Why this project](#-why-this-project)
- [Run locally in 60 seconds](#-run-locally-in-60-seconds)
- [Dashboard pages](#-dashboard-pages)
- [Global slicers](#-global-slicers)
- [Dataset details](#-dataset-details)
- [Customer segmentation logic](#-customer-segmentation-logic)
- [Project structure](#-project-structure)
- [Deployment](#-deployment)
- [Environment variables](#-environment-variables)

---

## 🎯 Why this project

This repository focuses on **business insights**, not e-commerce transactions.
It answers questions like:

- What drives conversion?
- Which customer segments contribute most revenue?
- How do category, price, and discount behavior interact?
- Where do users abandon the funnel?

---

## ⚡ Run locally in 60 seconds

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open: **http://127.0.0.1:5050**

### Optional validation commands

```bash
python scripts/build_dataset.py
python scripts/smoke_test.py
npm i jsdom && node scripts/frontend_dom_test.mjs
```

`python3 --version` must be **>= 3.10**.

---

## 📊 Dashboard pages

| Route | Page |
|---|---|
| `/` | redirects to `/overview` |
| `/overview` (alias `/dashboard`) | **Executive overview** — top KPIs, funnel, snapshot visuals |
| `/customers` | **Customer behavior & value** — Pareto segmentation, revenue contribution, frequency |
| `/conversion` (alias `/journey`, `/funnel`) | **Conversion journey** — funnel by user type, session duration, discount impact |
| `/categories` (alias `/category-price`) | **Category & price performance** — revenue, conversion, price bands, payment mix |

### JSON APIs

| Endpoint | Purpose |
|---|---|
| `GET /api/summary` | `{ready, totals, status}` headline aggregates for active filters |
| `GET /api/export` | export current report state with filters, totals, and segments |
| `GET /healthz` | `{ok, rows, status, version}` |

---

## 🎛️ Global slicers

All slicers are backed by a single source of truth (`core/filters.py` specs), so UI, validation, and SQL stay aligned.

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
| `purch` | `purchased` | select |
| `seg` | customer segment | select |
| `dbucket` | discount bucket | select |
| `pband` | price band | select |
| `rmin` | `rating` | preset select |
| `dmin`, `dmax` | `discount_percent` | preset selects |

If filters return no rows, the UI shows a clear **“No rows match these filters”** message.

---

## 🗂️ Dataset details

| | |
|---|---|
| Bundled file | [`data/Ecommerce.csv`](data/Ecommerce.csv) — **25,000 rows × 29 columns** |
| Source | Kaggle: `kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase` (CC BY 4.0, synthetic) |
| Runtime dependency | none — Kaggle is **not** contacted at runtime |
| Refresh (dev only) | `python scripts/download_dataset.py` then `python scripts/build_dataset.py` |

<details>
<summary><strong>View full CSV schema (29 columns)</strong></summary>

```text
customer_id, session_id, visit_date, device_type, user_type, marketing_channel, product_id,
product_category, unit_price, quantity, discount_percent, discount_amount, revenue, pages_viewed,
time_on_site_sec, added_to_cart, purchased, cart_abandoned, rating, review_text,
review_helpful_votes, payment_method, visit_day, visit_month, visit_weekday, visit_season,
session_duration_bucket, revenue_normalized, location
```
</details>

<details>
<summary><strong>Verified facts from the bundled file</strong></summary>

- 0 nulls, 0 duplicate rows, CRLF line endings, `visit_date` is `DD-MM-YYYY` text.
- 25,000 unique sessions, 8,442 unique customers, 899 product IDs.
- `product_id` is not a stable SKU (appears across categories), so analysis is category/segment/price-band focused.
- `revenue = unit_price × quantity − discount_amount` only when `purchased = 1`; otherwise `0`.
- Non-purchase rows have placeholder `rating = 4`; rating metrics are limited to `purchased = 1`.
- Encoded fields (`device_type`, `user_type`, `marketing_channel`, `payment_method`, `product_category`, `location`, `review_text`) are shown as labels like `Category 2`, `Payment 3`.
</details>

### Headline metrics (unfiltered)

**25,000 sessions · 8,442 customers · 5,616 purchases · ₹10,116,169.06 revenue · ₹1,801 AOV · 22.46% conversion**

---

## 👥 Customer segmentation logic

Segments are calculated from lifetime revenue per customer:

- **High value** — top 20% of buyers (836 customers, 9.90% of all, 47.21% of revenue)
- **Mid value** — next 30% of buyers
- **Core value** — remaining 50% of buyers
- **Window shoppers** — never purchased (50.53% of customers)

---

## 🧱 Project structure

```text
app.py                  create_app(): routes, slicers, payloads, APIs
api/index.py            Vercel entrypoint (re-exports app)
data/loader.py          DB discovery + auto-build from CSV
data/Ecommerce.csv      source of truth
data/ecommerce.db       derived SQLite store (rebuildable)
core/store.py           read-only per-thread sqlite3 access
core/filters.py         slicer SPECS (UI + validation + SQL)
core/format.py          formatting helpers (₹, %, compact, date)
analytics/common.py     metrics + dimensions + chart/table specs
analytics/report.py     report pages: overview/customers/conversion/categories
templates/              base/page/macros/filters/icons/offline
public/static/          app.css, app.js, vendored Chart.js
scripts/                dataset build/download + smoke/frontend checks
```

---

## 🚀 Deployment

For Vercel deployment details, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

Quick deploy:

```bash
npx vercel --prod
```

---

## ⚙️ Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `5050` | local server port |
| `FLASK_DEBUG` | unset | set `1` for debug reload |
| `DATA_DIR` | `data/` | directory for `ecommerce.db` / `Ecommerce.csv` |
