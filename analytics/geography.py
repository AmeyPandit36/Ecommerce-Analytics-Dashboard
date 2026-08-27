def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    res = {}
    if "location" in df.columns and "revenue" in df.columns:
        res["revenue_by_location"] = df.groupby("location")["revenue"].sum().sort_values(ascending=False).head(10).to_dict()
    if "location" in df.columns and "customer_id" in df.columns:
        res["customers_by_location"] = df.groupby("location")["customer_id"].nunique().sort_values(ascending=False).head(10).to_dict()
    if "location" in df.columns:
        res["orders_by_location"] = df.groupby("location").size().sort_values(ascending=False).head(10).to_dict()
    return {"ready": True, **res}
