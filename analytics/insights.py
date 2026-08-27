def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    insights = []
    # Ranking insight
    if "product_category" in df.columns and "revenue" in df.columns:
        top = df.groupby("product_category")["revenue"].sum().sort_values(ascending=False).head(1)
        if not top.empty:
            cat = int(top.index[0])
            rev = float(top.iloc[0])
            insights.append({"type":"ranking","title":"Top Revenue Category","text":f"Category {cat} leads in revenue (₹{rev:,.0f}).","metric":"revenue"})
    # Trend insight (monthly)
    if "visit_month" in df.columns and "revenue" in df.columns:
        monthly = df.groupby("visit_month")["revenue"].sum()
        if len(monthly) > 1:
            first, last = monthly.iloc[0], monthly.iloc[-1]
            change = ((last - first) / first * 100) if first else 0
            insights.append({"type":"trend","title":"Revenue Trend","text":f"Revenue changed {change:+.1f}% from first to last month.","metric":"revenue"})
    # Concentration
    if "product_category" in df.columns and "purchased" in df.columns:
        cat_purchases = df.groupby("product_category")["purchased"].sum().sort_values(ascending=False)
        top3 = cat_purchases.head(3).sum()
        total = cat_purchases.sum()
        share = top3/total*100 if total else 0
        insights.append({"type":"concentration","title":"Top Category Concentration","text":f"Top 3 categories account for {share:.1f}% of purchases.","metric":"share"})
    # Correlation: discount vs purchase
    if "discount_percent" in df.columns and "purchased" in df.columns:
        import numpy as np
        corr = float(np.corrcoef(df["discount_percent"].fillna(0), df["purchased"].fillna(0))[0,1])
        direction = "positive" if corr > 0 else "negative" if corr < 0 else "neutral"
        insights.append({"type":"correlation","title":"Discount vs Purchase","text":f"Discount % shows a {direction} correlation (r={corr:.2f}) with purchase.","metric":"correlation"})
    # Abandonment
    if "cart_abandoned" in df.columns:
        rate = float(df["cart_abandoned"].mean()*100)
        insights.append({"type":"anomaly","title":"Cart Abandonment","text":f"Cart abandonment rate is {rate:.1f}%.","metric":"abandonment"})
    return {"ready": True, "insights": insights}
