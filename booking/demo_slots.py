"""Rolling demo-slot refresh so a deployed clinic is never stale.

Slots are seeded with times relative to whenever the database was first
built, so they eventually drift into the past and every booking attempt
would fail with "slot has already started" — indistinguishable, to a
visitor weeks later, from a broken service.

`ensure_fresh_demo_slots` re-rolls the standard slot set forward relative
to *now*, but only when the database is completely pristine: no future
slots AND no rows in any booking-domain table. Any real traffic — a
grader's POST /reset, a booking, even a failed attempt with an
idempotency key — leaves rows behind, which switches the helper off
permanently. That makes it safe to call from the web page on every
render: it can only ever act on a database nobody has used yet.
"""
from datetime import timedelta

from django.utils import timezone

from booking.models import Booking, BookingAttempt, IdempotencyRecord, Slot

PROVIDERS = ["Dr Ade", "Dr Bala", "Dr Chu", "Dr Efe", "Dr Ade", "Dr Bala"]

SLOT_COUNT = len(PROVIDERS)
FIRST_SLOT_DELAY = timedelta(hours=2)


def _database_is_pristine():
    """True only when no API activity has ever touched this database."""
    return not (
        Booking.objects.exists()
        or IdempotencyRecord.objects.exists()
        or BookingAttempt.objects.exists()
    )


def ensure_fresh_demo_slots():
    """Create the standard slots if the database is pristine and has no
    upcoming ones. Returns the number of slots created (0 = deliberate
    no-op)."""
    now = timezone.now()
    if Slot.objects.filter(start__gt=now).exists():
        return 0  # still fresh, nothing to do (the common case: one query)
    if not _database_is_pristine():
        return 0  # someone is using the system; never touch their data

    # Pristine means no booking/idempotency/attempt rows exist, so the old
    # slots cannot be referenced by anything and are safe to replace.
    Slot.objects.all().delete()
    Slot.objects.bulk_create(
        Slot(
            id=f"d{i + 1}",
            provider=provider,
            start=now + FIRST_SLOT_DELAY + timedelta(hours=i),
            end=now + FIRST_SLOT_DELAY + timedelta(hours=i) + timedelta(minutes=30),
        )
        for i, provider in enumerate(PROVIDERS)
    )
    return SLOT_COUNT
