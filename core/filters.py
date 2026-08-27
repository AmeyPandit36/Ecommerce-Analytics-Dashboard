"""Global filter bar: query-string <-> parameterised SQL. No user input is ever
concatenated into SQL, and every option shown in the UI is read back from the
dataset itself (so a filter can never offer a value that does not exist)."""
from __future__ import annotations

from dataclasses import dataclass

from core.store import Store  # noqa: F401  (type hints / shared module surface)


@dataclass(frozen=True)
class FilterSpec:
    key: str
    column: str
    label: str
    kind: str = "int"            # int | text | date | outcome
    op: str = "="
    label_col: str = ""          # human-readable companion column in `sessions`
    icon: str = "filter"
    hint: str = ""


SPECS: tuple[FilterSpec, ...] = (
    FilterSpec("from", "visit_date", "From", "date", ">=", icon="calendar",
               hint="visit_date (parsed from the dataset's DD-MM-YYYY format)"),
    FilterSpec("to", "visit_date", "To", "date", "<=", icon="calendar",
               hint="visit_date"),
    FilterSpec("month", "visit_month", "Month", "int", "=", label_col="month_name", icon="calendar"),
    FilterSpec("cat", "product_category", "Category", "int", "=", label_col="category_label",
               icon="tags", hint="product_category"),
    FilterSpec("pay", "payment_method", "Payment method", "int", "=", label_col="payment_label",
               icon="credit-card", hint="payment_method"),
    FilterSpec("dev", "device_type", "Device", "int", "=", label_col="device_label",
               icon="mobile", hint="device_type"),
    FilterSpec("utype", "user_type", "User type", "int", "=", label_col="user_type_label",
               icon="user", hint="user_type"),
    FilterSpec("chan", "marketing_channel", "Channel", "int", "=", label_col="channel_label",
               icon="bullhorn", hint="marketing_channel"),
    FilterSpec("loc", "location", "Location", "int", "=", label_col="location_label",
               icon="location", hint="location"),
    FilterSpec("bucket", "duration_bucket", "Session length", "text", "=",
               icon="clock", hint="session_duration_bucket"),
    FilterSpec("purch", "purchased", "Outcome", "outcome", "=", icon="cart"),
    FilterSpec("rmin", "rating", "Min rating", "int", ">=", icon="star",
               hint="rating, on all sessions"),
    FilterSpec("dmin", "discount_percent", "Min discount %", "int", ">=", icon="percent"),
    FilterSpec("dmax", "discount_percent", "Max discount %", "int", "<=", icon="percent"),
)

SPEC_BY_KEY = {s.key: s for s in SPECS}
OUTCOME_LABELS = {"1": "Purchased", "0": "Browsed, no purchase"}


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
    if spec.kind == "int" and store is not None and raw.lstrip("-").isdigit():
        for option in store.distinct(spec.column, spec.label_col or None):
            if str(option["value"]) == str(int(float(raw))):
                return option["label"]
        return f"{spec.label} {raw}"
    return raw


# Small numeric filters get fixed step lists that match the real data ranges
# (rating 1-5, discount_percent 0-30 in steps of 5 - both verified from the CSV).
PRESETS = {
    "rmin": [{"value": str(v), "label": f"{v} ★ & up", "n": None} for v in (5, 4, 3, 2, 1)],
    "dmin": [{"value": str(v), "label": f"{v}% & up", "n": None} for v in (0, 5, 10, 15, 20, 25, 30)],
    "dmax": [{"value": str(v), "label": f"up to {v}%", "n": None} for v in (0, 5, 10, 15, 20, 25, 30)],
}


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
        if spec.key in PRESETS:
            out[spec.key] = PRESETS[spec.key]
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
