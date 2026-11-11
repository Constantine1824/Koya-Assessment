"""Populate the database the very first time it is used.

Runs on every deploy (see scripts/deploy/build.sh). Creates the standard
6-slot set ONLY when the Slot table is empty, so a fresh deployment
(e.g. new Render Postgres) works before anyone calls POST /reset. The
same rolling-refresh rules as the web page apply: pristine databases
with only stale slots get re-rolled relative to now, and any database
with real activity is left untouched. (The dev-only counterpart with
sample bookings is `seed_demo`.)
"""
from django.core.management.base import BaseCommand

from booking.demo_slots import ensure_fresh_demo_slots


class Command(BaseCommand):
    help = "Seed or refresh the default slots on a pristine database (idempotent)"

    def handle(self, *args, **options):
        created = ensure_fresh_demo_slots()
        if created:
            self.stdout.write(self.style.SUCCESS(f"seeded {created} slots (fresh database)"))
        else:
            self.stdout.write(
                "slots already usable or database in use -- nothing to seed"
            )
