"""Assessment contract tests: levels 1-5.

Level 3/4 concurrency tests run real threads against the database
(TransactionTestCase), mirroring what a grader does over HTTP.
"""
import concurrent.futures
from datetime import timedelta
from urllib.parse import quote

from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .models import Booking, BookingAttempt, IdempotencyRecord, Slot

KEY = "clinic-demo-key"


def slot_payload(sid, provider, start, end):
    return {"id": sid, "provider": provider, "start": start, "end": end}


def default_slots():
    now = timezone.now()
    future = now + timedelta(hours=24)
    return [
        slot_payload("p1", "Dr Bala",
                     (now - timedelta(days=1)).isoformat(),
                     (now - timedelta(days=1) + timedelta(minutes=30)).isoformat()),
        slot_payload("s1", "Dr Ade", future.isoformat(),
                     (future + timedelta(minutes=30)).isoformat()),
        slot_payload("s3", "Dr Bala", (future + timedelta(hours=1)).isoformat(),
                     (future + timedelta(hours=1) + timedelta(minutes=30)).isoformat()),
        slot_payload("s2", "Dr Ade", (future + timedelta(hours=2)).isoformat(),
                     (future + timedelta(hours=2) + timedelta(minutes=30)).isoformat()),
    ]


def fresh_client():
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=KEY)
    return client


class BaseMixin:
    def setUp(self):
        self.client = fresh_client()

    def reset_data(self):
        response = self.client.post("/reset", {"slots": default_slots()}, format="json")
        self.assertEqual(response.status_code, 200, response.json() if response.content else "")
        return response

    def book(self, client=None, slot_id="s1", name="Ada Obi",
             email="ada@example.com", headers=None):
        return (client or self.client).post(
            "/bookings",
            {"slot_id": slot_id, "name": name, "email": email},
            format="json",
            headers=headers or {},
        )


class Level1Tests(BaseMixin, TestCase):
    def test_reset_replaces_slots_and_clears_state(self):
        self.reset_data()
        self.book(self.client)
        self.assertTrue(Slot.objects.exists())
        self.assertEqual(Booking.objects.count(), 1)

        replacement = [slot_payload(
            "x1", "Dr Who",
            (timezone.now() + timedelta(hours=5)).isoformat(),
            (timezone.now() + timedelta(hours=5, minutes=30)).isoformat(),
        )]
        response = self.client.post("/reset", {"slots": replacement}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Slot.objects.count(), 1)
        self.assertEqual(Booking.objects.count(), 0)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)
        self.assertEqual(BookingAttempt.objects.count(), 0)

    def test_slots_sorted_earliest_first_with_tiebreak(self):
        self.reset_data()
        response = self.client.get("/slots")
        self.assertEqual(response.status_code, 200)
        ids = [s["id"] for s in response.json()["slots"]]
        self.assertEqual(ids, ["p1", "s1", "s3", "s2"])

    def test_slots_have_available_flag(self):
        self.reset_data()
        self.book(self.client, slot_id="s1")
        slots = {s["id"]: s for s in self.client.get("/slots").json()["slots"]}
        self.assertFalse(slots["s1"]["available"])
        self.assertTrue(slots["s2"]["available"])
        self.assertTrue(slots["p1"]["available"])

    def test_provider_filter_is_exact_match(self):
        self.reset_data()
        response = self.client.get("/slots", {"provider": "Dr Ade"})
        self.assertEqual([s["id"] for s in response.json()["slots"]], ["s1", "s2"])
        response = self.client.get("/slots", {"provider": "Dr Ade XX"})
        self.assertEqual(response.json()["slots"], [])

    def test_book_returns_201_with_confirmed_booking(self):
        self.reset_data()
        response = self.book(self.client, email="Ada@Example.COM")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            sorted(body.keys()), ["created_at", "email", "id", "name", "slot_id", "status"]
        )
        self.assertEqual(body["status"], "confirmed")
        self.assertEqual(body["email"], "ada@example.com")
        self.assertTrue(body["created_at"].endswith("Z"))

    def test_lookup_by_id_and_404s(self):
        self.reset_data()
        booking = self.book(self.client).json()

        response = self.client.get(f"/bookings/{booking['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], booking["id"])

        response = self.client.get("/bookings/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)

        response = self.client.get("/bookings/nope")
        self.assertEqual(response.status_code, 404)


class Level2Tests(BaseMixin, TestCase):
    def test_every_endpoint_requires_the_key(self):
        self.reset_data()
        checks = [
            ("GET", "/slots", None),
            ("POST", "/bookings", {"slot_id": "s1", "name": "A", "email": "a@b.co"}),
            ("DELETE", "/bookings/xyz", None),
            ("POST", "/reset", {"slots": []}),
        ]
        for with_key in (None, "wrong-key"):
            for method, path, body in checks:
                client = APIClient()
                if with_key:
                    client.credentials(HTTP_X_API_KEY=with_key)
                method_fn = {
                    "GET": client.get, "POST": client.post, "DELETE": client.delete,
                }[method]
                kwargs = {} if body is None else {"data": body}
                response = method_fn(path, format="json", **kwargs)
                self.assertEqual(response.status_code, 401, (method, path, with_key))
                self.assertIn("error", response.json())

    def test_missing_blank_and_invalid_fields_are_rejected(self):
        self.reset_data()
        cases = [
            {"slot_id": "s1", "name": "Ada Obi"},                            # no email
            {"slot_id": "s1", "email": "ada@example.com"},                   # no name
            {"slot_id": "s1", "name": "   ", "email": "ada@example.com"},    # blank name
            {"slot_id": "s1", "name": "Ada Obi", "email": "   "},            # blank email
            {"name": "Ada Obi", "email": "ada@example.com"},                 # no slot_id
            {"slot_id": "s1", "name": "Ada Obi", "email": "not-an-email"},
            {"slot_id": "s1", "name": "Ada Obi", "email": "ada@example"},
            {"slot_id": "s1", "name": "Ada Obi", "email": "ada@example.com."},
            {"slot_id": "s1", "name": "Ada Obi", "email": "ada example.com"},
        ]
        for case in cases:
            response = self.client.post("/bookings", case, format="json")
            self.assertEqual(response.status_code, 400, case)
            self.assertIn("error", response.json(), case)

    def test_unknown_slot_is_404_not_400(self):
        self.reset_data()
        response = self.book(self.client, slot_id="ghost")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_already_started_slot_is_400(self):
        self.reset_data()
        response = self.book(self.client, slot_id="p1")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    def test_name_and_email_trimmed_email_lowercased(self):
        self.reset_data()
        response = self.book(self.client, name="  Ada Obi  ", email="  ADA@Example.COM ")
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["name"], "Ada Obi")
        self.assertEqual(body["email"], "ada@example.com")


class Level3Tests(BaseMixin, TestCase):
    def test_second_booking_on_same_slot_conflicts(self):
        self.reset_data()
        self.book(self.client, slot_id="s1", email="one@example.com")
        response = self.book(self.client, slot_id="s1", name="Bo Dia", email="two@example.com")
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())

    def test_cancel_frees_slot_then_rebookable(self):
        self.reset_data()
        booking = self.book(self.client, slot_id="s1").json()

        response = self.client.delete(f"/bookings/{booking['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "cancelled")

        response = self.client.delete(f"/bookings/{booking['id']}")
        self.assertEqual(response.status_code, 409)
        self.assertIn("error", response.json())

        slots = {s["id"]: s for s in self.client.get("/slots").json()["slots"]}
        self.assertTrue(slots["s1"]["available"])

        response = self.book(self.client, slot_id="s1", email="two@example.com")
        self.assertEqual(response.status_code, 201)

    def test_cancel_unknown_booking_404(self):
        self.reset_data()
        response = self.client.delete("/bookings/00000000-0000-0000-0000-000000000000")
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())


