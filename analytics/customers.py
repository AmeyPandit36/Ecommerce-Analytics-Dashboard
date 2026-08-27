def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    # Segmentation by revenue per customer
    cust_rev = df.groupby("customer_id")["revenue"].sum() if "customer_id" in df.columns and "revenue" in df.columns else None
    segments = {}
    if cust_rev is not None and len(cust_rev) > 0:
        q33 = cust_rev.quantile(0.33); q66 = cust_rev.quantile(0.66)
        segments = {
            "High Value": int((cust_rev >= q66).sum()),
            "Medium Value": int(((cust_rev >= q33) & (cust_rev < q66)).sum()),
            "Low Value": int((cust_rev < q33).sum()),
        }
    # Cart abandonment by user type
    abandon = {}
    if "cart_abandoned" in df.columns and "user_type" in df.columns:
        abandon = df.groupby("user_type")["cart_abandoned"].mean().to_dict()
    # Ratings by segment (approximate by purchase status)
    rating_groups = {}
    if "rating" in df.columns and "purchased" in df.columns:
        rating_groups = df.groupby("purchased")["rating"].mean().to_dict()
    # Location concentration
    location_rev = {}
    if "location" in df.columns and "revenue" in df.columns:
        location_rev = df.groupby("location")["revenue"].sum().sort_values(ascending=False).head(5).to_dict()
    return {"ready": True, "segments": segments, "abandon_by_type": abandon, "rating_by_purchase": rating_groups, "top_locations": location_rev}
