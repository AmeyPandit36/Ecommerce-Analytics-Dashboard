"""Global filter bar: query-string <-> parameterised SQL. No user input is ever
concatenated into SQL, and every option shown in the UI is read back from the
dataset itself (so a filter can never offer a value that does not exist)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from core.store import Store  # noqa: F401  (type hints / shared module surface)


@dataclass(frozen=True)
class FilterSpec:
    key: str
    column: str
    label: str
    kind: str = "int"            # int | text | date | outcome | segment | discount | price
    op: str = "="
    label_col: str = ""          # human-readable companion column in `sessions`
    icon: str = "filter"
    hint: str = ""


SPECS: tuple[FilterSpec, ...] = (
    # Date range
    FilterSpec("from", "visit_date", "From", "date", ">=", icon="calendar",
               hint="visit_date (parsed from the dataset's DD-MM-YYYY format)"),
    FilterSpec("to", "visit_date", "To", "date", "<=", icon="calendar",
               hint="visit_date"),
    # Core analytical slicers (priority order)
    FilterSpec("cat", "product_category", "Category", "int", "=", label_col="category_label",
               icon="tags", hint="product_category"),
    FilterSpec("seg", "segment", "Customer segment", "segment", "=", icon="users",
               hint="Pareto lifetime-revenue segment"),
    FilterSpec("utype", "user_type", "User type", "int", "=", label_col="user_type_label",
               icon="user", hint="user_type"),
    FilterSpec("dbucket", "discount_bucket", "Discount bucket", "discount", "=", icon="percent",
               hint="grouped discount depth"),
    FilterSpec("pband", "price_band", "Price band", "price", "=", icon="tags",
               hint="grouped unit price"),
    FilterSpec("pay", "payment_method", "Payment method", "int", "=", label_col="payment_label",
               icon="credit-card", hint="payment_method"),
    # Secondary dimensions
    FilterSpec("month", "visit_month", "Month", "int", "=", label_col="month_name", icon="calendar"),
    FilterSpec("bucket", "duration_bucket", "Session length", "text", "=",
               icon="clock", hint="session_duration_bucket"),
    FilterSpec("dev", "device_type", "Device", "int", "=", label_col="device_label",
               icon="mobile", hint="device_type"),
    FilterSpec("chan", "marketing_channel", "Channel", "int", "=", label_col="channel_label",
               icon="bullhorn", hint="marketing_channel"),
    FilterSpec("loc", "location", "Location", "int", "=", label_col="location_label",
               icon="location", hint="location"),
    FilterSpec("purch", "purchased", "Outcome", "outcome", "=", icon="cart"),
)

SPEC_BY_KEY = {s.key: s for s in SPECS}
OUTCOME_LABELS = {"1": "Purchased", "0": "Browsed, no purchase"}

SEGMENT_VALUES = {"high": "High value", "mid": "Mid value", "core": "Core value",
                  "window": "Window shoppers"}

# (key, label, sql-expression) — same bucketing as analytics/common.py DIMENSIONS.
DISCOUNT_BUCKETS = (
    ("0", "0% (no discount)", "discount_percent = 0"),
    ("1", "5–10%", "discount_percent > 0 AND discount_percent <= 10"),
    ("2", "11–20%", "discount_percent > 10 AND discount_percent <= 20"),
    ("3", "21–30%", "discount_percent > 20 AND discount_percent <= 30"),
)
PRICE_BANDS = (
    ("0", "≤ ₹500", "unit_price <= 500"),
    ("1", "₹501–1,000", "unit_price > 500 AND unit_price <= 1000"),
    ("2", "₹1,001–1,500", "unit_price > 1000 AND unit_price <= 1500"),
    ("3", "₹1,501–2,000", "unit_price > 1500 AND unit_price <= 2000"),
)


def normalise(value) -> str:
    return str(value).strip() if value is not None else ""


def coerce(spec: FilterSpec, raw: str):
    """Validate + coerce a raw query-string value. Returns None when unusable."""
    if not raw:
        return None
    if spec.kind in ("int", "outcome"):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None
    if spec.kind == "date":
        text = raw.replace("/", "-")
        parts = text.split("-")
        if len(parts) != 3:
            return None
        try:
            a, b, c = (int(p) for p in parts)
        except ValueError:
            return None
        if len(str(a)) == 4:                      # yyyy-mm-dd
            year, month, day = a, b, c
        else:                                     # dd-mm-yyyy (dataset format)
            day, month, year = a, b, c
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2100):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    return raw[:64]                               # free text (whitelisted against data)


def _segment_cutoffs(store: Store) -> dict[str, int]:
    """Exact Pareto band boundaries (matching analytics/report.segment_data).

    High = top 20% of buyers, Mid = next 30%, Core = remaining 50%, by lifetime
    revenue. Counts are ceil'd in Python so they match the report exactly.
    """
    buyers = store.scalar(
        "SELECT COUNT(*) FROM (SELECT customer_id FROM sessions "
        "WHERE purchased = 1 GROUP BY customer_id HAVING SUM(revenue) > 0)", (), 0) or 0
    if not buyers:
        return {}
    high = max(1, math.ceil(buyers * 0.2))
    mid = max(1, math.ceil(buyers * 0.3))
    return {"high": high, "mid": mid, "core_end": high + mid}


def _segment_sql(band: str, cutoffs: dict[str, int]) -> str:
    """customer_id IN (...) predicate for a Pareto segment band (fixed, safe SQL)."""
    if band == "window":
        return "customer_id NOT IN (SELECT customer_id FROM sessions WHERE purchased = 1)"
    ranked = ("(SELECT customer_id, SUM(revenue) AS r FROM sessions WHERE purchased = 1 "
              "GROUP BY customer_id HAVING SUM(revenue) > 0 ORDER BY r DESC)")
    if band == "high":
        return f"customer_id IN (SELECT customer_id FROM {ranked} LIMIT {cutoffs['high']})"
    if band == "mid":
        return (f"customer_id IN (SELECT customer_id FROM {ranked} "
                f"LIMIT {cutoffs['mid']} OFFSET {cutoffs['high']})")
    if band == "core":
        return (f"customer_id IN (SELECT customer_id FROM {ranked} "
                f"LIMIT -1 OFFSET {cutoffs['core_end']})")
    return None


def _special_clause(spec: FilterSpec, value, store: Store | None) -> str | None:
    """Parameterless predicate for derived filters (segment / discount bucket / price band)."""
    if spec.kind == "segment":
        if store is None:
            return None
        cutoffs = _segment_cutoffs(store)
        if not cutoffs:
            return None
        return _segment_sql(str(value), cutoffs)
    if spec.kind == "discount":
        for key, _label, expr in DISCOUNT_BUCKETS:
            if str(key) == str(value):
                return f"({expr})"
        return None
    if spec.kind == "price":
        for key, _label, expr in PRICE_BANDS:
            if str(key) == str(value):
                return f"({expr})"
        return None
    return None


def build_where(args: dict, store: Store | None = None) -> tuple[str, tuple, list[dict]]:
    """Return (sql fragment, bound params, active-filter chips)."""
    clauses: list[str] = []
    params: list = []
    active: list[dict] = []
    for spec in SPECS:
        raw = normalise(args.get(spec.key))
        value = coerce(spec, raw)
        if value is None:
            continue
        if spec.kind in ("segment", "discount", "price"):
            clause = _special_clause(spec, value, store)
            if clause:
                clauses.append(f"AND {clause}")
                active.append({"key": spec.key, "label": spec.label, "raw": raw,
                               "display": display_value(spec, raw, store)})
            continue
        if spec.kind == "text" and store is not None:
            allowed = [str(o["value"]) for o in store.distinct(spec.column)]
            if allowed and str(value) not in allowed:
                continue
        params.append(value)
        clauses.append(f"AND {spec.column} {spec.op} ?")
        active.append({"key": spec.key, "label": spec.label, "raw": raw,
                       "display": display_value(spec, raw, store)})
    return (" ".join(clauses), tuple(params), active)


def display_value(spec: FilterSpec, raw: str, store: Store | None) -> str:
    if spec.kind == "outcome":
        return OUTCOME_LABELS.get(raw, raw)
    if spec.kind == "date":
        return raw
    if spec.kind == "segment":
        return SEGMENT_VALUES.get(raw, raw)
    if spec.kind == "discount":
        for key, label, _expr in DISCOUNT_BUCKETS:
            if str(key) == str(raw):
                return label
        return raw
    if spec.kind == "price":
        for key, label, _expr in PRICE_BANDS:
            if str(key) == str(raw):
                return label
        return raw
    if spec.kind == "int" and store is not None and raw.lstrip("-").isdigit():
        for option in store.distinct(spec.column, spec.label_col or None):
            if str(option["value"]) == str(int(float(raw))):
                return option["label"]
        return f"{spec.label} {raw}"
    return raw


def ui_specs() -> list[dict]:
    """Control metadata so the filter bar is generated from the same spec list the
    SQL builder uses - a filter can never appear in the UI that the engine ignores."""
    return [{"key": s.key, "label": s.label, "kind": s.kind, "icon": s.icon, "hint": s.hint}
            for s in SPECS]


def options(store: Store) -> dict[str, list[dict]]:
    """Filter-bar options, built from the real distinct values in the dataset."""
    out: dict[str, list[dict]] = {}
    for spec in SPECS:
        if spec.kind == "outcome":
            out[spec.key] = [{"value": k, "label": v, "n": None} for k, v in OUTCOME_LABELS.items()]
            continue
        if spec.kind == "date":
            continue
        if spec.kind == "segment":
            out[spec.key] = [{"value": k, "label": v, "n": None} for k, v in SEGMENT_VALUES.items()]
            continue
        if spec.kind == "discount":
            out[spec.key] = [{"value": k, "label": label, "n": None} for k, label, _e in DISCOUNT_BUCKETS]
            continue
        if spec.kind == "price":
            out[spec.key] = [{"value": k, "label": label, "n": None} for k, label, _e in PRICE_BANDS]
            continue
        out[spec.key] = store.distinct(spec.column, spec.label_col or None)
    return out


def query_string(args: dict, **overrides) -> str:
    """Rebuild a query string from current args + overrides (for links/pagination)."""
    from urllib.parse import urlencode

    merged = {k: normalise(v) for k, v in args.items() if normalise(v) and k in SPEC_BY_KEY}
    for key, value in overrides.items():
        value = normalise(value)
        if value:
            merged[key] = value
        else:
            merged.pop(key, None)
    return urlencode(merged)


def keep_filter_args(args: dict) -> dict:
    """Only the recognised filter keys, sanitised + normalised - safe to echo into
    templates (dates come back as ISO so <input type=date> can display them)."""
    out = {}
    for spec in SPECS:
        raw = normalise(args.get(spec.key))
        if not raw:
            continue
        value = coerce(spec, raw)
        if value is None:
            continue
        out[spec.key] = str(value) if spec.kind != "date" else value
        if spec.kind == "date":
            out[spec.key] = value
    return out
