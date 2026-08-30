"""E-Commerce Customer Behavior & Purchase Analysis — Flask application.

A professional, Power BI-style interactive analytics report over the bundled
Kaggle dataset (data/Ecommerce.csv -> data/ecommerce.db, built by
scripts/build_dataset.py). Every KPI, chart, callout and finding on every page is
a live SQL aggregate over the real dataset rows and respects the global slicers.

Four report pages (no product/SKU rankings — product_id is not a stable SKU):

    /overview     Executive overview
    /customers    Customer behavior & value
    /conversion   Conversion & purchase behavior
    /categories   Category & price performance

Local:   python app.py          -> http://localhost:5050
Vercel:  api/index.py re-exports `app` (see DEPLOYMENT.md)
"""
from __future__ import annotations

import json
import math
import os
import time

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from analytics import report
from core import format as F
from core import filters as FL
from data.loader import load_store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "3.0.0"

STORE, STATUS = load_store()

# (endpoint, label, icon, blurb)
NAV = (
    ("overview", "Overview", "grid", "Executive summary — KPIs, findings and funnel"),
    ("customers", "Customers", "users", "Segmentation, value and who drives revenue"),
    ("conversion", "Conversion", "filter", "Funnel, session behaviour and discounts"),
    ("categories", "Category & Price", "tags", "Category, price band and payment performance"),
)

PAGE_META = {
    "overview": {
        "title": "E-Commerce Customer Behavior & Purchase Analysis",
        "subtitle": "An interactive analysis of customer behavior, conversion, revenue "
                    "concentration, category performance, and purchase patterns.",
    },
    "customers": {
        "title": "Customer Behavior & Value",
        "subtitle": "Who is driving revenue? Segmentation, repeat behaviour and value concentration.",
    },
    "conversion": {
        "title": "Conversion & Purchase Behavior",
        "subtitle": "Where are sessions being lost? Funnel leakage, session behaviour and discounts.",
    },
    "categories": {
        "title": "Category & Price Performance",
        "subtitle": "Where does revenue come from — and does revenue mean demand?",
    },
}


