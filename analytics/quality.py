def compute(df):
    if df is None or len(df) == 0: return {"ready": False, "reason": "Dataset not loaded"}
    rows = len(df)
    cols = len(df.columns)
    missing = int(df.isnull().sum().sum())
    dups = int(df.duplicated().sum())
    # Quality score (transparent): start 100, penalize missing, dups, outliers
    score = 100
    score -= (missing / (rows * cols)) * 20
    score -= (dups / rows) * 10
    # Outlier rough check on revenue
    outlier_penalty = 0
    if "revenue" in df.columns:
        q99 = df["revenue"].quantile(0.99)
        outliers = int((df["revenue"] > q99 * 3).sum())
        outlier_penalty = (outliers / rows) * 5
    score -= outlier_penalty
    score = max(0, min(100, round(score)))
    # Detect issues per column
    issues = []
    for col in df.columns:
        nulls = int(df[col].isnull().sum())
        if nulls > 0:
            issues.append({"column": col, "issue": f"{nulls} missing values", "pct": round(nulls/rows*100,1)})
    # Numeric outlier flag
    if "revenue" in df.columns:
        outliers = int((df["revenue"] > df["revenue"].quantile(0.999)).sum())
        if outliers > 0:
            issues.append({"column": "revenue", "issue": f"{outliers} extreme outliers (>99.9th pct)", "pct": round(outliers/rows*100,1)})
    return {"ready": True, "rows": rows, "cols": cols, "missing": missing, "duplicates": dups,
            "quality_score": score, "issues": issues}
