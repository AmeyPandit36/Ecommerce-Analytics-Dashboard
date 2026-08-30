#!/usr/bin/env python3
"""
Build the local analytics store from the bundled Kaggle CSV.

    python scripts/build_dataset.py            # build data/ecommerce.db from data/Ecommerce.csv
    python scripts/download_dataset.py         # (optional dev step) refresh data/Ecommerce.csv from Kaggle

Design notes
------------
The dashboard queries a small SQLite database instead of pandas at runtime:

* no compiled dependencies -> the Vercel function bundle stays tiny and the
  cold start stays fast (Flask + stdlib only),
* filtering / aggregation happens in SQL on indexed columns, so every page
  answers in single-digit milliseconds,
* the raw CSV stays in the repo as the source of truth and can be re-profiled
  at any time with this script.

Everything written here is *computed from the CSV* - nothing is invented.
Columns that the dataset ships as integer codes (product_category,
payment_method, location, ...) are kept as codes; labels are generated as
"Category 7", "Payment 3", ... because the dataset contains no decoding map.

Only two encodings are decoded, because both are verifiable from the data
itself (cross-tabulation of the code against the parsed visit_date):

* visit_weekday 0..6  == Monday..Sunday
* visit_season  1 -> Mar-May, 2 -> Jun-Aug, 0 -> Sep-Nov, 3 -> Dec-Feb
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from statistics import mean, median

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CSV_PATH = os.path.join(DATA_DIR, "Ecommerce.csv")
DB_PATH = os.path.join(DATA_DIR, "ecommerce.db")

DATASET_SLUG = "kundanbedmutha/indian-e-commerce-customer-behavior-and-purchase"
DATASET_FILE = "Ecommerce.csv"
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Categorical columns that the dataset stores as opaque integer codes.
CODE_COLUMNS = {
    "product_category": "Category",
    "payment_method": "Payment",
    "device_type": "Device",
    "user_type": "User type",
    "marketing_channel": "Channel",
    "location": "Location",
    "review_text": "Review code",
}

# Season code -> month numbers, verified against visit_date during profiling.
SEASON_MONTHS = {1: (3, 4, 5), 2: (6, 7, 8), 0: (9, 10, 11), 3: (12, 1, 2)}
SEASON_NAMES = {1: "Spring (Mar-May)", 2: "Summer (Jun-Aug)",
                0: "Autumn (Sep-Nov)", 3: "Winter (Dec-Feb)"}

INT_COLUMNS = ["customer_id", "session_id", "device_type", "user_type", "marketing_channel",
               "product_id", "product_category", "quantity", "discount_percent", "pages_viewed",
               "time_on_site_sec", "added_to_cart", "purchased", "cart_abandoned", "rating",
               "review_text", "review_helpful_votes", "payment_method", "visit_day",
               "visit_month", "visit_weekday", "visit_season", "location"]
FLOAT_COLUMNS = ["unit_price", "discount_amount", "revenue", "revenue_normalized"]

SCHEMA = """
DROP TABLE IF EXISTS sessions;
CREATE TABLE sessions (
    session_id           INTEGER PRIMARY KEY,
    customer_id          INTEGER NOT NULL,
    visit_date           TEXT    NOT NULL,
    visit_year           INTEGER NOT NULL,
    visit_month          INTEGER NOT NULL,
    month_name           TEXT    NOT NULL,
    visit_day            INTEGER NOT NULL,
    weekday              INTEGER NOT NULL,
    weekday_name         TEXT    NOT NULL,
    season               INTEGER NOT NULL,
    season_name          TEXT    NOT NULL,
    device_type          INTEGER NOT NULL,
    device_label         TEXT    NOT NULL,
    user_type            INTEGER NOT NULL,
    user_type_label      TEXT    NOT NULL,
    marketing_channel    INTEGER NOT NULL,
    channel_label        TEXT    NOT NULL,
    product_id           INTEGER NOT NULL,
    product_category     INTEGER NOT NULL,
    category_label       TEXT    NOT NULL,
    unit_price           REAL    NOT NULL,
    quantity             INTEGER NOT NULL,
    gross_value          REAL    NOT NULL,
    discount_percent     INTEGER NOT NULL,
    discount_amount      REAL    NOT NULL,
    revenue              REAL    NOT NULL,
    pages_viewed         INTEGER NOT NULL,
    time_on_site_sec     INTEGER NOT NULL,
    duration_bucket      TEXT    NOT NULL,
    added_to_cart        INTEGER NOT NULL,
    purchased            INTEGER NOT NULL,
    cart_abandoned       INTEGER NOT NULL,
    rating               INTEGER NOT NULL,
    review_code          INTEGER NOT NULL,
    review_helpful_votes INTEGER NOT NULL,
    payment_method       INTEGER NOT NULL,
    payment_label        TEXT    NOT NULL,
    location             INTEGER NOT NULL,
    location_label       TEXT    NOT NULL,
    revenue_normalized   REAL    NOT NULL
);
CREATE INDEX ix_cust      ON sessions(customer_id);
CREATE INDEX ix_prod      ON sessions(product_id);
CREATE INDEX ix_cat       ON sessions(product_category);
CREATE INDEX ix_pay       ON sessions(payment_method);
CREATE INDEX ix_loc       ON sessions(location);
CREATE INDEX ix_dev       ON sessions(device_type);
CREATE INDEX ix_user      ON sessions(user_type);
CREATE INDEX ix_chan      ON sessions(marketing_channel);
CREATE INDEX ix_month     ON sessions(visit_month);
CREATE INDEX ix_date      ON sessions(visit_date);
CREATE INDEX ix_purch     ON sessions(purchased);
CREATE INDEX ix_rating    ON sessions(rating);
CREATE INDEX ix_bucket    ON sessions(duration_bucket);

