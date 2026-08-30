# Deployment guide

Target platform: **Vercel** (Serverless Function, Python 3.12 runtime). The app is a plain Flask
WSGI app, so the same code also runs unchanged on Render / Railway / Fly.io / any Docker host with
`gunicorn`.

## Live status

| | |
|---|---|
| Deployed | **No** — as of 2026-08-30 there is no Vercel/Render/Fly/GitHub-Pages deployment for this repo (`gh api .../deployments` → `[]`, no environments, no Pages site, no workflows) |
| Repo | https://github.com/AmeyPandit36/Ecommerce-Analytics-Dashboard |
| Ready to ship | Yes — `.github/workflows/deploy.yml`, `vercel.json`, `render.yaml` and `Dockerfile` are all committed; adding one repository secret is the only remaining step |

---

## 0. Fastest path — GitHub Actions (no local network access needed)

`.github/workflows/deploy.yml` runs on every push to `main` and on demand. It first boots the app
and runs `scripts/smoke_test.py` (231 checks), then deploys to whichever host has a credential
configured, then re-runs the same 231 checks against the **live** URL.

1. Add **one** of these under *Settings → Secrets and variables → Actions → New repository secret*:

   | Host | Secrets |
   |---|---|
   | Vercel (default) | `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` |
   | Render | `RENDER_DEPLOY_HOOK_URL` (Settings → Deploy Hook), plus an optional repo *variable* `RENDER_URL` so the post-deploy smoke test knows where to point |
   | Fly.io | `FLY_API_TOKEN` (and a `fly.toml` at the repo root) |

2. *Actions → Deploy → Run workflow* (or push to `main`). With no secret configured the workflow
   still verifies the app and reports that nothing was deployed — it does not fail.

From a machine without egress to the hosting APIs (a locked-down sandbox, for example), trigger the
same run with the GitHub CLI:

```bash
gh workflow run deploy.yml --ref main -f target=vercel
gh run watch            # stream the logs
```


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

There is nothing to configure beyond that: `vercel.json` is already in the repo and only carries
the function settings (see below).

### How the pieces fit

