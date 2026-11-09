"""End-to-end verification against the running Clinic Booking API.

Covers every documented behaviour from https://koyaacademy.com/assessment-api:
levels 1-5, including the concurrent-booking race via real HTTP threads.

Usage: python scripts/smoke_live.py [base_url] [api_key]
"""
import concurrent.futures
import json
import re
import sys
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
KEY = sys.argv[2] if len(sys.argv) > 2 else "clinic-demo-key"

FAILURES = []


def check(name, cond, extra=""):
    tag = "PASS " if cond else "FAIL "
    print(tag + name + ("" if cond else f"   [{extra}]"))
    if not cond:
        FAILURES.append(name)


def req(method, path, key=KEY, body=None, headers=None, timeout=30):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    out = urllib.request.Request(url, data=data, method=method)
    out.add_header("Content-Type", "application/json")
    if key:
        out.add_header("X-API-Key", key)
    for k, v in (headers or {}).items():
        out.add_header(k, v)
    try:
        with urllib.request.urlopen(out, timeout=timeout) as resp:
            raw = resp.read()
            parsed = _parse(raw, resp.headers.get("Content-Type", ""))
            return resp.status, parsed, dict(resp.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        parsed = _parse(raw, e.headers.get("Content-Type", "")) if raw else None
        return e.code, parsed, dict(e.headers)


def _parse(raw, content_type):
    if not raw:
        return None
    if content_type.startswith("application/json"):
        return json.loads(raw)
    return raw[:600].decode(errors="replace")


F = "2027-06-01T{0:02d}:00:00Z"
E = "2027-06-01T{0:02d}:30:00Z"


def slot(sid, provider, start_h, end_h):
    return {"id": sid, "provider": provider, "start": F.format(start_h), "end": E.format(end_h)}


SLOTS = [
    slot("s1", "Dr Ade", 9, 9),
    slot("s2", "Dr Ade", 10, 10),
    slot("s3", "Dr Bala", 9, 9),
    {"id": "p1", "provider": "Dr Bala", "start": "2021-01-01T09:00:00Z", "end": "2021-01-01T09:30:00Z"},
    slot("f1", "Dr Chu", 11, 11),
]


# ---------------------------------------------------------------- reset
st, body, hdr = req("POST", "/reset", body={"slots": SLOTS})
check("reset returns 200", st == 200, f"{st} {body}")

# ---------------------------------------------------------------- level 2: auth
st, body, _ = req("GET", "/slots", key="")
check("missing key -> 401", st == 401, f"{st} {body}")
st, body, _ = req("GET", "/slots", key="wrong-key")
check("wrong key -> 401", st == 401, f"{st} {body}")
st, body, _ = req("POST", "/bookings", key="", body={"slot_id": "s1", "name": "x", "email": "x@y.co"})
check("booking without key -> 401", st == 401, f"{st} {body}")
st, body, _ = req("DELETE", "/bookings/nope", key="")
check("delete without key -> 401", st == 401, f"{st} {body}")

# ---------------------------------------------------------------- level 1: slots listing
st, body, _ = req("GET", "/slots")
check("slots list 200", st == 200, f"{st}")
slots = body["slots"]
ids = [s["id"] for s in slots]
check("slots ordered by start (past first, tie by id)", ids == ["p1", "s1", "s3", "s2", "f1"], str(ids))
check("slot shape", all({"id", "provider", "start", "end", "available"} <= set(s) for s in slots))
check("all available initially", all(s["available"] for s in slots), str([s for s in slots if not s["available"]]))
zcheck = all(s["start"].endswith("Z") for s in slots)
check("datetimes end with Z", zcheck, str([s["start"] for s in slots]))

st, body, _ = req("GET", "/slots?provider=Dr%20Bala")
check("provider filter exact", [s["id"] for s in body["slots"]] == ["p1", "s3"], str(body))

# ---------------------------------------------------------------- level 1 basic booking + lookup
st, b1, _ = req("POST", "/bookings", body={"slot_id": "s1", "name": "Ada Obi", "email": "Ada@Example.COM "})
check("book returns 201", st == 201, f"{st} {b1}")
check("booking shape", isinstance(b1, dict) and all(k in b1 for k in ("id", "slot_id", "name", "email", "status", "created_at")), str(b1))
check("status confirmed", b1.get("status") == "confirmed", str(b1))
check("email trimmed+lowercased", b1.get("email") == "ada@example.com" and b1.get("name") == "Ada Obi", str(b1))

st, got, _ = req("GET", f"/bookings/{b1['id']}")
check("lookup by id 200", st == 200 and got.get("id") == b1["id"], f"{st} {got}")
st, err, _ = req("GET", "/bookings/does-not-exist")
check("lookup unknown id -> 404", st == 404 and "error" in err, f"{st} {err}")
st, err, _ = req("GET", "/bookings/not-a-uuid")
check("lookup invalid id -> 404", st == 404, f"{st} {err}")

st, body, _ = req("GET", "/slots")
s1row = next(s for s in body["slots"] if s["id"] == "s1")
check("booked slot no longer available", s1row["available"] is False, str(s1row))

# ---------------------------------------------------------------- level 2: validation
def book(**kw):
    payload = {"slot_id": "s2", "name": "Bo Dia", "email": "bo@example.com"}
    payload.update(kw)
    return req("POST", "/bookings", body=payload)

st, err, _ = book(name="   ")
check("blank name -> 400", st == 400 and "error" in err, f"{st} {err}")
st, err, _ = book(email="", name="   ")
check("blank name+email -> 400 (first error surfaced)", st == 400 and "error" in err, f"{st} {err}")
st, err, _ = book(email="not-an-email")
check("invalid email -> 400", st == 400, f"{st} {err}")
st, err, _ = book(slot_id="ghost")
check("unknown slot -> 404", st == 404 and "error" in err, f"{st} {err}")
st, err, _ = book(slot_id="p1")
check("past slot -> 400 already started", st == 400 and "error" in err, f"{st} {err}")
st, err, _ = book()
payload = {"slot_id": "s2", "name": "Bo Dia", "email": "bo@example.com"}
del payload["email"]
st, err, _ = req("POST", "/bookings", body=payload)
check("missing email -> 400", st == 400, f"{st} {err}")
st, err, _ = req("POST", "/bookings", body=[1, 2])
check("non-object body -> 400", st == 400, f"{st} {err}")

# ---------------------------------------------------------------- level 3: conflict + cancel + race
st, err, _ = req("POST", "/bookings", body={"slot_id": "s1", "name": "Cee Dia", "email": "cee@example.com"})
check("same slot again -> 409", st == 409 and "error" in err, f"{st} {err}")

st, cc, _ = req("DELETE", f"/bookings/{b1['id']}")
check("cancel -> 200 cancelled", st == 200 and cc.get("status") == "cancelled", f"{st} {cc}")
st, err, _ = req("DELETE", f"/bookings/{b1['id']}")
check("cancel twice -> 409", st == 409 and "error" in err, f"{st} {err}")
st, body, _ = req("GET", "/slots")
s1row = next(s for s in body["slots"] if s["id"] == "s1")
check("cancelled slot is available again", s1row["available"] is True, str(s1row))
st, re_booked, _ = req("POST", "/bookings", body={"slot_id": "s1", "name": "Cee Dia", "email": "cee@example.com"})
check("slot rebookable after cancel", st == 201, f"{st} {re_booked}")

req("POST", "/reset", body={"slots": SLOTS[:3]})
racers = 12
with concurrent.futures.ThreadPoolExecutor(max_workers=racers) as pool:
    futures = [
        pool.submit(req, "POST", "/bookings", body={"slot_id": "s2", "name": f"Race {i:02}", "email": f"race{i}@example.com"})
        for i in range(racers)
    ]
    results = [f.result()[0] for f in futures]
ones = results.count(201)
nines = results.count(409)
check(f"race: exactly one 201 ({ones}), rest 409 ({nines})",
      ones == 1 and nines == racers - 1, str(sorted(results)))
st, body, _ = req("GET", "/slots")
s2row = next(s for s in body["slots"] if s["id"] == "s2")
check("race: slot shows unavailable", s2row["available"] is False, str(s2row))

# ---------------------------------------------------------------- level 4: idempotency + pagination
req("POST", "/reset", body={"slots": SLOTS})  # fresh full slot set for this phase

st, i1, hdr = req("POST", "/bookings", body={"slot_id": "s1", "name": "Id Em", "email": "idem@example.com"},
                  headers={"Idempotency-Key": "key-42"})
check("first idempotent booking 201", st == 201, f"{st} {i1}")
st, i2, _ = req("POST", "/bookings", body={"slot_id": "s1", "name": "Id Em", "email": "idem@example.com"},
                headers={"Idempotency-Key": "key-42"})
check("replay same key+body -> same response", st == 201 and i2 == i1, f"{st} {i2}")
st, i3, _ = req("POST", "/bookings", body={"slot_id": "s3", "name": "Id Em", "email": "idem@example.com"},
                headers={"Idempotency-Key": "key-42"})
check("same key, different body -> 422", st == 422 and "error" in i3, f"{st} {i3}")
st, i4, _ = req("POST", "/bookings", body={"slot_id": "s1", "name": "Id Em X", "email": "idem@example.com"},
                headers={"Idempotency-Key": "key-42"})
check("same key, different name -> 422", st == 422, f"{st} {i4}")

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures = [
        pool.submit(req, "POST", "/bookings", body={"slot_id": "f1", "name": "Con Duo", "email": "con@example.com"},
                    headers={"Idempotency-Key": "key-duo"})
        for _ in range(4)
    ]
    dup_results = [f.result() for f in futures]
dups_ok = all(s == 201 and b == dup_results[0][1] for s, b, _ in dup_results)
check("concurrent same key+body -> single identical booking", dups_ok,
      str([(s, b.get("id") if isinstance(b, dict) else b) for s, b, _ in dup_results]))

# failed validation under a key is replayed as-is
st, err404, _ = req("POST", "/bookings", body={"slot_id": "ghost", "name": "Id Em", "email": "idem@example.com"},
                    headers={"Idempotency-Key": "key-bad"})
st2, err404_again, _ = req("POST", "/bookings", body={"slot_id": "ghost", "name": "Id Em", "email": "idem@example.com"},
                           headers={"Idempotency-Key": "key-bad"})
check("failed booking replayed (same status)", st == 404 and st2 == 404 and err404 == err404_again, f"{st}/{st2}")

# ---------------------------------------------------------------- pagination
# Re-seed fresh data (resets tables, backdates bookings) and walk pages.
import pathlib
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
subprocess.run([sys.executable, "manage.py", "seed_pagination"], cwd=PROJECT_ROOT, check=True)

st, page1, _ = req("GET", "/bookings?email=paged@example.com&limit=5")
check("page 1 200", st == 200 and len(page1.get("bookings", [])) == 5, f"{st} {page1}")
check("page 1 has next_cursor", bool(page1.get("next_cursor")), str(page1)[:120])
order_ok = len(page1["bookings"]) >= 2 and all(
    page1["bookings"][i]["created_at"] <= page1["bookings"][i + 1]["created_at"]
    for i in range(len(page1["bookings"]) - 1)
)
check("page 1 oldest first", order_ok, str([b["created_at"] for b in page1["bookings"]]))

collected = [b["id"] for b in page1["bookings"]]
cursor = page1["next_cursor"]
pages = 1
while cursor and pages < 10:
    st, pageN, _ = req("GET", f"/bookings?email=PAGED@example.com&limit=5&cursor={cursor}")
    assert st == 200, f"page {pages+1} failed: {st} {pageN}"
    collected.extend(b["id"] for b in pageN["bookings"])
    cursor = pageN["next_cursor"]
    pages += 1
check(f"walked {pages} pages -> 15 unique bookings, last page next_cursor null",
      len(collected) == 15 and len(set(collected)) == 15 and cursor is None, f"n={len(collected)} uniq={len(set(collected))} cursor={cursor}")

for bad in ("0", "51", "abc", "-1"):
    st, err, _ = req("GET", f"/bookings?email=paged@example.com&limit={bad}")
    check(f"invalid limit {bad} -> 400", st == 400 and "error" in err, f"{st} {err}")
st, err, _ = req("GET", "/bookings")
check("missing email -> 400", st == 400, f"{st} {err}")
st, err, _ = req("GET", "/bookings?email=paged@example.com&cursor=!!!not-base64")
check("invalid cursor -> 400", st == 400 and "error" in err, f"{st} {err}")

# ---------------------------------------------------------------- level 5: rate limit
req("POST", "/reset", body={"slots": [{"id": "r1", "provider": "Dr Rate", "start": F.format(9), "end": F.format(9).replace("00:00:00Z", "00:30:00Z")}]})
for n in range(5):
    # five attempts that all fail validation, but each counts against the window
    st, err, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "   ", "email": "spam@example.com"})
    check(f"failed attempt {n+1} -> 400", st == 400, f"{st} {err}")
