def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    # Top products by revenue
    prod_rev = {}
    if "product_id" in df.columns and "revenue" in df.columns:
        prod_rev = df.groupby("product_id")["revenue"].sum().sort_values(ascending=False).head(10).to_dict()
    # Product ratings
    prod_rating = {}
    if "product_id" in df.columns and "rating" in df.columns:
        prod_rating = df.groupby("product_id")["rating"].mean().sort_values(ascending=False).head(10).to_dict()
    # Category performance
    cat_perf = {}
    if "product_category" in df.columns and "revenue" in df.columns:
        cat_perf = df.groupby("product_category").agg({"revenue":"sum","purchased":"sum","rating":"mean"}).sort_values("revenue", ascending=False).head(10).to_dict("index")
    # Discount vs purchase correlation (approx)
    discount_corr = None
    if "discount_percent" in df.columns and "purchased" in df.columns:
        import numpy as np
        discount_corr = float(np.corrcoef(df["discount_percent"].fillna(0), df["purchased"].fillna(0))[0,1])
    return {"ready": True, "top_products_rev": prod_rev, "top_products_rating": prod_rating, "category_perf": cat_perf, "discount_purchase_corr": discount_corr}
