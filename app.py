import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
import pandas as pd

# Load dataset once at startup; if unavailable, handle gracefully
from data.loader import load_dataset
from analytics import sales, customers, products, funnel, geography, quality, insights, ai_analyst

app = Flask(__name__)
app.config["SECRET_KEY"] = "dataarena-secret"

# Global dataset state
_df = None
_df_status = "Initializing..."

def init_data():
    global _df, _df_status
    try:
        _df, _df_status = load_dataset()
    except Exception as e:
        _df = None
        _df_status = f"Error: {e}"

init_data()

# Helper: build chart data from analytics
@app.context_processor
def inject_globals():
    return dict(
        df_loaded=_df is not None,
        df_status=_df_status,
        dataset_name="Indian E-Commerce Customer Behavior & Purchase",
        version="1.0.0",
    )

@app.route("/")
def root():
    return redirect(url_for("dashboard"))

def apply_filters(df):
    if df is None: return df
    try:
        cat = request.args.get("cat")
        if cat and "product_category" in df.columns: df = df[df["product_category"].astype(str) == cat]
        pay = request.args.get("pay")
        if pay and "payment_method" in df.columns: df = df[df["payment_method"].astype(str) == pay]
        loc = request.args.get("loc")
        if loc and "location" in df.columns: df = df[df["location"].astype(str) == loc]
        dmin = request.args.get("dmin"); dmax = request.args.get("dmax")
        if dmin and "discount_percent" in df.columns: df = df[df["discount_percent"] >= float(dmin)]
        if dmax and "discount_percent" in df.columns: df = df[df["discount_percent"] <= float(dmax)]
    except Exception: pass
    return df

@app.route("/dashboard")
def dashboard():
    data = sales.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    ins = insights.compute(_df) if _df is not None else {"ready": False}
    return render_template("dashboard.html", sales_data=data, insights=ins, df=_df)

@app.route("/sales")
def sales_page():
    data = sales.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("sales.html", data=data, df=_df)

@app.route("/customers")
def customers_page():
    data = customers.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("customers.html", data=data, df=_df)

@app.route("/products")
def products_page():
    data = products.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("products.html", data=data, df=_df)

@app.route("/funnel")
def funnel_page():
    data = funnel.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("funnel.html", data=data, df=_df)

@app.route("/geography")
def geography_page():
    data = geography.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("geography.html", data=data, df=_df)

@app.route("/data-quality")
def data_quality_page():
    data = quality.compute(apply_filters(_df)) if _df is not None else {"ready": False, "reason": _df_status}
    return render_template("data_quality.html", data=data, df=_df)

@app.route("/ai-analyst")
def ai_analyst_page():
    return render_template("ai_analyst.html", df=_df, df_status=_df_status)

@app.route("/api/ask", methods=["POST"])
def api_ask():
    query = request.get_json(silent=True) or {}
    q = query.get("question", "")
    result = ai_analyst.answer_question(q, _df)
    return jsonify(result)

@app.route("/business-questions")
def business_questions():
    return render_template("business_questions.html", df=_df, df_status=_df_status)

@app.route("/api/export")
def export_report():
    # Simple JSON report
    report = {
        "dataset": "Indian E-Commerce Customer Behavior & Purchase",
        "status": _df_status,
        "sales": sales.compute(_df) if _df is not None else None,
        "quality": quality.compute(_df) if _df is not None else None,
    }
    return jsonify(report)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
