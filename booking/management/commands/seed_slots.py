"""Populate the database the very first time it is used.

Creates the standard 6-slot set ONLY when the Slot table is empty, so a
fresh deployment (e.g. new Render Postgres) works before anyone calls
POST /reset. Made deploy-safe: it never considers demo bookings and it
never wipes, so re-running on every build changes nothing. (The dev-only
counterpart with sample bookings is `seed_demo`.)
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from booking.models import Slot

PROVIDERS = ["Dr Ade", "Dr Bala", "Dr Chu", "Dr Efe", "Dr Ade", "Dr Bala"]


class Command(BaseCommand):
    help = "Seed the default slots if the database has none (idempotent)"

    def handle(self, *args, **options):
        if Slot.objects.exists():
            self.stdout.write(
                f"slots already present ({Slot.objects.count()}) -- nothing to seed"
            )
            return

        base = timezone.now() + timedelta(hours=2)
        Slot.objects.bulk_create(
            Slot(
                id=f"d{i + 1}",
                provider=provider,
                start=base + timedelta(hours=i + 1),
                end=base + timedelta(hours=i + 1) + timedelta(minutes=30),
            )
            for i, provider in enumerate(PROVIDERS)
        )
        self.stdout.write(self.style.SUCCESS(f"seeded {len(PROVIDERS)} slots (fresh database)"))
