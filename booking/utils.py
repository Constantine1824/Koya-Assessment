import base64
import hashlib
import json
from datetime import timezone as dt_tz

from django.utils.dateparse import parse_datetime


def parse_dt(value):
    """Parse an ISO-8601 datetime; naive values are assumed UTC."""
    dt = parse_datetime(value) if isinstance(value, str) else None
    if dt is None:
        raise ValueError(f"invalid datetime: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_tz.utc)
    return dt


def canonical_body_hash(body):
    """Stable hash of a parsed JSON body so semantically identical bodies
    (any key order) share one hash for idempotency matching."""
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def encode_cursor(last_created_at, last_id):
    raw = json.dumps({"c": last_created_at.isoformat(), "i": str(last_id)})
    return base64.urlsafe_b64encode(raw.encode("ascii")).decode("ascii")


def decode_cursor(token):
    raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or "c" not in data or "i" not in data:
        raise ValueError("malformed cursor")
    return parse_dt(data["c"]), data["i"]
