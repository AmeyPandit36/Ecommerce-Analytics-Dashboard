"""Formatting helpers shared by the analytics layer and templates."""
from __future__ import annotations

import math

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _group_indian(digits: str) -> str:
    """1234567 -> 12,34,567 (last group of 3, then pairs)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def _group_west(digits: str) -> str:
    out, count = [], 0
    for ch in reversed(digits):
        out.append(ch)
        count += 1
        if count % 3 == 0 and count != len(digits):
            out.append(",")
    return "".join(reversed(out))


def number(value, digits: int = 0, style: str = "indian") -> str:
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(value):
        return "n/a"
    neg = "-" if value < 0 else ""
    body = f"{abs(value):.{digits}f}"
    if "." in body:
        whole, frac = body.split(".")
    else:
        whole, frac = body, ""
    grouped = _group_indian(whole) if style == "indian" else _group_west(whole)
    if digits:
        return f"{neg}{grouped}.{frac}"
    return f"{neg}{grouped}"


def inr(value, digits: int = 0) -> str:
    """Rupee value with Indian digit grouping: Rs 1,01,16,169.00"""
    if value is None:
        return "n/a"
    return "₹" + number(value, digits)


def inr_m(value) -> str:
    """Compact Western million: ₹10.12M. Used for headline revenue KPIs."""
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"₹{value / 1e6:.2f}M"


def inr_short(value) -> str:
    """Compact currency: ₹2.04M for millions, ₹1,801 for thousands, ₹837.83 for small."""
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e6:
        return f"{sign}₹{v / 1e6:.2f}M"
    if v >= 1000:
        return f"{sign}₹{number(v)}"
    return f"{sign}₹{v:,.2f}"


def compact(value, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e7:
        return f"{sign}{v / 1e7:.{digits}f}Cr"
    if v >= 1e5:
        return f"{sign}{v / 1e5:.{digits}f}L"
    if v >= 1000:
        return f"{sign}{v / 1000:.{digits}f}k"
    return f"{sign}{v:.0f}"


def pct(value, digits: int = 1, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    arrow = ""
    if signed:
        arrow = "▲ " if value > 0 else ("▼ " if value < 0 else "")
        return f"{arrow}{abs(value):.{digits}f}%"
    return f"{value:.{digits}f}%"


def date_label(iso: str) -> str:
    try:
        year, month, day = iso.split("-")
        return f"{int(day)} {MONTHS[int(month) - 1]} {year}"
    except Exception:
        return str(iso)


def seconds_to_mmss(value) -> str:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{value // 60}m {value % 60:02d}s"


def clean(value, digits: int = 2):
    """Round for JSON payloads without turning None into 0 (keeps n/a honest)."""
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
