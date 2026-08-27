"""Ecommerce Analytics Dashboard — Flask application.

Serves a premium analytics UI over the bundled Kaggle dataset
(data/Ecommerce.csv -> data/ecommerce.db, built by scripts/build_dataset.py).
Every KPI, chart and table on every page is a live SQL aggregate over the real
dataset rows and respects the global filter bar.

Local:   python app.py          → http://localhost:5050
Vercel:  api/index.py re-exports `app` (see DEPLOYMENT.md)
"""
from __future__ import annotations

import json
import math
import os
import time

from flask import Flask, Response, jsonify, redirect, render_template, request, url_for

from analytics import ai_analyst as analyst
from analytics import customers, funnel, insights, products, quality, sales
from core import format as F
from core import filters as FL
from data.loader import load_store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION = "2.0.0"

STORE, STATUS = load_store()

# (endpoint, label, icon, blurb)
NAV = (
    ("dashboard", "Overview", "grid", "KPIs, trends and auto-generated insights"),
    ("sales", "Sales & Products", "chart", "Revenue, categories, discounts, rankings"),
    ("customers", "Customers", "users", "Value segmentation, behaviour, spend"),
    ("journey", "Customer Journey", "filter", "Sessions → cart → purchase"),
    ("analyst", "AI Analyst", "sparkles", "Ask the data a question"),
    ("quality", "Data Quality", "shield", "Completeness, duplicates, outliers"),
)


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
            "store": STORE,
            "df_loaded": STORE is not None,
            "df_status": STATUS,
            "version": VERSION,
            "dataset_name": "Indian E-Commerce Customer Behavior & Purchase",
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
        """Shown when a filter combination leaves nothing to aggregate."""
        return [{"kind": "note", "tone": "warn", "icon": "eye",
                 "title": "No rows match these filters",
                 "text": (reason or "The aggregation returned an empty set.")
                         + " The bundled dataset holds 25,000 sessions spanning "
                           "2024-01-01 to 2024-12-30, so reset a filter to get data back."}]

    def filter_state():
        """(where clause, bound params, active chips) for the global filter bar."""
        if STORE is None:
            return "", (), []
        where, params, active = FL.build_where(request.args.to_dict(), STORE)
        keep = FL.keep_filter_args(request.args.to_dict())
        for item in active:  # chip -> link that removes only this filter
            item["remove_url"] = "?" + FL.query_string({**keep, item["key"]: ""})
        return where, params, active

    def page(title, subtitle, sections, *, meta=None, status_code=200, elapsed=0.0):
        _where, _params, active = filter_state()
        charts = {}
        table_state = None
        for section in sections:
            if section.get("kind") == "charts":
                for chart in section.get("items", []):
                    charts[chart["id"]] = chart
            elif section.get("kind") == "product_table":
                table_state = section.get("table")
        payload = {
            "charts": charts,
            "productTable": table_state,
            "filters": FL.keep_filter_args(request.args.to_dict()),
            "routes": {"products": url_for("api_products")},
        }
        context = {
            "page_title": title,
            "page_subtitle": subtitle,
            "sections": sections,
            "filters": payload["filters"],
            "active_filters": active,
            "filter_options": (FL.options(STORE) if STORE is not None else {}),
            "filter_specs": FL.ui_specs(),
            "hide_filters": bool((meta or {}).get("no_filters")),
            "meta": meta or {},
            "payload": payload,
            "elapsed_ms": round(elapsed * 1000, 1),
        }
        if STORE is None:
            return render_template("offline.html", **context), status_code
        return render_template("page.html", **context), status_code

    # ----------------------------------------------------------------------- web
    @app.route("/")
    def root():
        return redirect(url_for("dashboard"))

    @app.route("/healthz")
    def healthz():
        rows = STORE.scalar("SELECT COUNT(*) FROM sessions", (), 0) if STORE else 0
        return jsonify({"ok": STORE is not None, "rows": rows, "status": STATUS,
                        "version": VERSION})

    @app.route("/dashboard", endpoint="dashboard")
    def dashboard_page():
        if STORE is None:
            return page("Overview", "Executive dashboard", [])
        started = time.perf_counter()
        where, params, _ = filter_state()
        try:
            data = sales.compute(STORE, where, params)
            if not data.get("ready"):
                return page("Overview", "Executive dashboard", empty_state(data.get("reason")),
                            elapsed=time.perf_counter() - started)
            ins = insights.compute(STORE, where, params)
            charts = data["charts"]
            sections = [
                {"kind": "kpis", "items": data["kpis"]},
                {"kind": "insights", "items": ins["insights"]},
                {"kind": "charts", "items": charts[0:1]},
                {"kind": "charts", "items": charts[1:3]},
                {"kind": "charts", "items": [charts[5], charts[3]]},
                {"kind": "tables", "items": data["tables"][0:1]},
            ]
            return page("Overview", "Executive dashboard — KPIs, trends and auto-generated insights",
                        sections, meta={"totals": data["totals"], "granularity": data["trend_granularity"],
                                        "insight_count": ins["all_insights"]},
                        elapsed=time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover
            return _error_page(exc, "Overview")

    @app.route("/sales", endpoint="sales")
    def sales_page():
        if STORE is None:
            return page("Sales & Products", "Revenue, categories, discounts and products", [])
        started = time.perf_counter()
        where, params, _ = filter_state()
        try:
            data = sales.compute(STORE, where, params)
            if not data.get("ready"):
                return page("Sales & Products", "Revenue, categories, discounts and products",
                            empty_state(data.get("reason")), elapsed=time.perf_counter() - started)
            args = request.args.to_dict()
            table = products.product_table(
                STORE, where, params, q=args.get("q", ""), sort=args.get("sort", "revenue"),
                direction=args.get("dir", "desc"), page=args.get("page", 1),
                per_page=args.get("per", 12))
            charts = data["charts"]
            sections = [
                {"kind": "kpis", "items": data["kpis"]},
                {"kind": "charts", "items": charts[0:2]},
                {"kind": "tables", "items": data["tables"]},
                {"kind": "charts", "items": charts[2:3] + data["products"]["charts"][0:1]},
                {"kind": "charts", "items": charts[3:6]},
                {"kind": "product_table", "table": table, "highlights": data["products"]["highlights"]},
                {"kind": "charts", "items": charts[6:] + data["products"]["charts"][1:]},
            ]
            return page("Sales & Products",
                        "Revenue, category performance, discounts and product rankings", sections,
                        meta={"totals": data["totals"], "highlights": data["products"]["highlights"]},
                        elapsed=time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover
            return _error_page(exc, "Sales & Products")

    @app.route("/customers", endpoint="customers")
    def customers_page():
        if STORE is None:
            return page("Customers", "Segmentation and behaviour", [])
        started = time.perf_counter()
        where, params, _ = filter_state()
        try:
            data = customers.compute(STORE, where, params)
            if not data.get("ready"):
                return page("Customers", "Segmentation and behaviour", empty_state(data.get("reason")),
                            elapsed=time.perf_counter() - started)
            charts = data["charts"]
            sections = [
                {"kind": "kpis", "items": data["kpis"]},
                {"kind": "methodology", "data": data["segment_rule"]},
                {"kind": "tables", "items": data["tables"][0:1]},
                {"kind": "charts", "items": charts[0:2]},
                {"kind": "charts", "items": charts[2:4]},
                {"kind": "tables", "items": data["tables"][1:]},
                {"kind": "charts", "items": charts[4:]},
            ]
            return page("Customers", "Who buys, how much they spend, and what separates the segments",
                        sections, meta={"totals": data["totals"]},
                        elapsed=time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover
            return _error_page(exc, "Customers")

    @app.route("/journey", endpoint="journey")
    @app.route("/funnel")
    def journey_page():
        if STORE is None:
            return page("Customer Journey", "Funnel and conversion drivers", [])
        started = time.perf_counter()
        where, params, _ = filter_state()
        try:
            data = funnel.compute(STORE, where, params)
            if not data.get("ready"):
                return page("Customer Journey", "Funnel and conversion drivers",
                            empty_state(data.get("reason")), elapsed=time.perf_counter() - started)
            charts = data["charts"]
            sections = [
                {"kind": "kpis", "items": data["kpis"]},
                {"kind": "funnel", "steps": data["steps"], "dropoffs": data["dropoffs"]},
                {"kind": "charts", "items": charts[0:1] + charts[4:5]},
                {"kind": "charts", "items": charts[1:4]},
                {"kind": "tables", "items": data["tables"]},
                {"kind": "charts", "items": charts[5:]},
            ]
            return page("Customer Journey", "Sessions → carts → purchases, and what moves conversion",
                        sections, meta={"totals": data["totals"]}, elapsed=time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover
            return _error_page(exc, "Customer Journey")

    @app.route("/data-quality", endpoint="quality")
    @app.route("/quality")
    def quality_page():
        if STORE is None:
            return page("Data Quality", "Dataset profile", [])
        started = time.perf_counter()
        try:
            data = quality.compute(STORE)
            sections = [
                {"kind": "kpis", "items": data["kpis"]},
                {"kind": "quality", "data": data},
                {"kind": "charts", "items": data["charts"]},
                {"kind": "tables", "items": data["tables"]},
            ]
            return page("Data Quality", "Completeness, duplicates, types, outliers and semantics notes",
                        sections, meta={"score": data["score"], "meta": data["meta"], "no_filters": True},
                        elapsed=time.perf_counter() - started)
        except Exception as exc:  # pragma: no cover
            return _error_page(exc, "Data Quality")

    @app.route("/ai-analyst", endpoint="analyst")
    def analyst_page():
        _where, _params, active = filter_state()
        return render_template(
            "analyst.html",
            page_title="AI Analyst",
            page_subtitle="A deterministic query engine over the dataset — no language model, no invented answers",
            examples=list(analyst.EXAMPLES),
            filters=FL.keep_filter_args(request.args.to_dict()),
            active_filters=active,
            filter_options=(FL.options(STORE) if STORE is not None else {}),
            filter_specs=FL.ui_specs(),
            hide_filters=False,
            meta={},
            payload={"charts": {}, "productTable": None,
                     "filters": FL.keep_filter_args(request.args.to_dict()),
                     "routes": {"ask": url_for("api_ask"), "products": url_for("api_products")}},
            elapsed_ms=0.0,
        )

    # --------------------------------------------------------------------- apis
    @app.route("/api/products", endpoint="api_products")
    def api_products():
        if STORE is None:
            return jsonify({"ready": False, "reason": STATUS}), 503
        where, params, _ = filter_state()
        args = request.args.to_dict()
        data = products.product_table(
            STORE, where, params,
            q=args.get("q", ""), sort=args.get("sort", "revenue"),
            direction=args.get("dir", "desc"), page=args.get("page", 1),
            per_page=args.get("per", 12))
        data["ready"] = True
        data["filters"] = FL.keep_filter_args(args)
        return jsonify(data)

    @app.route("/api/ask", methods=["POST", "GET"], endpoint="api_ask")
    def api_ask():
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question") or request.args.get("q") or "")[:400]
        if request.args.get("ignore_filters") == "1" or payload.get("ignore_filters"):
            where, params = "", ()
        else:
            where, params, _ = filter_state()
        started = time.perf_counter()
        try:
            answer = analyst.answer_question(question, STORE, where, params)
            answer = analyst.llm_polish(answer)
        except Exception as exc:  # a bad question must never break the page
            app.logger.exception("AI analyst failed for %r", question)
            answer = {"answer": "That question hit an internal error, so nothing was reported.",
                      "detail": (f"{type(exc).__name__}: {exc}" if app.debug else
                                 "The query for this intent failed. Try one of the suggested questions "
                                 "or simplify the wording."), "evidence": None, "chart": None,
                      "method": "n/a", "limitations": "Nothing was estimated or invented.",
                      "confidence": "error", "followups": list(analyst.EXAMPLES[:4]),
                      "question": question}
        answer["took_ms"] = round((time.perf_counter() - started) * 1000, 1)
        answer["filters"] = FL.keep_filter_args(request.args.to_dict())
        answer["examples"] = list(analyst.EXAMPLES)
        return jsonify(_sanitise(answer))

    @app.route("/api/summary")
    def api_summary():
        if STORE is None:
            return jsonify({"ready": False, "reason": STATUS}), 503
        where, params, _ = filter_state()
        return jsonify({"ready": True, "totals": sales.compute(STORE, where, params)["totals"],
                        "status": STATUS})

    @app.route("/api/export")
    def api_export():
        if STORE is None:
            return jsonify({"ready": False, "reason": STATUS}), 503
        where, params, active = filter_state()
        sales_data = sales.compute(STORE, where, params)
        report = {
            "dataset": "Indian E-Commerce Customer Behavior & Purchase",
            "source": {"slug": STORE.meta.get("dataset_slug"), "file": STORE.meta.get("source_csv"),
                       "csv_sha256": STORE.meta.get("csv_sha256"),
                       "csv_bytes": STORE.meta.get("csv_bytes"),
                       "built_at": STORE.meta.get("generated_utc")},
            "generated_utc": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            "status": STATUS,
            "filters": {item["key"]: item["raw"] for item in active},
            "totals": sales_data["totals"],
            "insights": [{"title": item["title"], "text": item["text"], "metric": item["metric"]}
                         for item in insights.compute(STORE, where, params)["insights"]],
            "segments": customers.compute(STORE, where, params)["segments"],
            "quality": {key: value for key, value in quality.compute(STORE).items()
                        if key in ("score", "dtype_counts", "findings", "meta")},
        }
        body = json.dumps(_sanitise(report), indent=2, default=str)
        return Response(body, mimetype="application/json",
                        headers={"Content-Disposition": 'attachment; filename="dashboard-report.json"'})

    # --------------------------------------------------------------- error paths
    def _error_page(exc: Exception, title: str):
        app.logger.exception("%s failed", title)
        return render_template("offline.html", page_title=title,
                               page_subtitle="This view hit an error instead of data",
                               sections=[], filters={}, active_filters=[], filter_options={},
                               hide_filters=True, payload={"charts": {}, "productTable": None},
                               meta={"error": f"{type(exc).__name__}: {exc}"}, elapsed_ms=0.0), 500

    @app.errorhandler(404)
    def not_found(_exc):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found", "path": request.path}), 404
        return render_template("offline.html", page_title="Page not found",
                               page_subtitle=f"No route matches <code>{request.path}</code>",
                               sections=[], filters={}, active_filters=[], filter_options={},
                               hide_filters=True, payload={"charts": {}, "productTable": None},
                               meta={"missing": request.path}, elapsed_ms=0.0), 404

    @app.errorhandler(500)
    def server_error(_exc):  # pragma: no cover
        return render_template("offline.html", page_title="Server error",
                               page_subtitle="Something went wrong while computing this view",
                               sections=[], filters={}, active_filters=[], filter_options={},
                               hide_filters=True, payload={"charts": {}, "productTable": None},
                               meta={"error": "Internal server error — see server logs"},
                               elapsed_ms=0.0), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    print(f"Ecommerce Analytics Dashboard → http://0.0.0.0:{port}  |  {STATUS}")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
