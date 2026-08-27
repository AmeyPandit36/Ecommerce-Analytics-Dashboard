import re

def answer_question(query, df):
    if df is None or len(df) == 0:
        return {"answer":"Dataset not loaded.","evidence":"N/A","visualization":None,"interpretation":"Load dataset to analyze.","limitations":"File missing."}
    q = query.lower()
    # Keyword mapping
    if any(w in q for w in ["category","categories","best category","top category","revenue by category"]):
        if "revenue" in df.columns and "product_category" in df.columns:
            top = df.groupby("product_category")["revenue"].sum().sort_values(ascending=False).head(1)
            cat = int(top.index[0]); rev = float(top.iloc[0])
            return {"answer":f"Category {cat} generates the most revenue (₹{rev:,.0f}).","evidence":f"Revenue by category: {cat} = ₹{rev:,.0f}","visualization":"bar","interpretation":"This category drives the largest share of business revenue.","limitations":"Category IDs are encoded; mapping to names requires external reference."}
    if any(w in q for w in ["cart abandon","abandonment","abandoned"]):
        rate = float(df["cart_abandoned"].mean()*100) if "cart_abandoned" in df.columns else 0
        return {"answer":f"Cart abandonment rate is {rate:.1f}%.","evidence":f"Mean cart_abandoned = {rate:.1f}%","visualization":"donut","interpretation":"A significant share of sessions do not complete purchase.","limitations":"Abandonment metric is session-level and may include non-cart interactions."}
    if any(w in q for w in ["payment","payment method","most popular payment"]):
        if "payment_method" in df.columns:
            top = df["payment_method"].value_counts().head(1)
            method = int(top.index[0]); count = int(top.iloc[0])
            return {"answer":f"Payment method {method} is most popular ({count} uses).","evidence":f"Count = {count}","visualization":"bar","interpretation":"This method dominates checkout preferences.","limitations":"Payment methods are encoded integers; decoding requires category mapping."}
    if any(w in q for w in ["top product","best product","top 5 products","best performing","top products"]):
        if "product_id" in df.columns and "revenue" in df.columns:
            top = df.groupby("product_id")["revenue"].sum().sort_values(ascending=False).head(5)
            return {"answer":"Top products by revenue: " + ", ".join([f"Product {k} (₹{v:,.0f})" for k,v in top.items()]),"evidence":"Top 5 product revenue sums shown.","visualization":"horizontal_bar","interpretation":"These products contribute disproportionately to revenue.","limitations":"Product IDs are encoded; names not available in dataset."}
    if any(w in q for w in ["rating","best rating","highest rating","ratings"]):
        if "rating" in df.columns:
            avg = float(df["rating"].mean()); top = df.groupby("product_id")["rating"].mean().sort_values(ascending=False).head(1)
            return {"answer":f"Average rating is {avg:.2f}. Highest-rates product: {top.index[0]} (avg {top.iloc[0]:.2f}).","evidence":f"Overall mean = {avg:.2f}; top product = {top.index[0]}","visualization":"bar","interpretation":"Higher ratings may correlate with satisfaction.","limitations":"Ratings are integer-scale; interpret as ordinal."}
    if any(w in q for w in ["discount","discount percent","does discount","correlation"]):
        if "discount_percent" in df.columns and "purchased" in df.columns:
            import numpy as np
            corr = float(np.corrcoef(df["discount_percent"].fillna(0), df["purchased"].fillna(0))[0,1])
            return {"answer":f"Discount % has a {('positive' if corr>0 else 'negative' if corr<0 else 'near-zero')} correlation with purchase (r={corr:.2f}).","evidence":f"Pearson r = {corr:.2f}","visualization":"scatter","interpretation":"Relationship is correlational, not causal.","limitations":"Correlation does not imply causation; other variables may confound."}
    if any(w in q for w in ["location","where","city","geography","region","highest spending"]):
        if "location" in df.columns and "revenue" in df.columns:
            top = df.groupby("location")["revenue"].sum().sort_values(ascending=False).head(1)
            loc = int(top.index[0]); rev = float(top.iloc[0])
            return {"answer":f"Location {loc} has the highest total spending (₹{rev:,.0f}).","evidence":f"Revenue by location top = {loc} ({rev:,.0f})","visualization":"bar","interpretation":"Geographic concentration suggests regional demand patterns.","limitations":"Location is encoded integer; decoding requires external mapping."}
    # Default
    return {"answer":"Based on the dataset, I can analyze categories, sales, customers, and behavior.","evidence":"Available columns: " + ", ".join(df.columns[:10].tolist()),"visualization":"table","interpretation":"Ask a specific question about revenue, products, customers, discounts, or geography.","limitations":"Some fields are encoded and require mapping for full interpretation."}
