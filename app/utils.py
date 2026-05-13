from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta


NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    compact = NON_ALNUM_RE.sub(" ", ascii_only.upper()).strip()
    return re.sub(r"\s+", " ", compact)


def normalize_header(value: str) -> str:
    return normalize_text(value).lower().replace(" ", "_")


def parse_hhmm(value: str | None) -> time | None:
    if not value:
        return None
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (ValueError, AttributeError):
        return None
    if hour == 24 and minute == 0:
        return time(0, 0)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return time(hour, minute)


def parse_datetime_from_strings(day: str, hhmm: str | None) -> datetime | None:
    try:
        parsed_day = date.fromisoformat(day)
    except ValueError:
        return None
    parsed_time = parse_hhmm(hhmm)
    if parsed_time is None:
        return None
    return datetime.combine(parsed_day, parsed_time)


def parse_gtfs_time_to_minutes(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour_text, minute_text, *rest = value.strip().split(":")
        hour = int(hour_text)
        minute = int(minute_text)
        second = int(rest[0]) if rest else 0
    except (ValueError, AttributeError):
        return None
    if hour < 0 or minute < 0 or minute > 59 or second < 0 or second > 59:
        return None
    return hour * 60 + minute + (1 if second >= 30 else 0)


def duration_minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(max(total_minutes, 0), 60)
    return f"{hours}h{minutes:02d}"


def format_price(amount: str | float | int | None, currency: str | None) -> str | None:
    if amount in (None, "") or not currency:
        return None
    try:
        numeric_amount = float(amount)
    except (TypeError, ValueError):
        return None
    normalized_currency = currency.upper()
    amount_text = f"{numeric_amount:.2f}".replace(".", ",")
    if normalized_currency == "EUR":
        return f"{amount_text} EUR"
    return f"{amount_text} {normalized_currency}"


def safe_float(value: object) -> float | None:
    try:
        if value is None:
            return None
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(converted):
        return None
    return converted


def parse_coord_string(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    parts = re.split(r"[;, ]+", value.strip())
    numeric = [safe_float(part) for part in parts if part]
    numeric = [part for part in numeric if part is not None]
    if len(numeric) < 2:
        return None, None
    first, second = numeric[0], numeric[1]
    if abs(first) <= 90 and abs(second) <= 180:
        return first, second
    if abs(second) <= 90 and abs(first) <= 180:
        return second, first
    return None, None


def match_score(candidate: str, query: str) -> int:
    candidate_norm = normalize_text(candidate)
    query_norm = normalize_text(query)
    if not query_norm:
        return 0
    if candidate_norm == query_norm:
        return 100
    if candidate_norm.startswith(query_norm + " "):
        return 80
    if f" {query_norm} " in f" {candidate_norm} ":
        return 60
    if query_norm in candidate_norm:
        return 40
    return 0


def add_minutes(moment: datetime, minutes: int) -> datetime:
    return moment + timedelta(minutes=minutes)
