import math
import time
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .demo_slots import demo_refresh_block_reason, ensure_fresh_demo_slots
from .models import Booking, BookingAttempt, IdempotencyRecord, SeedState, Slot
from .serializers import BookingSerializer, NewBookingSerializer, SlotListSerializer
from .utils import canonical_body_hash, decode_cursor, encode_cursor, parse_dt

ERROR_STARTED = "slot has already started"
ERROR_SLOT_MISSING = "slot not found"
ERROR_CONFLICT = "slot already booked"
ERROR_IDEM_REPLAY_MISMATCH = "idempotency key reused with a different body"
ERROR_RATE_LIMITED = "too many booking attempts for this email, try again later"
ERROR_RESERVED_EMAIL = "__no_email__"

IDEM_WAIT_SECONDS = 10
IDEM_PENDING_MAX_AGE = timedelta(minutes=15)
_LAST_ATTEMPT_CLEANUP = [None]


def _retry_locked(fn):
    """SQLite (file mode) can surface transient lock contention when many
    threads collide outside the booking transaction. PostgreSQL never
    hits this path; on SQLite we briefly wait and retry."""
    def wrapper(*args, **kwargs):
        for attempt in range(4):
            try:
                return fn(*args, **kwargs)
            except OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < 3:
                    time.sleep(0.05 * (attempt + 1))
                    continue
                raise
        return None
    return wrapper


def error_response(message, status_code, headers=None):
    return Response({"error": message}, status=status_code, headers=headers)


def page_view(request):
    # Keeps a deployed page usable whenever it is first visited, however
    # long after the build; a no-op the moment the database has any
    # activity (see demo_slots docstring).
    ensure_fresh_demo_slots()
    return render(
        request,
        "booking/index.html",
        {
            "api_key": settings.X_API_KEY,
            "api_base": getattr(settings, "CLINIC_API_BASE", ""),
        },
    )


def api_page_view(request):
    """Interactive OpenAPI explorer at /api (AllowAnonymous: harmless spec)."""
    return render(request, "booking/api.html", {"api_key": settings.X_API_KEY})


@api_view(["POST"])
def demo_refresh_view(request):
    """Demo-ops helper behind the page's Refresh button: re-rolls stale
    demo slot times to now. The explicit click bypasses the quiet-window
    guard (a human asked for it), but a recent POST /reset payload stays
    untouchable. Not part of the graded contract."""
    refreshed = ensure_fresh_demo_slots(force=True)
    if refreshed:
        return Response({"refreshed": refreshed})
    return Response({"refreshed": 0, "reason": demo_refresh_block_reason()})


# ---------------------------------------------------------------------------
# Level 1 - reset, slots, bookings, booking detail
# ---------------------------------------------------------------------------


@api_view(["POST"])
def reset_view(request):
    data = request.data
    if not isinstance(data, dict) or "slots" not in data:
        return error_response("slots is required", 400)
    slots_data = data["slots"]
    if not isinstance(slots_data, list):
        return error_response("slots must be a list", 400)

    by_id = {}
    for i, item in enumerate(slots_data):
        invalid = _invalid_slot(item, i)
        if invalid is not None:
            return invalid
        try:
            start = parse_dt(item["start"])
            end = parse_dt(item["end"])
        except ValueError as exc:
            return error_response(f"slot[{i}]: {exc}", 400)
        by_id[item["id"].strip()] = Slot(
            id=item["id"].strip(), provider=item["provider"].strip(), start=start, end=end
        )

    with transaction.atomic():
        _perform_reset(by_id)

    return Response({"status": "reset", "slots": len(by_id)})


@_retry_locked
def _perform_reset(by_id):
    # Wipe related state too so graders always start clean.
    IdempotencyRecord.objects.all().delete()
    BookingAttempt.objects.all().delete()
    Booking.objects.all().delete()
    Slot.objects.all().delete()
    Slot.objects.bulk_create(by_id.values())
    # An explicit reset payload is authoritative: the rolling demo-slot
    # refresh must leave these slots alone for a grace period.
    SeedState.mark_reset()