st, err, hdr = req("POST", "/bookings", body={"slot_id": "r1", "name": "Spam Bot", "email": "spam@example.com"})
check("6th attempt -> 429", st == 429 and "error" in err, f"{st} {err}")
ra = hdr.get("Retry-After")
check("Retry-After is whole seconds >= 1", ra is not None and re.fullmatch(r"\d+", str(ra)) and int(ra) >= 1, str(ra))
st, ok_other, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"})
check("other email unaffected -> 201", st == 201, f"{st} {ok_other}")

# a keyed 409 (slot conflict) is stored; replays keep returning it even after
# the window fills up, and replays never consume attempt quota
keyed = "key-r1-409"
st, keyed409, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"},
                      headers={"Idempotency-Key": keyed})
check("keyed booking on full slot -> 409", st == 409, f"{st} keyed409")
for _ in range(2):
    req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"})  # 409, counts
st, fifth, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"})
check("5th attempt for other still allowed (409 not 429)", st == 409, f"{st}")
st, sixth, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"})
check("6th attempt for other -> 429", st == 429 and "error" in sixth, f"{st}")
st, replayed409, _ = req("POST", "/bookings", body={"slot_id": "r1", "name": "Other Ok", "email": "other@example.com"},
                         headers={"Idempotency-Key": keyed})
check("idempotent replay bypasses the limiter", st == 409 and replayed409 == keyed409, f"{st} {replayed409}")

# ---------------------------------------------------------------- web page
st, html, _ = req("GET", "/", key="")
check("web page 200 served without key", st == 200 and "<body" in str(html), f"{st}")
st, css, _ = req("GET", "/static/booking/app.js", key="")
check("app.js served", st == 200, f"{st}")

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} checks: {FAILURES}")
    sys.exit(1)
print("ALL CHECKS PASSED")
