def compute(df):
    if df is None or len(df) == 0:
        return {"ready": False, "reason": "Dataset not loaded"}
    # Revenue metrics
    total_revenue = float(df["revenue"].sum()) if "revenue" in df.columns else 0.0
    avg_order_value = float(df["revenue"].mean()) if "revenue" in df.columns else 0.0
    total_orders = int(df["purchased"].sum()) if "purchased" in df.columns else 0
    total_customers = df["customer_id"].nunique() if "customer_id" in df.columns else 0
    conversion_rate = float(df["purchased"].mean() * 100) if "purchased" in df.columns else 0.0
    avg_discount = float(df["discount_percent"].mean()) if "discount_percent" in df.columns else 0.0
    avg_rating = float(df["rating"].mean()) if "rating" in df.columns else 0.0
    # Categories
    cat_revenue = {}
    if "product_category" in df.columns and "revenue" in df.columns:
        cat_revenue = df.groupby("product_category")["revenue"].sum().sort_values(ascending=False).head(5).to_dict()
    # Payment methods
    payment_counts = {}
    if "payment_method" in df.columns:
        payment_counts = df["payment_method"].value_counts().head(5).to_dict()
    # Time trend (monthly revenue)
    monthly = {}
    if "visit_month" in df.columns and "revenue" in df.columns:
        monthly = df.groupby("visit_month")["revenue"].sum().sort_index().to_dict()
    return {
        "ready": True,
        "total_revenue": total_revenue,
        "avg_order_value": avg_order_value,
        "total_orders": total_orders,
        "total_customers": total_customers,
        "conversion_rate": conversion_rate,
        "avg_discount": avg_discount,
        "avg_rating": avg_rating,
        "category_revenue": cat_revenue,
        "payment_counts": payment_counts,
        "monthly_revenue": monthly,
    }
