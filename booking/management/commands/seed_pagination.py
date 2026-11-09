"""Seed 15 slots and 15 backdated bookings for pagination testing.

Run: python manage.py seed_pagination
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import Booking, BookingAttempt, IdempotencyRecord, Slot


class Command(BaseCommand):
    help = "Wipe data, seed 15 future slots and 15 backdated bookings for pagination tests"

    def handle(self, *args, **options):
        now = timezone.now()
        IdempotencyRecord.objects.all().delete()
        BookingAttempt.objects.all().delete()
        Booking.objects.all().delete()
        Slot.objects.all().delete()

        slots = [
            Slot(id=f"pg{i:02}", provider="Dr Page",
                 start=now + timedelta(days=i), end=now + timedelta(days=i, minutes=30))
            for i in range(15)
        ]
        Slot.objects.bulk_create(slots)

        # created_at is auto_now_add, so lowercase it into the window by
        # updating rows after creation; also makes the cursor order stable.
        for i in range(15):
            booking = Booking.objects.create(
                slot=slots[i], name="Paged An", email="paged@example.com",
                status=Booking.STATUS_CONFIRMED,
            )
            Booking.objects.filter(pk=booking.pk).update(
                created_at=now - timedelta(minutes=200 - i * 10)
            )

        self.stdout.write(self.style.SUCCESS("seeded 15 slots + 15 bookings (paged@example.com)"))
