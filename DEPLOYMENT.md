# Deployment guide

Target platform: **Vercel** (Serverless Function, Python 3.12 runtime). The app is a plain Flask
WSGI app, so the same code also runs unchanged on Render / Railway / Fly.io / any Docker host with
`gunicorn`.

---

## 1. Vercel (recommended)

### Prerequisites

```bash
git clone https://github.com/AmeyPandit36/Ecommerce-Analytics-Dashboard
cd Ecommerce-Analytics-Dashboard
npx vercel --login          # or: npm i -g vercel && vercel login
```

### Deploy

```bash
vercel                    # first run: link/create the project (accept the auto-detected "Other / Python")
vercel --prod
```

or from the Vercel dashboard: **Add New → Project → import the GitHub repo → Deploy**. No build
command, no output directory, no framework preset are required — leave the defaults.

### How the pieces fit

| Concern | How it is handled |
|---|---|
| Entrypoint | Vercel's zero-config Python runtime finds the module-level `app` in `app.py` (repo root). `api/index.py` re-exports the same object (`handler = app`) — one code path, no duplicated app factory |
| Build | none. Vercel ships the repo as-is and the Python runtime installs `requirements.txt` |
| Runtime deps | only `Flask`. Analytics run on stdlib `sqlite3`, so no pandas/numpy wheels are installed → small bundle, fast cold start |
| Data | `data/ecommerce.db` and `data/Ecommerce.csv` are **committed**, so the function reads them straight from `/var/task/data`. No KaggleHub call ever happens at runtime |
| Self-healing | if the DB is missing or unreadable, `data/loader.py` rebuilds it from the CSV into the first writable directory it finds, and the UI degrades to an offline page instead of a 500 |
| Static assets | Vercel serves `public/**` from its CDN; `Chart.js` is vendored at `public/static/vendor/chart.umd.min.js` — no CDN links anywhere |
| Function settings | `vercel.json`: `maxDuration: 30`, `excludeFiles` trims `.git`, caches, virtualenvs out of the bundle |
| Python version | `.python-version` pins 3.12 |

### Environment variables (all optional)

* `DATA_DIR` — alternate location for the SQLite store.
* `SECRET_KEY` — inert (no sessions/flashes); set it if you add auth.

---

## 2. Verify the live URL

Replace `https://YOUR-APP.vercel.app` below:

```bash
python scripts/smoke_test.py https://YOUR-APP.vercel.app
```

It must print `171 checks, 0 failures`. It validates:

1. `/overview`, `/customers`, `/conversion`, `/categories`, `/healthz`, `/api/summary`,
   `/api/export` all return 200 (no error pages).
2. `/static/app.css`, `/static/app.js` and the vendored Chart.js are served at the expected size.
3. every `<canvas data-chart>` has a matching spec in the embedded JSON payload, with non-empty
   labels/series and numeric data, and every `<use href="#i-…">` icon exists in the inlined sprite.
4. each slicer parameter changes the aggregates, and an impossible filter (`?cat=99`) yields an
   empty result rather than an error.
5. headline KPIs (sessions, purchases, revenue, customers) equal a **recomputation from the raw
   CSV** done independently in the test — for the unfiltered view and six filter combinations.
6. the verified headline figures are reproduced exactly: 25,000 sessions, 8,442 customers,
   22.46 % conversion, ₹1,801 AOV, 65.15 % abandonment, ₹10.12M revenue.

Then a 60-second manual pass in the browser:

- [ ] Overview shows ₹10.12M revenue, 25,000 sessions, 8,442 customers, 22.46 % conversion,
      ₹1,801 AOV, 65.15 % abandonment on a light background with charcoal text and a blue accent.
- [ ] Charts animate in, tooltips show ₹/% values, and the funnel shows 25,000 → 16,117 → 5,616.
- [ ] Change **Category** → every KPI, chart, callout and chip updates; **Reset Filters** returns
      to the full range.
- [ ] Customers shows the four Pareto segments; Conversion shows discount analysis; Category & Price
      shows the data-quality note about `product_id`.
- [ ] Browser console is clean (no 404s, no CORS, no Chart.js warnings).

---

## 3. If the deployment fails

| Symptom | Cause and fix |
|---|---|
| `Error: No Python entrypoint found` / `404: NOT_FOUND` | the repo root must contain `app.py` with a module-level `app` (it does). Keep `api/index.py` importing it |
| `ModuleNotFoundError: No module named 'core'` / `'analytics'` | the entrypoint was resolved from a subdirectory. Use `api/index.py` (it prepends the repo root to `sys.path`) |
| `500` with "Analytics store missing", or `/healthz` → `{"ok": false}` | `data/ecommerce.db` did not reach the function: `git ls-files data/` must list both data files |
| `413`/bundle-size error | trim more with `functions."app.py".excludeFiles`. Do **not** exclude `data/`, `core/`, `analytics/`, `public/`, `templates/` |
| `INIT_REPORT_INVALID: handler not found` | the entry module must export `app` (WSGI callable) |
| Function times out | raise `maxDuration` in `vercel.json` (30 s is generous: pages compute in tens of milliseconds) |
| CSS/JS 404 in production | assets must live at `public/static/**` and templates must reference `/static/...` via `url_for('static', …)` |
| Blank charts only in production | Chart.js is vendored — a 404 for `/static/vendor/chart.umd.min.js` means `public/` was excluded |

---

## 4. Any other host (Docker / Render / Railway)

```bash
pip install -r requirements.txt -r requirements-dev.txt
gunicorn "app:create_app()" --bind 0.0.0.0:${PORT:-5050} --workers 2 --timeout 60
```

`create_app()` is the app factory; `app` is also importable as a module attribute
(`gunicorn app:app` works too). Nothing else is needed — no database service, no env vars,
no network access: the dataset travels with the code.
