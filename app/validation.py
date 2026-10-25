from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from flask import request

from .errors import ApiError

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def json_body() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "Send a JSON object in the request body.")
    return data


def clean_text(value: Any, field: str, *, max_len: int, required: bool = False, min_len: int = 0) -> str:
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        raise ApiError(400, f"{field} must be text.")
    text = _CTRL.sub("", str(value)).strip()
    if required and not text:
        raise ApiError(400, f"{field} is required.")
    if text and len(text) < min_len:
        raise ApiError(400, f"{field} must be at least {min_len} characters.")
    if len(text) > max_len:
        raise ApiError(400, f"{field} must be at most {max_len} characters.")
    return text


def choice(value: Any, field: str, allowed: Iterable[str], *, required: bool = True, default: str | None = None) -> str:
    allowed = list(allowed)
    if value in (None, ""):
        if default is not None:
            return default
        if required:
            raise ApiError(400, f"{field} is required.")
        return ""
    if value not in allowed:
        raise ApiError(400, f"{field} must be one of: {', '.join(allowed)}.")
    return value


def number(value: Any, field: str, *, lo: float, hi: float, required: bool = False) -> float | None:
    if value in (None, ""):
        if required:
            raise ApiError(400, f"{field} is required.")
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{field} must be a number.") from None
    if not (lo <= num <= hi) or num != num:
        raise ApiError(400, f"{field} must be between {lo} and {hi}.")
    return num


def query_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return max(lo, min(hi, int(raw)))
    except ValueError:
        raise ApiError(400, f"{name} must be a whole number.") from None


DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def device_id(value: Any) -> str:
    text = clean_text(value, "device_id", max_len=64, required=True)
    if not DEVICE_ID_RE.match(text):
        raise ApiError(400, "device_id is not valid.")
    return text
