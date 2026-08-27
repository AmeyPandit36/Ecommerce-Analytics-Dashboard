def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    total = len(df)
    added = int(df["added_to_cart"].sum()) if "added_to_cart" in df.columns else 0
    purchased = int(df["purchased"].sum()) if "purchased" in df.columns else 0
    abandoned = int(df["cart_abandoned"].sum()) if "cart_abandoned" in df.columns else 0
    # Funnel: Sessions -> Added to Cart -> Purchased (using behavioral flags)
    # Also calculate drop-off
    results = {
        "ready": True,
        "total_sessions": total,
        "added_to_cart": added,
        "purchased": purchased,
        "cart_abandoned": abandoned,
        "add_to_cart_rate": round(added/total*100,2) if total else 0,
        "purchase_rate_from_cart": round(purchased/added*100,2) if added else 0,
        "purchase_rate_from_session": round(purchased/total*100,2) if total else 0,
        "abandonment_rate": round(abandoned/total*100,2) if total else 0,
    }
    return results