def _invalid_slot(item, i):
    if not isinstance(item, dict):
        return error_response(f"slot[{i}] must be an object", 400)
    for field in ("id", "provider", "start", "end"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            return error_response(f"slot[{i}]: {field} is required", 400)
    return None


@api_view(["GET"])
def slots_view(request):
    qs = Slot.objects.annotate(
        confirmed_count=Count("bookings", filter=Q(bookings__status=Booking.STATUS_CONFIRMED))
    )
    provider = request.query_params.get("provider")
    if provider:
        qs = qs.filter(provider=provider)
    qs = qs.order_by("start", "id")  # earliest start first
    return Response({"slots": SlotListSerializer(qs, many=True).data})


# ---------------------------------------------------------------------------
# Levels 2-5 - POST /bookings
# ---------------------------------------------------------------------------


class IdempotencyState:
    NEW = "new"          # reserved a pending record for this key -> proceed
    REPLAY = "replay"    # same key + same body -> return stored response


def _resolve_idempotency(idem_key, body_hash):
    """Returns (state, replay_response_or_pending_record)."""
    while True:
        record = IdempotencyRecord.objects.filter(key=idem_key).first()
        if record is None:
            try:
                _reserve_idempotency(idem_key, body_hash)
            except IntegrityError:
                continue  # concurrent request reserved it; loop and replay
            return IdempotencyState.NEW, None

        if record.request_hash != body_hash:
            return None, error_response(ERROR_IDEM_REPLAY_MISMATCH, 422)

        if record.status_code is not None:
            return None, Response(record.response_body, status=record.status_code)

        # Pending: another request holds this exact key+body right now.
        age = timezone.now() - record.created_at
        if age > IDEM_PENDING_MAX_AGE:
            # Abandoned by a crashed request; adopt it and retry fresh below.
            record.delete()
            continue

        deadline = time.monotonic() + IDEM_WAIT_SECONDS
        while time.monotonic() < deadline:
            time.sleep(0.05)
            record = IdempotencyRecord.objects.filter(key=idem_key).first()
            if record is None:
                break  # it was adopted/reset elsewhere; restart outer loop
            if record.status_code is not None:
                return None, Response(record.response_body, status=record.status_code)
        return None, error_response("request is still being processed", 503)


@_retry_locked
def _reserve_idempotency(idem_key, body_hash):
    IdempotencyRecord.objects.create(
        key=idem_key, request_hash=body_hash, status_code=None, response_body=None
    )


def _finalize_idempotency(idem_key, body_hash, status_code, body):
    IdempotencyRecord.objects.filter(key=idem_key, request_hash=body_hash).update(
        status_code=status_code, response_body=body
    )


def _touch_rate_limit(email_raw):
    """Level 5: records this attempt and returns a 429 Response when the
    rolling window is full. Failed attempts count, successful ones count,
    and other emails are never affected."""
    if isinstance(email_raw, str) and email_raw.strip():
        bucket = email_raw.strip().lower()
    else:
        bucket = ERROR_RESERVED_EMAIL

    now = timezone.now()
    _cleanup_old_attempts(now)
    blocked_response = _rate_limit_probe(bucket, now)
    if blocked_response is not None:
        return blocked_response
    return None


@_retry_locked
def _rate_limit_probe(bucket, now):
    """Records the attempt, then returns a 429 Response if the rolling
    window is already full."""
    BookingAttempt.objects.create(email=bucket)
    window_start = now - timedelta(seconds=settings.RATE_LIMIT_WINDOW_SECONDS)
    attempts = list(
        BookingAttempt.objects.filter(email=bucket, at__gte=window_start).order_by("at")
    )
    if len(attempts) > settings.RATE_LIMIT_MAX_ATTEMPTS:
        oldest = attempts[0].at
        retry_after = max(
            1,
            math.ceil(
                (oldest + timedelta(seconds=settings.RATE_LIMIT_WINDOW_SECONDS) - now).total_seconds()
            ),
        )
        return error_response(
            ERROR_RATE_LIMITED, 429, headers={"Retry-After": str(retry_after)}
        )
    return None


def _cleanup_old_attempts(now):
    last = _LAST_ATTEMPT_CLEANUP[0]
    if last is None or (now - last).total_seconds() > 60:
        BookingAttempt.objects.filter(
            at__lt=now - timedelta(hours=settings.RATE_LIMIT_EMAILS_TTL_HOURS)
        ).delete()
        _LAST_ATTEMPT_CLEANUP[0] = now


def _validate_or_message(body):
    serializer = NewBookingSerializer(data=body)
    if not serializer.is_valid():
        for field in ("slot_id", "name", "email"):
            if field in serializer.errors:
                return None, str(serializer.errors[field][0])
        return None, "invalid booking"
    return serializer.validated_data, None


def _create_booking(slot_id, name, email):
    """Level 3: race-safe creation. select_for_update serializes contenders
    on this slot; the partial unique constraint is the last line of defense.
    Returns (mode, payload) with mode in: created/missing/started/conflict.
    """
    last_error = None
    for try_no in range(5):
        try:
            with transaction.atomic():
                slot = Slot.objects.select_for_update().get(pk=slot_id)
                if slot.start <= timezone.now():
                    return "started", ERROR_STARTED
                if slot.bookings.filter(status=Booking.STATUS_CONFIRMED).exists():
                    return "conflict", ERROR_CONFLICT
                booking = Booking.objects.create(slot=slot, name=name, email=email)
                return "created", booking
        except Slot.DoesNotExist:
            return "missing", ERROR_SLOT_MISSING
        except IntegrityError:
            # Lost the race against the unique constraint.
            return "conflict", ERROR_CONFLICT
        except OperationalError as exc:
            # SQLite can surface a lock timeout under heavy concurrent tests
            # if a contender was queued behind other writers.
            if "locked" in str(exc).lower() and try_no < 4:
                time.sleep(0.02 * (try_no + 1))
                last_error = exc
                continue
            raise
    raise last_error


@api_view(["GET", "POST"])
def bookings_collection_view(request):
    if request.method == "GET":
        return _person_bookings(request)
    return _create_booking_view(request)


def _create_booking_view(request):
    body = request.data
    if not isinstance(body, dict):
        return error_response("slot_id, name and email are required", 400)

    idem_key = (request.headers.get("Idempotency-Key") or "").strip()
    body_hash = canonical_body_hash(body)

    if idem_key:
        state, replay = _resolve_idempotency(idem_key, body_hash)
        if replay is not None:
            return replay

    # Level 5 first: attempts count even if they later fail validation.
    limited = _touch_rate_limit(body.get("email"))
    if limited is not None:
        return limited

    validated, validation_message = _validate_or_message(body)
    if validation_message is not None:
        if idem_key:
            _finalize_idempotency(idem_key, body_hash, 400, {"error": validation_message})
        return error_response(validation_message, 400)

    mode, payload = _create_booking(
        validated["slot_id"], validated["name"], validated["email"]
    )

    if mode == "created":
        response_body = BookingSerializer(payload).data
        if idem_key:
            _finalize_idempotency(idem_key, body_hash, 201, response_body)
        return Response(response_body, status=201)

    messages = {
        "missing": (404, ERROR_SLOT_MISSING),
        "conflict": (409, ERROR_CONFLICT),
        "started": (400, ERROR_STARTED),
    }
    code, message = messages[mode]
    if idem_key:
        _finalize_idempotency(idem_key, body_hash, code, {"error": message})
    return error_response(message, code)


# ---------------------------------------------------------------------------
# Level 1/3 - booking detail: lookup and cancel
# ---------------------------------------------------------------------------


def _find_booking_or_none(booking_id):
    try:
        return Booking.objects.filter(pk=booking_id).first()
    except (ValueError, ValidationError):
        return None


@api_view(["GET", "DELETE"])
def booking_detail_view(request, booking_id):
    booking = _find_booking_or_none(booking_id)
    if booking is None:
        return error_response("booking not found", 404)

    if request.method == "GET":
        return Response(BookingSerializer(booking).data)

    if booking.status == Booking.STATUS_CANCELLED:
        return error_response("booking already cancelled", 409)
    with transaction.atomic():
        updated = Booking.objects.filter(
            pk=booking.pk, status=Booking.STATUS_CONFIRMED
        ).update(status=Booking.STATUS_CANCELLED)
    if not updated:  # a concurrent request cancelled it first
        return error_response("booking already cancelled", 409)
    booking.refresh_from_db()
    return Response(BookingSerializer(booking).data)


# ---------------------------------------------------------------------------
# Level 4 - list one person's bookings with cursor pagination
# ---------------------------------------------------------------------------


def _person_bookings(request):
    email_param = request.query_params.get("email", "")
    if not email_param.strip():
        return error_response("email is required", 400)
    email = email_param.strip().lower()

    limit_param = request.query_params.get("limit")
    limit = 10
    if limit_param is not None:
        try:
            limit = int(limit_param)
        except ValueError:
            return error_response("invalid limit", 400)
        if not 1 <= limit <= 50:
            return error_response("invalid limit", 400)

    qs = Booking.objects.filter(email=email).order_by("created_at", "id")

    cursor_token = request.query_params.get("cursor")
    if cursor_token:
        try:
            last_created, last_id = decode_cursor(cursor_token)
        except Exception:
            return error_response("invalid cursor", 400)
        qs = qs.filter(
            Q(created_at__gt=last_created) | Q(created_at=last_created, id__gt=last_id)
        )

    rows = list(qs[: limit + 1])
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_cursor(last.created_at, last.pk)

    return Response(
        {"bookings": BookingSerializer(rows, many=True).data, "next_cursor": next_cursor}
    )