def _sanitise(value):
    """JSON-safe: no NaN / Infinity ever reaches the browser."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _sanitise(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitise(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    return str(value)


def create_app() -> Flask:
    app = Flask(
        __name__,
        root_path=BASE_DIR,
        template_folder="templates",
        static_folder=os.path.join(BASE_DIR, "public", "static"),
        static_url_path="/static",
    )
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "ecommerce-analytics-dashboard")
    try:
        app.json.sort_keys = False
    except AttributeError:  # pragma: no cover - older Flask
        app.config["JSON_SORT_KEYS"] = False

    # ------------------------------------------------------------- template kit
    @app.context_processor
    def inject_globals():
        meta = STORE.meta if STORE else {}
        return {
            "nav": NAV,
            "page_meta": PAGE_META,
            "store": STORE,
            "df_loaded": STORE is not None,
            "df_status": STATUS,
            "version": VERSION,
            "dataset_name": "E-Commerce Customer Behavior & Purchase Analysis",
            "dataset_slug": meta.get("dataset_slug")
                            or "kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase",
            "dataset_rows": meta.get("rows"),
            "inr": F.inr,
            "inr_short": F.inr_short,
            "num": F.number,
            "pct": F.pct,
            "compact": F.compact,
            "date_label": F.date_label,
        }

    @app.template_filter("jsonjs")
    def jsonjs(value):
        return json.dumps(_sanitise(value), default=str).replace("</", "<\\/")

    @app.after_request
    def security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=86400, immutable")
        return response

    # ------------------------------------------------------------------- helpers
    def empty_state(reason: str | None = None) -> list:
        return [{"kind": "note", "tone": "warn", "icon": "eye",
                 "title": "No rows match these filters",
                 "text": (reason or "The aggregation returned an empty set.")
                         + " The bundled dataset holds 25,000 sessions spanning "
                           "2024-01-01 to 2024-12-30, so reset a filter to get data back."}]

    def filter_state():
        if STORE is None:
            return "", (), []
        where, params, active = FL.build_where(request.args.to_dict(), STORE)
        keep = FL.keep_filter_args(request.args.to_dict())
        for item in active:
            item["remove_url"] = "?" + FL.query_string({**keep, item["key"]: ""})
        return where, params, active

    def page(key, data, status_code=200, elapsed=0.0):
        _where, _params, active = filter_state()
        sections = (data or {}).get("sections", [])
        charts = {}
        for section in sections:
            if section.get("kind") == "charts":
                for chart in section.get("items", []):
                    charts[chart["id"]] = chart
        payload = {
            "charts": charts,
            "filters": FL.keep_filter_args(request.args.to_dict()),
            "routes": {},
        }
        context = {
            "page_key": key,
            "page_title": PAGE_META[key]["title"],
            "page_subtitle": PAGE_META[key]["subtitle"],
            "sections": sections,
            "filters": payload["filters"],
            "active_filters": active,
            "filter_options": (FL.options(STORE) if STORE is not None else {}),
            "filter_specs": FL.ui_specs(),
            "hide_filters": False,
            "meta": {"totals": (data or {}).get("totals", {})},
            "payload": payload,
            "elapsed_ms": round(elapsed * 1000, 1),
        }
        if STORE is None:
            return render_template("offline.html", **context), status_code
        return render_template("page.html", **context), status_code

    def render_report_page(key):
        if STORE is None:
            return page(key, None)
        started = time.perf_counter()
        where, params, _ = filter_state()
        try:
            data = report.PAGES[key](STORE, where, params)
        except Exception as exc:  # pragma: no cover
            app.logger.exception("%s failed", key)
            return render_template("offline.html", page_title=PAGE_META[key]["title"],
                                   page_subtitle="This view hit an error instead of data",
                                   sections=[], filters={}, active_filters=[], filter_options={},
                                   hide_filters=True, payload={"charts": {}},
                                   page_meta=PAGE_META, nav=NAV, store=STORE,
                                   df_loaded=STORE is not None, df_status=STATUS,
                                   page_key=key, meta={"error": f"{type(exc).__name__}: {exc}"},
                                   elapsed_ms=0.0), 500
        if not data.get("ready"):
            data["sections"] = empty_state(data.get("reason"))
        return page(key, data, elapsed=time.perf_counter() - started)

    # ----------------------------------------------------------------------- web
    @app.route("/")
    def root():
        return redirect(url_for("overview"))

    @app.route("/healthz")
    def healthz():
        rows = STORE.scalar("SELECT COUNT(*) FROM sessions", (), 0) if STORE else 0
        return jsonify({"ok": STORE is not None, "rows": rows, "status": STATUS,
                        "version": VERSION})

    @app.route("/overview", endpoint="overview")
    def overview_page():
        return render_report_page("overview")

    @app.route("/customers", endpoint="customers")
    def customers_route():
        return render_report_page("customers")

    @app.route("/conversion", endpoint="conversion")
    def conversion_route():
        return render_report_page("conversion")

    @app.route("/categories", endpoint="categories")
    def categories_route():
        return render_report_page("categories")

    # Legacy endpoints now redirect to the closest report page.
    @app.route("/dashboard")
    def legacy_dashboard():
        return redirect(url_for("overview"))

    @app.route("/journey")
    @app.route("/funnel")
    def legacy_journey():
        return redirect(url_for("conversion"))

    @app.route("/category-price")
    def legacy_category_price():
        return redirect(url_for("categories"))

    @app.route("/sales")
    def legacy_sales():
        return redirect(url_for("categories"))

    @app.route("/data-quality")
    @app.route("/quality")
    def legacy_quality():
        return redirect(url_for("categories"))

    @app.route("/ai-analyst")
    def legacy_analyst():
        return redirect(url_for("overview"))

    # --------------------------------------------------------------------- apis
    @app.route("/api/summary")
    def api_summary():
        if STORE is None:
            return jsonify({"ready": False, "reason": STATUS}), 503
        where, params, _ = filter_state()
        return jsonify({"ready": True, "totals": report.overview(STORE, where, params)["totals"],
                        "status": STATUS})

    @app.route("/api/export")
    def api_export():
        if STORE is None:
            return jsonify({"ready": False, "reason": STATUS}), 503
        where, params, active = filter_state()
        out = {
            "dataset": "E-Commerce Customer Behavior & Purchase Analysis",
            "source": {"slug": STORE.meta.get("dataset_slug"), "file": STORE.meta.get("source_csv"),
                       "csv_sha256": STORE.meta.get("csv_sha256"),
                       "csv_bytes": STORE.meta.get("csv_bytes"),
                       "built_at": STORE.meta.get("generated_utc")},
            "generated_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "status": STATUS,
            "filters": {item["key"]: item["raw"] for item in active},
            "totals": report.overview(STORE, where, params)["totals"],
            "segments": report.segment_data(STORE, where, params)["segments"],
        }
        body = json.dumps(_sanitise(out), indent=2, default=str)
        return Response(body, mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="dashboard-report.json"'})

    # --------------------------------------------------------------- error paths
    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found", "path": request.path}), 404
        return render_template("offline.html", page_title="Page not found",
                               page_subtitle=f"No route matches <code>{request.path}</code>",
                               sections=[], filters={}, active_filters=[], filter_options={},
                               hide_filters=True, payload={"charts": {}},
                               page_meta=PAGE_META, nav=NAV, store=STORE,
                               df_loaded=STORE is not None, df_status=STATUS,
                               page_key="overview", meta={"missing": request.path},
                               elapsed_ms=0.0), 404

    @app.errorhandler(500)
    def server_error(_exc):  # pragma: no cover
        return render_template("offline.html", page_title="Server error",
                               page_subtitle="Something went wrong while computing this view",
                               sections=[], filters={}, active_filters=[], filter_options={},
                               hide_filters=True, payload={"charts": {}},
                               page_meta=PAGE_META, nav=NAV, store=STORE,
                               df_loaded=STORE is not None, df_status=STATUS,
                               page_key="overview", meta={"error": "Internal server error"},
                               elapsed_ms=0.0), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    print(f"E-Commerce Customer Behavior & Purchase Analysis → http://0.0.0.0:{port}  |  {STATUS}")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
