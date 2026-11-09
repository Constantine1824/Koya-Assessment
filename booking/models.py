import uuid

from django.db import models


class Slot(models.Model):
    id = models.CharField(primary_key=True, max_length=255)
    provider = models.CharField(max_length=255)
    start = models.DateTimeField()
    end = models.DateTimeField()

    class Meta:
        ordering = ["start", "id"]

    def __str__(self):
        return f"{self.provider} {self.id}"


class Booking(models.Model):
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [(STATUS_CONFIRMED, STATUS_CONFIRMED), (STATUS_CANCELLED, STATUS_CANCELLED)]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slot = models.ForeignKey(Slot, on_delete=models.PROTECT, related_name="bookings")
    name = models.CharField(max_length=255)
    email = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CONFIRMED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "created_at", "id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["slot"],
                condition=models.Q(status="confirmed"),
                name="uniq_confirmed_booking_per_slot",
            ),
        ]

    def __str__(self):
        return f"{self.email} -> {self.slot}"


class IdempotencyRecord(models.Model):
    """Level 4: replays of the same Idempotency-Key return the stored
    response verbatim; a different body under the same key is a 422."""

    key = models.CharField(primary_key=True, max_length=255)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveIntegerField(null=True)  # null = still in flight
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.key}'


class BookingAttempt(models.Model):
    """Level 5: every POST /bookings attempt per email, used by the
    rolling-window rate limiter."""

    email = models.CharField(max_length=255, db_index=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.email} @ {self.at}"