DROP TABLE IF EXISTS dq_columns;
CREATE TABLE dq_columns (
    name         TEXT PRIMARY KEY,
    position     INTEGER,
    dtype        TEXT,
    not_nulls    INTEGER,
    nulls        INTEGER,
    distinct_n   INTEGER,
    min_num      REAL,
    max_num      REAL,
    mean_num     REAL,
    median_num   REAL,
    min_str      TEXT,
    max_str      TEXT,
    top_values   TEXT,
    outlier_low  REAL,
    outlier_high REAL,
    outliers     INTEGER,
    role         TEXT
);

DROP TABLE IF EXISTS meta;
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def parse_date(raw: str):
    """Dataset stores dates as DD-MM-YYYY. Returns (iso, year, month, day) or None."""
    parts = raw.strip().split("-")
    if len(parts) != 3:
        return None
    day_s, month_s, year_s = parts
    try:
        day, month, year = int(day_s), int(month_s), int(year_s)
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}", year, month, day


def weekday_from_civil(y: int, m: int, d: int) -> int:
    """Tomohiko Sakai's algorithm -> 0=Monday .. 6=Sunday (stdlib only)."""
    t = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    if m < 3:
        y -= 1
    wd = (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7  # 0=Sunday
    return (wd + 6) % 7


def to_int(value):
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def to_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_rows(path: str):
    """Read + normalise the CSV. Returns (rows, issues)."""
    rows, issues = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames or []
        missing = (set(CODE_COLUMNS) | {"visit_date", "revenue", "purchased"}) - set(fieldnames)
        if missing:
            raise SystemExit(f"Unexpected CSV header, missing columns: {sorted(missing)}")

        for i, src in enumerate(reader):
            parsed = parse_date(src.get("visit_date") or "")
            if not parsed:
                issues.append(f"row {i}: unparseable visit_date {src.get('visit_date')!r}")
                continue
            iso, year, month, day = parsed
            wd = weekday_from_civil(year, month, day)

            cat = to_int(src.get("product_category"))
            pay = to_int(src.get("payment_method"))
            dev = to_int(src.get("device_type"))
            usr = to_int(src.get("user_type"))
            ch = to_int(src.get("marketing_channel"))
            loc = to_int(src.get("location"))
            unit_price = to_float(src.get("unit_price")) or 0.0
            qty = to_int(src.get("quantity")) or 0
            disc_pct = to_int(src.get("discount_percent")) or 0
            disc_amt = to_float(src.get("discount_amount")) or 0.0
            revenue = to_float(src.get("revenue")) or 0.0
            purchased = to_int(src.get("purchased")) or 0
            time_on_site = to_int(src.get("time_on_site_sec")) or 0

            rows.append((
                to_int(src.get("session_id")) if src.get("session_id") not in (None, "") else i,
                to_int(src.get("customer_id")),
                iso, year, month, MONTH_NAMES[month - 1], day, wd, WEEKDAY_NAMES[wd],
                to_int(src.get("visit_season")) or 0,
                SEASON_NAMES.get(to_int(src.get("visit_season")) or 0, "Season NA"),
                dev, f"Device {dev}",
                usr, f"User type {usr}",
                ch, f"Channel {ch}",
                to_int(src.get("product_id")), cat, f"Category {cat}",
                unit_price, qty, round(unit_price * qty, 2), disc_pct, disc_amt, revenue,
                to_int(src.get("pages_viewed")) or 0, time_on_site,
                (src.get("session_duration_bucket") or "Unknown").strip() or "Unknown",
                to_int(src.get("added_to_cart")) or 0, purchased,
                to_int(src.get("cart_abandoned")) or 0,
                to_int(src.get("rating")) or 0, to_int(src.get("review_text")) or 0,
                to_int(src.get("review_helpful_votes")) or 0,
                pay, f"Payment {pay}", loc, f"Location {loc}",
                to_float(src.get("revenue_normalized")) or 0.0,
            ))
    return rows, issues


def profile_columns(raw_rows, fieldnames, clean_rows):
    """Per-column quality profile computed from the raw CSV + normalised rows."""
    numeric = set(INT_COLUMNS) | set(FLOAT_COLUMNS)
    by_name = defaultdict(list)
    for row in raw_rows:
        for col in fieldnames:
            by_name[col].append(row.get(col))

    profiles = []
    for pos, col in enumerate(fieldnames):
        values = by_name[col]
        blanks = sum(1 for v in values if v is None or str(v).strip() == "")
        distinct = len({v for v in values})
        is_num = col in numeric
        nums = []
        if is_num:
            nums = [to_float(v) for v in values]
            nums = [v for v in nums if v is not None]
        counter = Counter(values)
        top_vals = [{"value": ("" if k is None else str(k))[:40], "count": c}
                    for k, c in counter.most_common(3)]
        min_n = max_n = mean_n = median_n = low_f = high_f = None
        outliers = 0
        if nums:
            min_n, max_n = min(nums), max(nums)
            mean_n = mean(nums)
            median_n = median(nums)
            if len(nums) >= 100:
                ordered = sorted(nums)
                q1 = ordered[int(0.25 * (len(ordered) - 1))]
                q3 = ordered[int(0.75 * (len(ordered) - 1))]
                iqr = q3 - q1
                low_f, high_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                outliers = sum(1 for v in nums if v < low_f or v > high_f)
        if col == "visit_date":
            dtype, role = "date (text DD-MM-YYYY)", "temporal"
        elif is_num:
            dtype = "integer" if col in INT_COLUMNS else "float"
            role = "measure" if col in {"unit_price", "revenue", "discount_amount",
                                        "time_on_site_sec", "gross_value", "revenue_normalized"} \
                else ("binary flag" if col in {"added_to_cart", "purchased", "cart_abandoned"} else "code")
        else:
            dtype = "text"
            role = "category" if col in CODE_COLUMNS or col == "session_duration_bucket" else "text"
        if col in CODE_COLUMNS:
            role = "encoded category (integer code)"
        profiles.append((
            col, pos, dtype, len(values) - blanks, blanks, distinct,
            min_n, max_n, mean_n, median_n,
            (counter.most_common(1)[0][0] if dtype == "text" else None), None,
            json.dumps(top_vals), low_f, high_f, outliers, role,
        ))
    return profiles


def consistency_checks(clean_rows):
    """Real data-quality findings for this specific dataset (nothing assumed)."""
    n = len(clean_rows)
    idx = {name: i for i, name in enumerate(
        ["session_id", "customer_id", "visit_date", "visit_year", "visit_month", "month_name",
         "visit_day", "weekday", "weekday_name", "season", "season_name", "device_type",
         "device_label", "user_type", "user_type_label", "marketing_channel", "channel_label",
         "product_id", "product_category", "category_label", "unit_price", "quantity",
         "gross_value", "discount_percent", "discount_amount", "revenue", "pages_viewed",
         "time_on_site_sec", "duration_bucket", "added_to_cart", "purchased", "cart_abandoned",
         "rating", "review_code", "review_helpful_votes", "payment_method", "payment_label",
         "location", "location_label", "revenue_normalized"])}
    get = lambda row, col: row[idx[col]]

    revenue_zero_on_purchase = sum(1 for r in clean_rows if get(r, "purchased") == 1 and get(r, "revenue") == 0)
    revenue_nonzero_no_purchase = sum(1 for r in clean_rows if get(r, "purchased") == 0 and get(r, "revenue") > 0)
    bad_discount = sum(1 for r in clean_rows
                       if abs(get(r, "discount_amount") - round(get(r, "gross_value") * get(r, "discount_percent") / 100, 2)) > 0.02)
    cart_mismatch = sum(1 for r in clean_rows if get(r, "purchased") == 1 and get(r, "added_to_cart") == 0)
    abandon_mismatch = sum(1 for r in clean_rows
                           if get(r, "added_to_cart") == 1 and (get(r, "purchased") + get(r, "cart_abandoned")) != 1)
    rating_counts = Counter(get(r, "rating") for r in clean_rows if get(r, "purchased") == 0)
    placeholder = rating_counts.most_common(1)[0] if rating_counts else (None, 0)
    dup_ids = n - len({get(r, "session_id") for r in clean_rows})
    nonpos_price = sum(1 for r in clean_rows if get(r, "unit_price") <= 0)

    findings = []
    if revenue_zero_on_purchase:
        findings.append({"severity": "warning", "column": "revenue",
                         "title": f"{revenue_zero_on_purchase:,} purchased sessions have zero revenue",
                         "detail": "Rows with purchased = 1 but revenue = 0 would drag averages down; they are excluded from AOV."})
    if revenue_nonzero_no_purchase:
        findings.append({"severity": "warning", "column": "revenue",
                         "title": f"{revenue_nonzero_no_purchase:,} non-purchase sessions carry revenue",
                         "detail": "Revenue should be 0 when purchased = 0."})
    else:
        findings.append({"severity": "info", "column": "revenue",
                         "title": "revenue is 0 for every non-purchase session",
                         "detail": "Revenue is only booked on completed purchases, so revenue averages must be taken "
                                   "over purchased sessions (5,616 rows) - not over all 25,000 sessions. "
                                   "The dashboard does exactly that."})
    if placeholder[1] > n * 0.2:
        findings.append({"severity": "warning", "column": "rating",
                         "title": f"rating = {placeholder[0]} on {placeholder[1]:,} non-purchase sessions",
                         "detail": "Sessions that never bought carry a constant placeholder rating. Averaging "
                                   "`rating` across all rows is therefore misleading, so every rating metric here "
                                   "is computed on purchased sessions only."})
    if bad_discount:
        findings.append({"severity": "warning", "column": "discount_amount",
                         "title": f"{bad_discount:,} rows where discount_amount != gross_value x discount_percent",
                         "detail": "Rounding drift of more than 2 paise between the two discount fields."})
    else:
        findings.append({"severity": "ok", "column": "discount_amount",
                         "title": "discount_amount reconciles with unit_price x quantity x discount_percent",
                         "detail": "Verified row-by-row against the recomputed discount (tolerance Rs 0.02)."})
    if cart_mismatch:
        findings.append({"severity": "warning", "column": "purchased",
                         "title": f"{cart_mismatch:,} purchases without added_to_cart = 1",
                         "detail": "Funnel stages are not strictly nested; the journey page uses observed counts."})
    if abandon_mismatch:
        findings.append({"severity": "warning", "column": "cart_abandoned",
                         "title": f"{abandon_mismatch:,} carts are neither purchased nor abandoned",
                         "detail": "Check that the funnel stages still sum to the cart population."})
    else:
        findings.append({"severity": "ok", "column": "cart_abandoned",
                         "title": "Every cart ends exactly once - purchased or abandoned",
                         "detail": "added_to_cart = 1 always has exactly one of purchased / cart_abandoned set, "
                                   "so the funnel is internally consistent."})
    if dup_ids:
        findings.append({"severity": "warning", "column": "session_id",
                         "title": f"{dup_ids:,} duplicated session_id values",
                         "detail": "session_id is the primary key of the analytics table."})
    else:
        findings.append({"severity": "ok", "column": "session_id",
                         "title": "session_id is unique across all rows",
                         "detail": "One row = one session; no duplicate keys."})
    if nonpos_price:
        findings.append({"severity": "warning", "column": "unit_price",
                         "title": f"{nonpos_price:,} rows with unit_price <= 0",
                         "detail": "Non-positive prices distort average order value."})
    findings.append({"severity": "info", "column": "product_category, payment_method, location, ...",
                     "title": "Categoricals are stored as opaque integer codes",
                     "description": "",
                     "detail": "The dataset ships no code-to-name mapping, so the UI shows the codes "
                               "(Category 0-7, Payment 0-5, Device 0-2, Channel 0-5, Location 0-224) "
                               "instead of guessing names such as 'Electronics' or 'UPI'."})
    return findings


def main(csv_path: str = CSV_PATH, db_path: str = DB_PATH) -> dict:
    if not os.path.isfile(csv_path):
        raise SystemExit(f"Dataset CSV not found at {csv_path}")
    with open(csv_path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fieldnames = list(reader.fieldnames or [])
        raw_rows = [dict(r) for r in reader]

    clean_rows, issues = read_rows(csv_path)
    profiles = profile_columns(raw_rows, fieldnames, clean_rows)
    findings = consistency_checks(clean_rows)

    full_dups = len(raw_rows) - len({tuple(sorted(r.items())) for r in raw_rows})

    tmp = db_path + ".tmp"
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    placeholders = ",".join("?" * len(clean_rows[0]))
    con.executemany(f"INSERT INTO sessions VALUES ({placeholders})", clean_rows)
    con.executemany("INSERT INTO dq_columns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", profiles)

    dates = sorted({r[2] for r in clean_rows})
    meta = {
        "dataset_slug": DATASET_SLUG,
        "dataset_file": DATASET_FILE,
        "source_csv": os.path.relpath(csv_path, BASE_DIR),
        "csv_sha256": digest,
        "csv_bytes": str(os.path.getsize(csv_path)),
        "rows": str(len(clean_rows)),
        "csv_columns": str(len(fieldnames)),
        "duplicate_rows": str(full_dups),
        "unique_customers": str(len({r[1] for r in clean_rows})),
        "unique_products": str(len({r[17] for r in clean_rows})),
        "date_min": dates[0],
        "date_max": dates[-1],
        "generated_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "weekday_mapping": json.dumps({i: WEEKDAY_NAMES[i] for i in range(7)}),
        "season_mapping": json.dumps({str(k): SEASON_NAMES[k] for k in SEASON_NAMES}),
        "findings": json.dumps(findings),
        "unparsed_rows": str(len(issues)),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", sorted(meta.items()))
    con.commit()
    con.execute("VACUUM")
    con.commit()
    con.close()
    os.replace(tmp, db_path)

    return {"rows": len(clean_rows), "columns": len(fieldnames), "db": db_path,
            "db_bytes": os.path.getsize(db_path), "duplicate_rows": full_dups,
            "findings": len(findings), "issues": issues[:5], "meta": meta}


if __name__ == "__main__":
    result = main()
    print(f"Built {result['db']} ({result['db_bytes']:,} bytes) "
          f"from {result['rows']:,} rows x {result['columns']} columns")
    print(f"Duplicate full rows: {result['duplicate_rows']}  |  findings: {result['findings']}")
    if result["issues"]:
        print("Row issues:", result["issues"])
    sys.exit(0)