class Level3ConcurrencyTests(BaseMixin, TransactionTestCase):
    def test_parallel_bookings_only_one_wins(self):
        self.reset_data()
        racers = 12

        def race(i):
            try:
                client = fresh_client()
                return client.post(
                    "/bookings",
                    {"slot_id": "s1", "name": f"Race {i:02}", "email": f"race{i}@example.com"},
                    format="json",
                )
            finally:
                from django.db import connections
                connections.close_all()

        with concurrent.futures.ThreadPoolExecutor(max_workers=racers) as pool:
            results = [f.result().status_code for f in
                       [pool.submit(race, i) for i in range(racers)]]

        self.assertEqual(results.count(201), 1, results)
        self.assertEqual(results.count(409), racers - 1, results)
        slots = {s["id"]: s for s in self.client.get("/slots").json()["slots"]}
        self.assertFalse(slots["s1"]["available"])

    def test_parallel_cancels_exactly_one_wins(self):
        self.reset_data()
        booking = self.book(self.client, slot_id="s1").json()

        def do_cancel():
            try:
                return fresh_client().delete(f"/bookings/{booking['id']}").status_code
            finally:
                from django.db import connections
                connections.close_all()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = [f.result() for f in
                       [pool.submit(do_cancel) for _ in range(4)]]

        self.assertEqual(results.count(200), 1, results)
        self.assertEqual(results.count(409), 3, results)


class Level4Tests(BaseMixin, TestCase):
    def test_same_key_and_body_replay_returns_identical_response(self):
        self.reset_data()
        first = self.book(self.client, email="idem@example.com",
                          headers={"Idempotency-Key": "key-42"})
        self.assertEqual(first.status_code, 201)
        second = self.book(self.client, email="idem@example.com",
                           headers={"Idempotency-Key": "key-42"})
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Booking.objects.count(), 1)

    def test_same_key_different_body_is_422(self):
        self.reset_data()
        self.book(self.client, email="idem@example.com",
                  headers={"Idempotency-Key": "key-42"})
        for changed in ({"slot_id": "s3"}, {"name": "Ada Two"}, {"email": "someone@example.com"}):
            response = self.client.post(
                "/bookings",
                {"slot_id": "s1", "name": "Ada Obi", "email": "idem@example.com", **changed},
                format="json",
                headers={"Idempotency-Key": "key-42"},
            )
            self.assertEqual(response.status_code, 422, changed)
        self.assertEqual(Booking.objects.count(), 1)

    def test_reset_wipes_idempotency_state(self):
        self.reset_data()
        first = self.book(self.client, email="idem@example.com",
                          headers={"Idempotency-Key": "key-42"}).json()
        self.reset_data()
        again = self.book(self.client, email="idem@example.com",
                          headers={"Idempotency-Key": "key-42"}).json()
        self.assertNotEqual(first["id"], again["id"])


