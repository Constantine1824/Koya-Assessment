"""Rolling demo-slot refresh so a deployed clinic is never stale.

Slots are seeded with times relative to whenever the database was first
built, so they eventually drift into the past and every booking attempt
would fail with "slot has already started" — indistinguishable, to a
visitor weeks later, from a broken service.

`ensure_fresh_demo_slots` re-rolls the standard slot set forward relative
to *now*, but stays out of the way the moment the database belongs to
someone else:

1. Any upcoming slot -> the database is fresh, nothing to do.
2. Any booking / idempotency record / attempt created within
   DEMO_SLOT_QUIET_HOURS (default 24h) -> someone is actively using the
   system right now; never touch it mid-session.
3. A POST /reset within DEMO_SLOT_RESET_GRACE_DAYS (default 7d, tracked
   by the SeedState singleton) -> the current slots are an explicit,
   authoritative payload. Even a reset consisting purely of past slots
   (the "already started" 400 test case) is respected.

Slots are re-rolled in place (bulk_update) rather than deleted: old
bookings may still reference them (ForeignKey on_delete=PROTECT), and
those bookings keep their data — only the slot times move forward.
"""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from booking.models import Booking, BookingAttempt, IdempotencyRecord, SeedState, Slot

PROVIDERS = ["Dr Ade", "Dr Bala", "Dr Chu", "Dr Efe", "Dr Ade", "Dr Bala"]

SLOT_COUNT = len(PROVIDERS)
FIRST_SLOT_DELAY = timedelta(hours=2)


def _has_recent_activity(now):
    cutoff = now - timedelta(hours=settings.DEMO_SLOT_QUIET_HOURS)
    return (
        Booking.objects.filter(created_at__gte=cutoff).exists()
        or IdempotencyRecord.objects.filter(created_at__gte=cutoff).exists()
        or BookingAttempt.objects.filter(at__gte=cutoff).exists()
    )


def _reset_is_authoritative(now):
    state = SeedState.objects.filter(key="slots").first()
    if state is None or state.last_reset_at is None:
        return False
    return now - state.last_reset_at < timedelta(days=settings.DEMO_SLOT_RESET_GRACE_DAYS)


def demo_refresh_block_reason():
    """Why the manual (button) refresh would no-op. The button runs with
    force=True, so the quiet-window guard cannot be the reason; callers
    get a human-readable explanation instead."""
    now = timezone.now()
    if Slot.objects.filter(start__gt=now).exists():
        return "slots are already fresh"
    if _reset_is_authoritative(now):
        return "a recent POST /reset owns these slots; left untouched"
    return "unknown"


def ensure_fresh_demo_slots(force=False):
    """Re-roll the demo slots when they have gone stale and the database
    is quiet. Returns the number of slots refreshed (0 = deliberate
    no-op).

    force=True skips the quiet-window guard — used by the page's Refresh
    button, where a human explicitly clicked. The reset-grace guard is
    always respected: an explicit POST /reset payload is authoritative
    data no matter who asks."""
    now = timezone.now()
    if Slot.objects.filter(start__gt=now).exists():
        return 0  # still fresh (the common case: one query)
    if not force and _has_recent_activity(now):
        return 0  # someone is using the system right now
    if _reset_is_authoritative(now):
        return 0  # an explicit reset payload owns the current slots

    slots = list(Slot.objects.all())
    total = 0
    if slots:
        # Stale database: move the existing slots forward, in place, so
        # bookings that still reference them keep their data.
        new_starts = [now + FIRST_SLOT_DELAY + timedelta(hours=i) for i in range(len(slots))]
        for i, slot in enumerate(slots):
            slot.start = new_starts[i]
            slot.end = new_starts[i] + timedelta(minutes=30)
        Slot.objects.bulk_update(slots, ["start", "end"])
        total += len(slots)

    # Top up to the standard set so the page never looks sparse.
    existing_ids = {slot.id for slot in slots}
    missing = [f"d{i + 1}" for i in range(SLOT_COUNT) if f"d{i + 1}" not in existing_ids]
    if missing:
        Slot.objects.bulk_create(
            Slot(
                id=slot_id,
                provider=PROVIDERS[len(slots) + k],
                start=now + FIRST_SLOT_DELAY + timedelta(hours=len(slots) + k),
                end=now + FIRST_SLOT_DELAY + timedelta(hours=len(slots) + k) + timedelta(minutes=30),
            )
            for k, slot_id in enumerate(missing)
        )
        total += len(missing)
    return total
