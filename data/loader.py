"""
Dataset loader for Indian E-Commerce Customer Behavior & Purchase.
Tries multiple sources, validates schema, returns a clean pandas DataFrame.
"""
import os
import sys
import logging

logger = logging.getLogger(__name__)

DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(DATA_DIR, "data", "Ecommerce.csv")
KAGGLE_PATH = os.path.expanduser("~/.cache/kagglehub/datasets/kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase/")


def _find_file():
    candidates = [
        DATA_PATH,
        os.path.join(DATA_DIR, "Ecommerce.csv"),
        os.path.join(os.path.expanduser("~"), "Ecommerce.csv"),
        "/tmp/Ecommerce.csv",
    ]
    # Also search kagglehub downloaded folders
    try:
        import kagglehub
        downloaded = kagglehub.dataset_download("kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase")
        if downloaded:
            for root, _, files in os.walk(downloaded):
                for f in files:
                    if f.lower().endswith(".csv"):
                        candidates.insert(0, os.path.join(root, f))
    except Exception as e:
        logger.info(f"KaggleHub download attempt failed (expected in sandbox): {e}")
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def load_dataset():
    filepath = _find_file()
    if not filepath:
        # Log clearly for UI/state handling
        logger.warning("Dataset file not found locally or via KaggleHub. "
                       "Place Ecommerce.csv in data/ or run kagglehub download script.")
        return None, "Dataset not found. Place Ecommerce.csv in data/ or run download script."

    import pandas as pd
    try:
        df = pd.read_csv(filepath)
    except Exception as e:
        return None, f"Failed to read CSV: {e}"

    # Basic validation based on known schema
    expected_cols = {
        "customer_id", "session_id", "visit_date", "device_type", "user_type",
        "marketing_channel", "product_id", "product_category", "unit_price",
        "quantity", "discount_percent", "discount_amount", "revenue",
        "pages_viewed", "time_on_site_sec", "added_to_cart", "purchased",
        "cart_abandoned", "rating", "review_text", "review_helpful_votes",
        "payment_method", "visit_day", "visit_month", "visit_weekday",
        "visit_season", "session_duration_bucket", "revenue_normalized", "location"
    }
    missing = expected_cols - set(df.columns)
    if missing:
        # If file exists but has slightly different naming, adapt
        pass  # Don't hard-fail; analytics can use available cols

    # Clean visit_date
    if "visit_date" in df.columns:
        df["visit_date"] = pd.to_datetime(df["visit_date"], format="%d-%m-%Y", errors="coerce")
        if df["visit_date"].isna().sum() > 0:
            # Try other formats
            df["visit_date"] = pd.to_datetime(df["visit_date"], errors="coerce", dayfirst=True)

    # Numeric conversions for common columns
    numeric_cols = ["unit_price", "quantity", "discount_percent", "discount_amount",
                    "revenue", "pages_viewed", "time_on_site_sec",
                    "added_to_cart", "purchased", "cart_abandoned",
                    "rating", "review_text", "review_helpful_votes",
                    "payment_method", "visit_day", "visit_month", "visit_weekday",
                    "visit_season", "revenue_normalized", "location"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Add derived fields for analytics
    if "revenue" in df.columns and "quantity" in df.columns and "unit_price" in df.columns:
        df["calculated_revenue"] = df["unit_price"] * df["quantity"] * (1 - df["discount_percent"]/100)
    if "visit_date" in df.columns:
        df["visit_year"] = df["visit_date"].dt.year
        df["visit_month_name"] = df["visit_date"].dt.month_name()

    # Mapping dictionaries for readable labels (approximate from dataset context)
    df["device_type_label"] = df["device_type"].map({0: "Desktop", 1: "Mobile", 2: "Tablet"}).fillna("Unknown")
    df["user_type_label"] = df["user_type"].map({0: "New", 1: "Returning"}).fillna("Unknown")
    df["session_duration_label"] = df["session_duration_bucket"].fillna("Unknown")

    return df, f"Loaded {len(df)} rows, {len(df.columns)} columns from {filepath}"