class Level4ListTests(BaseMixin, TestCase):
    def seed(self, count):
        slots = list(Slot.objects.all())
        used = set()
        for i in range(count):
            slot = slots[i % len(slots)]
            # Only one confirmed booking per slot (L3 constraint), extras are
            # cancelled — they must still appear in the person's listing.
            status = Booking.STATUS_CONFIRMED if i < len(slots) else Booking.STATUS_CANCELLED
            booking = Booking.objects.create(
                slot=slot, name="Paged An", email="paged@example.com", status=status,
            )
            Booking.objects.filter(pk=booking.pk).update(
                created_at=timezone.now() - timedelta(minutes=300 - i * 10)
            )
            used.add(slot.pk)

    def test_walks_cursor_pages_without_duplicates(self):
        self.reset_data()
        self.seed(10)
        ids = []
        cursor = None
        for _ in range(6):
            path = "/bookings?email=paged@example.com&limit=4"
            if cursor:
                path += f"&cursor={quote(cursor)}"
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            page = response.json()
            ids.extend(b["id"] for b in page["bookings"])
            created = [b["created_at"] for b in page["bookings"]]
            self.assertEqual(created, sorted(created))
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(len(ids), 10)
        self.assertEqual(len(set(ids)), 10)
        self.assertIsNone(cursor)

    def test_email_match_ignores_case(self):
        self.reset_data()
        self.seed(3)
        response = self.client.get("/bookings", {"email": "PAGED@Example.COM"})
        self.assertEqual(len(response.json()["bookings"]), 3)

    def test_invalid_limit_and_missing_email(self):
        for limit in ("0", "51", "abc", "-3", "5.5"):
            response = self.client.get(f"/bookings?email=x@y.co&limit={limit}")
            self.assertEqual(response.status_code, 400, limit)
            self.assertIn("error", response.json())
        response = self.client.get("/bookings")
        self.assertEqual(response.status_code, 400)

    def test_invalid_cursor_rejected(self):
        response = self.client.get("/bookings", {"email": "x@y.co", "cursor": "@@bad@@"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class Level5Tests(BaseMixin, TestCase):
    def test_sixth_attempt_429_with_retry_after(self):
        self.reset_data()
        for i in range(4):  # failed attempts are included
            response = self.book(self.client, slot_id="s1", name="   ",
                                 email="spammer@example.com")
            self.assertEqual(response.status_code, 400, i)
        response = self.book(self.client, slot_id="s1", email="spammer@example.com")
        self.assertEqual(response.status_code, 201)
        response = self.book(self.client, slot_id="s3", email="spammer@example.com")
        self.assertEqual(response.status_code, 429)
        retry_after = response.headers.get("Retry-After")
        self.assertIsNotNone(retry_after)
        value = int(float(retry_after))
        self.assertGreaterEqual(value, 1)
        self.assertLessEqual(value, 60)
        self.assertIn("error", response.json())

    def test_other_email_unaffected(self):
        self.reset_data()
        for _ in range(5):
            self.book(self.client, slot_id="s1", name="   ", email="busy@example.com")
        response = self.book(self.client, slot_id="s1", email="calm@example.com")
        self.assertEqual(response.status_code, 201)

    def test_idempotent_replay_does_not_consume_attempts(self):
        self.reset_data()
        first = self.book(self.client, slot_id="s1", email="replayer@example.com",
                          headers={"Idempotency-Key": "key-replay"})
        self.assertEqual(first.status_code, 201)
        for _ in range(4):
            self.book(self.client, slot_id="s1", name="   ", email="replayer@example.com")
        response = self.book(self.client, slot_id="s3", email="replayer@example.com")
        self.assertEqual(response.status_code, 429)

        replay = self.book(self.client, slot_id="s1", email="replayer@example.com",
                           headers={"Idempotency-Key": "key-replay"})
        self.assertEqual(replay.status_code, 201)
        self.assertEqual(replay.json(), first.json())
        self.assertEqual(Booking.objects.count(), 1)


class SeedSlotsTests(TestCase):
    def test_seeds_only_when_empty_and_is_idempotent(self):
        from django.core.management import call_command

        # Fresh database: seeds the standard slot set.
        Slot.objects.all().delete()
        call_command("seed_slots", stdout=None)
        self.assertEqual(Slot.objects.count(), 6)
        self.assertTrue(all(s.start > timezone.now() for s in Slot.objects.all()))

        # Re-running on every build changes nothing.
        call_command("seed_slots", stdout=None)
        self.assertEqual(Slot.objects.count(), 6)
