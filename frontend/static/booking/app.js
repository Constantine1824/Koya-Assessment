(() => {
  "use strict";

  const cfg = window.CLINIC_CONFIG || {};
  // Same-origin by default; set apiBase to host the page elsewhere.
  const API_BASE = (cfg.apiBase || document.body.dataset.apiBase || "").replace(/\/+$/, "");

  // Key precedence: one saved by the user in this browser wins over the
  // server-provided default (so alternate keys work without redeploy).
  function storedUserKey() {
    try { return localStorage.getItem("clinicApiKey"); } catch { return null; }
  }
  function resolveKey() {
    return storedUserKey() || cfg.apiKey || document.body.dataset.apiKey || "";
  }
  let API_KEY = resolveKey();

  const $ = (sel) => document.querySelector(sel);

  const state = {
    slots: [],
    byId: new Map(),
    idemKey: null,
    bookings: { email: null, items: [], next: null },
  };

  // ------------------------------------------------------------------ helpers

  function showBanner(message, kind = "error", stayMs = 8000) {
    const el = $("#banner");
    el.textContent = message;
    el.className = kind === "ok" ? "banner ok" : "banner";
    el.hidden = false;
    if (stayMs) setTimeout(() => { el.hidden = true; }, stayMs);
  }

  function hideBanner() { $("#banner").hidden = true; }

  async function api(path, options = {}) {
    try {
      const res = await fetch(API_BASE + path, {
        method: options.method || "GET",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_KEY,
          ...(options.headers || {}),
        },
        body: options.body ? JSON.stringify(options.body) : undefined,
      });
      let data = null;
      try { data = await res.json(); } catch { /* non-JSON body */ }
      if (res.status === 401) unauthorizedFlow(res.data?.error);
      return { ok: res.ok, status: res.status, data, retryAfter: res.headers.get("Retry-After") };
    } catch {
      return { ok: false, status: 0, data: null, retryAfter: null };
    }
  }

  function unauthorizedFlow(message) {
    showBanner(
      message || "The API rejected the API key — set a new one in the API key dialog.",
      "error", 10000,
    );
    openKeyDialog();
  }

  // ------------------------------------------------------------- key dialog

  function openKeyDialog() {
    $("#key-input").value = storedUserKey() || API_KEY || "";
    setHidden("#key-error", true);
    $("#key-dialog").showModal();
    $("#key-input").focus();
  }

  $("#key-btn").addEventListener("click", openKeyDialog);
  $("#key-cancel").addEventListener("click", () => $("#key-dialog").close());
  $("#key-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = $("#key-input").value.trim();
    try {
      if (value) localStorage.setItem("clinicApiKey", value);
      else localStorage.removeItem("clinicApiKey");
    } catch { /* storage unavailable */ }
    API_KEY = resolveKey();
    $("#key-dialog").close();
    showBanner(
      value ? "API key saved — reloading slots." : "Cleared stored key — using the server key.",
      "ok", 5000,
    );
    loadSlots().catch(() => {});
  });

  const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

  function slotRange(slot) {
    const a = new Date(slot.start);
    const b = new Date(slot.end);
    return `${dayFmt.format(a)} · ${timeFmt.format(a)} – ${timeFmt.format(b)}`;
  }

  function initials(name) {
    return name.split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() || "").join("") || "?";
  }

  function isPast(slot) {
    return new Date(slot.start).getTime() <= Date.now();
  }

  function newIdempotencyKey() {
    return crypto?.randomUUID?.() || `idem-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }

  // ------------------------------------------------------------------- slots

  async function loadSlots() {
    const grid = $("#slot-grid");
    grid.setAttribute("aria-busy", "true");
    const provider = $("#provider-filter").value.trim();
    const res = await api(`/slots${provider ? `?provider=${encodeURIComponent(provider)}` : ""}`);
    // 401s are handled centrally (banner + key dialog) in api().
    if (!res.ok && res.status !== 401) {
      showBanner(res.data?.error || "Could not load slots.");
    }
    state.slots = (res.ok && res.data?.slots) || [];
    state.byId = new Map(state.slots.map((s) => [s.id, s]));
    renderSlots();
    grid.removeAttribute("aria-busy");
  }

  function renderSlots() {
    const grid = $("#slot-grid");
    grid.textContent = "";
    if (!state.slots.length) {
      grid.innerHTML = `<p class="empty">No slots found${$("#provider-filter").value.trim() ? " for this provider" : ""}. Ask the front desk, or press Refresh.</p>`;
      return;
    }
    for (const slot of state.slots) {
      const card = document.createElement("article");
      card.className = "slot-card";
      card.innerHTML = `
        <div class="provider"><span class="avatar" aria-hidden="true"></span><span class="name"></span></div>
        <div class="time"></div>
        <div class="slot-foot">
          <span class="badge"></span>
          <button class="btn" type="button"></button>
        </div>`;
      card.querySelector(".avatar").textContent = initials(slot.provider);
      card.querySelector(".name").textContent = slot.provider;
      card.querySelector(".time").textContent = slotRange(slot);
      const badge = card.querySelector(".badge");
      const btn = card.querySelector("button");
      if (!slot.available) {
        badge.textContent = "Booked";
        badge.className = "badge taken";
        btn.textContent = "Unavailable";
        btn.disabled = true;
      }
      // else if (isPast(slot)) {
      //   badge.textContent = "Started";
      //   badge.className = "badge taken";
      //   btn.textContent = "Started";
      //   btn.disabled = true;
      // }
      else {
        badge.textContent = "Available";
        badge.className = "badge ok";
        btn.textContent = "Book";
        btn.addEventListener("click", () => openBookDialog(slot));
      }
      grid.appendChild(card);
    }
  }

  $("#refresh-slots").addEventListener("click", async () => {
    const status = $("#refresh-status");
    status.textContent = "Refreshing…";
    const res = await api("/refresh-slots", { method: "POST" });
    if (res.status !== 401) {
      if (res.ok && res.data?.refreshed) {
        status.textContent = `Slot times moved to now (${res.data.refreshed} refreshed)`;
      } else if (res.ok) {
        status.textContent = res.data?.reason || "Nothing to refresh";
      } else {
        status.textContent = "Refresh failed — try again";
      }
      setTimeout(() => { status.textContent = ""; }, 6000);
    }
    await loadSlots().catch(() => {});
  });
  let filterTimer = null;
  $("#provider-filter").addEventListener("input", () => {
    clearTimeout(filterTimer);
    filterTimer = setTimeout(() => loadSlots().catch(() => {}), 250);
  });

  // ------------------------------------------------------------------ booking

  function openBookDialog(slot) {
    const dlg = $("#book-dialog");
    state.idemKey = newIdempotencyKey();
    $("#dialog-time").textContent = `${slot.provider} · ${slotRange(slot)}`;
    $("#book-name").value = $("#book-name").value || "";
    $("#book-email").value = $("#book-email").value;
    setHidden("#dialog-error", true);
    $("#dialog-submit").disabled = false;
    $("#dialog-submit").textContent = "Confirm booking";
    dlg.dataset.slotId = slot.id;
    $("#book-name").focus();
    dlg.showModal();
  }

  function setHidden(sel, hidden) { $(sel).hidden = hidden; }

  function dialogError(message) {
    $("#dialog-error").textContent = message;
    setHidden("#dialog-error", false);
  }

  function startRetryCountdown(seconds) {
    const btn = $("#dialog-submit");
    let left = Math.max(1, parseInt(seconds, 10) || 0);
    btn.disabled = true;
    const tick = () => {
      if (left <= 0) { btn.disabled = false; btn.textContent = "Confirm booking"; return; }
      btn.textContent = `Rate limited — retry in ${left}s`;
      left -= 1;
      setTimeout(tick, 1000);
    };
    tick();
  }

  $("#dialog-cancel").addEventListener("click", () => {
    $("#book-dialog").close();
    state.idemKey = null;
  });

  $("#book-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const dlg = $("#book-dialog");
    const name = $("#book-name").value.trim();
    const email = $("#book-email").value.trim();
    setHidden("#dialog-error", true);
    if (!name || !email) { dialogError("Please enter your name and email."); return; }
    const btn = $("#dialog-submit");
    btn.disabled = true;
    btn.textContent = "Booking…";
    const res = await api("/bookings", {
      method: "POST",
      headers: { "Idempotency-Key": state.idemKey },
      body: { slot_id: dlg.dataset.slotId, name, email },
    });
    btn.disabled = false;
    btn.textContent = "Confirm booking";

    if (res.status === 0) {
      dialogError("Network error while contacting the server. Press “Confirm booking” again — this retry is safe (same idempotency key).");
      return;
    }

    if (res.status === 201 && res.data?.id) {
      dlg.close();
      state.idemKey = null;
      try { localStorage.setItem("clinicEmail", email); } catch { /* private mode */ }
      $("#book-email").value = email;
      $("#book-name").value = name;
      showConfirmation(res.data, state.byId.get(dlg.dataset.slotId));
      loadSlots().catch(() => {});
      const lookupEmail = $("#lookup-email");
      if (state.bookings.email === email.toLowerCase() || !lookupEmail.value.trim()) {
        lookupEmail.value = email;
        $("#lookup-form").requestSubmit();
      }
      return;
    }

    if (res.status === 429) {
      dialogError(res.data?.error || "Too many attempts — please wait a moment.");
      startRetryCountdown(res.retryAfter || 30);
      return;
    }

    if (res.status === 409) { loadSlots().catch(() => {}); }
    dialogError(res.data?.error || "Booking failed. Please try again.");
  });

  // ------------------------------------------------------------- confirmation

  function showConfirmation(booking, slot) {
    $("#confirm-slot").textContent = slot
      ? `${slot.provider} · ${slotRange(slot)}`
      : `Slot ${booking.slot_id}`;
    $("#confirm-ref").textContent = booking.id;
    $("#confirm-name").textContent = booking.name;
    $("#confirm-email").textContent = booking.email;
    $("#confirm-created").textContent = new Date(booking.created_at).toLocaleString();
    $("#confirm-status").textContent = booking.status;
    $("#confirmation").hidden = false;
  }

  $("#confirm-close").addEventListener("click", () => { $("#confirmation").hidden = true; });
  $("#confirmation").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) e.currentTarget.hidden = true;
  });

  // ------------------------------------------------------- my bookings (L4+L3)

  function shortRef(id) { return id.slice(0, 8); }

  async function loadBookings({ append = false } = {}) {
    const email = $("#lookup-email").value.trim().toLowerCase();
    if (!email) { showBanner("Enter an email to find your bookings."); return; }
    const params = new URLSearchParams({ email, limit: "10" });
    if (append && state.bookings.next) params.set("cursor", state.bookings.next);
    const res = await api(`/bookings?${params}`);
    if (!res.ok) {
      showBanner(res.data?.error || "Could not load bookings.");
      return;
    }
    const page = res.data || { bookings: [], next_cursor: null };
    state.bookings.email = email;
    state.bookings.items = append ? state.bookings.items.concat(page.bookings) : page.bookings;
    state.bookings.next = page.next_cursor;
    $("#load-more").hidden = !page.next_cursor;
    renderBookings();
  }

  function renderBookings() {
    const list = $("#booking-list");
    list.textContent = "";
    if (!state.bookings.items.length) {
      list.innerHTML = `<p class="empty">No bookings for this address yet.</p>`;
      return;
    }
    for (const booking of state.bookings.items) {
      const slot = state.byId.get(booking.slot_id);
      const card = document.createElement("article");
      card.className = "booking-card";
      card.innerHTML = `
        <div class="line1">
          <span class="provider"></span>
          <span class="badge"></span>
        </div>
        <div class="time"></div>
        <div class="line2">
          <code class="ref"></code>
          <button class="btn danger cancel" type="button">Cancel</button>
        </div>`;
      card.querySelector(".provider").textContent = slot ? slot.provider : `Slot ${booking.slot_id}`;
      card.querySelector(".time").textContent = slot ? slotRange(slot) : "slot details unavailable";
      card.querySelector(".ref").textContent = booking.id;
      const badge = card.querySelector(".badge");
      const btn = card.querySelector("button.cancel");
      const cancelled = booking.status === "cancelled";
      badge.textContent = booking.status;
      badge.className = cancelled ? "badge cancelled" : "badge ok";
      if (cancelled) {
        btn.hidden = true;
      } else {
        btn.addEventListener("click", () => cancelBooking(booking.id, btn, card));
      }
      list.appendChild(card);
    }
  }

  async function cancelBooking(id, btn, card) {
    if (btn.dataset.confirm !== "1") {
      btn.dataset.confirm = "1";
      btn.textContent = "Confirm cancel";
      setTimeout(() => { btn.dataset.confirm = ""; btn.textContent = "Cancel"; }, 4000);
      return;
    }
    btn.disabled = true;
    btn.textContent = "Cancelling…";
    const res = await api(`/bookings/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (res.ok && res.data?.status === "cancelled") {
      card.querySelector(".badge").textContent = "cancelled";
      card.querySelector(".badge").className = "badge cancelled";
      btn.hidden = true;
      showBanner("Booking cancelled — the slot is open again.", "ok");
      loadSlots().catch(() => {});
    } else if (res.status === 0) {
      btn.disabled = false;
      btn.textContent = "Confirm cancel";
      showBanner("Network error — please try again.");
    } else {
      showBanner(res.data?.error || "Could not cancel this booking.");
      btn.disabled = false;
      btn.dataset.confirm = "";
      btn.textContent = "Confirm cancel";
    }
  }

  $("#lookup-form").addEventListener("submit", (e) => {
    e.preventDefault();
    loadBookings().catch(() => {});
  });
  $("#load-more").addEventListener("click", () => loadBookings({ append: true }).catch(() => {}));

  // -------------------------------------------------------------------- init

  try {
    const saved = localStorage.getItem("clinicEmail");
    if (saved) $("#lookup-email").value = saved;
  } catch { /* private mode */ }
  loadSlots().catch(() => showBanner("Could not reach the server."));
})();
