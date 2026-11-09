"""Seed a pleasant demo state: 6 future slots, a few booked, some free.

Run: python manage.py seed_demo
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.crypto import get_random_string

from booking.models import Booking, BookingAttempt, IdempotencyRecord, Slot

PROVIDERS = ["Dr Ade", "Dr Bala", "Dr Chu", "Dr Efe", "Dr Ade", "Dr Bala"]


class Command(BaseCommand):
    help = "Wipe data and seed 6 future slots with a mix of booked/free states"

    def handle(self, *args, **options):
        now = timezone.now()
        IdempotencyRecord.objects.all().delete()
        BookingAttempt.objects.all().delete()
        Booking.objects.all().delete()
        Slot.objects.all().delete()

        base = now + timedelta(hours=2)
        slots = []
        for i, provider in enumerate(PROVIDERS):
            start = base + timedelta(hours=i + 1)
            slots.append(
                Slot(
                    id=f"d{i + 1}",
                    provider=provider,
                    start=start,
                    end=start + timedelta(minutes=30),
                )
            )
        Slot.objects.bulk_create(slots)

        Booking.objects.create(
            slot=slots[0], name="Rosa Nixon", email="rosa@example.com",
        )  # confirmed
        Booking.objects.create(
            slot=slots[1], name="Rosa Nixon", email="rosa@example.com",
            status=Booking.STATUS_CANCELLED,
        )  # cancelled example
        Booking.objects.create(
            slot=slots[2], name="Ada Obi", email="ada@example.com",
        )  # confirmed

        self.stdout.write(
            self.style.SUCCESS(
                "seeded 6 slots (4 available, 2 taken) — "
                "look up email 'rosa@example.com' (1 confirmed, 1 cancelled) "
                "or 'ada@example.com'"
            )
        )