| Concern | How it is handled |
|---|---|
| Entrypoint | Vercel's zero-config Python runtime finds the module-level `app` in `app.py` (repo root). `api/index.py` re-exports the same object for runtimes that look for `api/index` (`handler = app`) — one code path, no duplicated app factory |
| Build | none. `builds`/`outputDirectory` are deliberately **not** set: Vercel ships the repo as-is and the Python runtime installs `requirements.txt` |
| Runtime deps | only `Flask` (`requirements.txt`). Analytics run on stdlib `sqlite3`, so no pandas/numpy wheels are installed → small bundle, fast cold start. `requirements-dev.txt` (pandas, kagglehub, gunicorn) is dev-only and never installed on the server |
| Data | `data/ecommerce.db` (7.9 MB) and `data/Ecommerce.csv` (2.4 MB) are **committed**, so the function reads them straight from `/var/task/data`. No KaggleHub call ever happens at runtime — the deployed app works with no network access and no Kaggle credentials |
| Self-healing | if the DB is missing or unreadable, `data/loader.py` rebuilds it from the CSV into the first writable directory it finds (`DATA_DIR`, then `/tmp`), and the UI degrades to an offline page with a clear message instead of a 500 |
| Static assets | Vercel serves `public/**` from its CDN, so assets live in `public/static/` (Flask's own `static` folder is intentionally not used); `Chart.js` is vendored at `public/static/vendor/chart.umd.min.js` — no CDN links anywhere |
| Function settings | `vercel.json`: `maxDuration: 30` (cold start + a few SQL aggregates), `excludeFiles` trims `.git`, caches, virtualenvs and `tests/` out of the bundle |
| Python version | `.python-version` pins 3.12 |

### Environment variables (all optional)

Set them in **Project → Settings → Environment Variables** only if you want them:

* `DATA_DIR` — alternate location for the SQLite store (e.g. a mounted path).
* `ANALYST_LLM=1` + `OPENAI_API_KEY` (+ `ANALYST_LLM_MODEL`) — lets a model rephrase analyst prose.
  Off by default; numbers are always the app's own SQL results.
* `SECRET_KEY` — the app has no sessions/flashes, so this is inert; set it if you add auth.

---

## 2. Verify the live URL

Replace `https://YOUR-APP.vercel.app` below. The repo ships a checker that runs the exact same
assertions against a remote deployment:

```bash
python scripts/smoke_test.py https://YOUR-APP.vercel.app
```

It must print `231 checks, 0 failures`. It validates:

1. `/`, `/dashboard`, `/sales`, `/customers`, `/journey`, `/data-quality`, `/ai-analyst`,
   `/healthz`, `/api/summary`, `/api/products`, `/api/export` all return 200 (no error pages).
2. `/static/app.css`, `/static/app.js` and the vendored Chart.js are served at the expected size.
3. every `<canvas data-chart>` on the page has a matching spec in the embedded JSON payload, with
   non-empty labels/series and numeric data (i.e. charts really render), and every `<use href="#i-…">`
   icon exists in the inlined sprite.
4. each filter parameter changes the aggregates (`?cat=2`, `?pay=1`, `?dev=0`, `?utype=1`,
   `?chan=4`, `?loc=46`, `?bucket=Long`, `?purch=1/0`, `?month=11`, `?rmin=4`, `?dmin=15`,
   `?dmax=0`, `?from=…`, `?to=…`, and combinations), and an impossible filter (`?cat=99`) yields
   an empty result rather than an error.
5. headline KPIs (sessions, purchases, revenue) equal a **recomputation from the raw CSV** done
   independently in the test with the stdlib `csv` module — for the unfiltered view and for six
   filter combinations.
6. the AI analyst answers all 14 example questions (plus junk questions, which must be refused) for
   four filter ranges, with no exceptions and no leaked tracebacks.

Then a 60-second manual pass in the browser:

- [ ] Overview KPIs show ₹1.01 Cr revenue, 25,000 sessions, 5,616 purchases, 22.5 % conversion
      (dark theme, subtle borders, no flash of unstyled content).
- [ ] Charts animate in, tooltips show ₹/% values, and the sidebar shows the dataset sha256.
- [ ] Change **Category** → every KPI, chart, table, insight and filter chip updates; **Reset filters**
      returns to the full range.
- [ ] `/sales` product table: search `42`, click a column header to sort, go to page 2, switch rows/page.
- [ ] `/ai-analyst`: click an example chip → answer + evidence table + chart + "How this was computed"
      + limitations; ask "who is the CEO" → it refuses.
- [ ] Browser console is clean (no 404s, no CORS, no Chart.js warnings).

---

## 3. If the deployment fails

| Symptom | Cause and fix |
|---|---|
| `Error: No Python entrypoint found` / `404: NOT_FOUND` | the repo root must contain `app.py` with a module-level `app` (it does). If you moved it, set `builds`/`functions` to your path, or keep `api/index.py` importing it |
| `ModuleNotFoundError: No module named 'core'` / `'analytics'` | the entrypoint was resolved from a subdirectory. Use `api/index.py` (it prepends the repo root to `sys.path`) rather than moving `app.py` |
| `500` with "Analytics store missing" in the footer, or `/healthz` → `{"ok": false}` | `data/ecommerce.db` did not reach the function: it is excluded by `.gitignore`/`excludeFiles`, or the commit that added it is not on the deployed branch. `git ls-files data/` must list both files |
| `413`/bundle-size error on `vercel deploy` | trim more with `functions."app.py".excludeFiles` (docs, notebooks, sample exports). Do **not** exclude `data/`, `core/`, `analytics/`, `public/`, `templates/` |
| `INIT_REPORT_INVALID: handler not found` | the entry module must export `app` (WSGI callable). `api/index.py` also aliases `handler` |
| Function times out (`FUNCTION_INVOCATION_TIMEOUT`) | raise `maxDuration` in `vercel.json` (30 s is already generous: pages compute in tens of milliseconds locally) |
| CSS/JS 404 in production | assets must live at `public/static/**` (Vercel ignores Flask's `static_folder`), and templates must reference `/static/...` via `url_for('static', …)` — check nothing was moved to a repo-root `static/` |
| Blank charts only in production | the payload script (`<script id="page-data">`) must not be stripped by a minifier; Chart.js is vendored, so a 404 for `/static/vendor/chart.umd.min.js` means `public/` was excluded |
| Deploy succeeds but pages are stale | Vercel cached an old build → **Settings → Deployments → Redeploy** with "Clear build cache" |

Debugging order that actually works: `vercel ls` → `vercel inspect <deployment-url>` →
`vercel logs <url> --follow`, then reproduce the same request locally with
`python scripts/smoke_test.py <url>`. Fix the cause and redeploy — do not stop at reporting the
failure.

---

## 4. Any other host (Docker / Render / Railway)

```bash
pip install -r requirements.txt -r requirements-dev.txt
gunicorn "app:create_app()" --bind 0.0.0.0:${PORT:-5050} --workers 2 --timeout 60
```

`create_app()` is the app factory; `app` is also importable as a module attribute
(`gunicorn app:app` works too). Nothing else is needed — no database service, no env vars,
no network access: the dataset travels with the code.
