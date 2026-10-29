/**
 * RFQ Form — dynamic runs, Leaflet maps, pricing sync
 */

(function () {
  "use strict";

  let runIndex = 0;
  const runsContainer = document.getElementById("runs-container");
  const pricingBody = document.getElementById("pricing-body");
  const runsJsonInput = document.getElementById("runs_json");
  const totalRunsInput = document.getElementById("total_runs");
  const form = document.getElementById("rfq-form");

  // Store Leaflet map instances per run so we can clean up
  const maps = {};

  // ---------- Helpers ----------

  async function fetchReservationNumber() {
    try {
      // ✅ UPDATED: Added /quotation prefix
      const res = await fetch("/quotation/api/reservation-number");
      const data = await res.json();
      return data.reservation_number;
    } catch {
      return String(Math.floor(100000 + Math.random() * 900000));
    }
  }

  function escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }


  // ---------- ORS address autocomplete ----------

  function attachAutocomplete(input) {
    if (input.dataset.acAttached) return;
    input.dataset.acAttached = "1";

    const wrap = document.createElement("div");
    wrap.className = "ac-wrap";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);

    const list = document.createElement("ul");
    list.className = "ac-list";
    list.hidden = true;
    wrap.appendChild(list);

    let timer = null;
    let activeIdx = -1;

    function hide() {
      list.hidden = true;
      list.innerHTML = "";
      activeIdx = -1;
    }

    function showSuggestions(features) {
      list.innerHTML = "";
      activeIdx = -1;
      if (!features.length) {
        hide();
        return;
      }
      features.forEach((f, i) => {
        const li = document.createElement("li");
        li.textContent = f.label;
        li.dataset.label = f.label;
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          input.value = f.label;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          hide();
        });
        list.appendChild(li);
      });
      list.hidden = false;
    }

    input.addEventListener("input", () => {
      const q = input.value.trim();
      clearTimeout(timer);
      if (q.length < 2) {
        hide();
        return;
      }
      timer = setTimeout(async () => {
        try {
          // ✅ UPDATED: Added /quotation prefix
          const res = await fetch("/quotation/api/geocode/autocomplete?text=" + encodeURIComponent(q));
          const data = await res.json();
          showSuggestions(data.features || []);
        } catch (err) {
          console.warn("Autocomplete failed", err);
          hide();
        }
      }, 280);
    });

    input.addEventListener("keydown", (e) => {
      const items = list.querySelectorAll("li");
      if (list.hidden || !items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeIdx = Math.min(activeIdx + 1, items.length - 1);
        items.forEach((li, i) => li.classList.toggle("active", i === activeIdx));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        activeIdx = Math.max(activeIdx - 1, 0);
        items.forEach((li, i) => li.classList.toggle("active", i === activeIdx));
      } else if (e.key === "Enter" && activeIdx >= 0) {
        e.preventDefault();
        input.value = items[activeIdx].dataset.label;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        hide();
      } else if (e.key === "Escape") {
        hide();
      }
    });

    input.addEventListener("blur", () => setTimeout(hide, 150));
  }

  // ---------- Create a run card ----------

  async function addRun(prefill = null) {
    const idx = runIndex++;
    const resNum = prefill?.reservation_number || (await fetchReservationNumber());

    const card = document.createElement("div");
    card.className = "run-card";
    card.dataset.idx = idx;
    card.innerHTML = `
      <div class="run-card-header">
        <h3>Run <span class="run-label">${idx + 1}</span> &mdash; Res. # <span class="res-num">${escapeHtml(resNum)}</span></h3>
        <button type="button" class="btn-remove" data-idx="${idx}">Remove</button>
      </div>

      <input type="hidden" class="f-reservation" value="${escapeHtml(resNum)}" />

      <div class="grid-2">
        <div class="field">
          <label>Date <span class="req">*</span></label>
          <input type="date" class="f-date" required value="${prefill?.date || ""}" />
        </div>
        <div class="field">
          <label>Pick-Up Time <span class="req">*</span></label>
          <input type="time" class="f-pickup-time" required value="${prefill?.pickup_time || ""}" />
        </div>
      </div>

      <div class="grid-2">
        <div class="field">
          <label>Passengers</label>
          <input type="text" class="f-passengers" placeholder="e.g. 55 or 1 bus"
                 value="${escapeHtml(prefill?.passengers || "")}" />
        </div>
        <div class="field">
          <label>Type <span class="req">*</span></label>
          <select class="f-type" required>
            <option value="">— Select type —</option>
            <option value="Airport Transfer" ${prefill?.type === "Airport Transfer" ? "selected" : ""}>Airport Transfer</option>
            <option value="Shuttle (Hourly)" ${prefill?.type === "Shuttle (Hourly)" ? "selected" : ""}>Shuttle (Hourly)</option>
            <option value="Limo (Hourly)" ${prefill?.type === "Limo (Hourly)" ? "selected" : ""}>Limo (Hourly)</option>
          </select>
        </div>
      </div>

      <div class="field">
        <label>Pickup Location <span class="req">*</span></label>
        <div class="addr-row">
          <input type="text" class="f-pickup-loc" required
                 placeholder="Start typing address or use map…"
                 value="${escapeHtml(prefill?.pickup_location || "")}" />
          <button type="button" class="btn-map btn-pick-map" data-idx="${idx}" data-target="pickup">Map</button>
        </div>
        <div class="map-box" id="map-pickup-${idx}" style="display:none;"></div>
      </div>

      <div class="field">
        <label>Drop-Off Location <span class="req">*</span></label>
        <div class="addr-row">
          <input type="text" class="f-dropoff-loc" required
                 placeholder="Start typing address or use map…"
                 value="${escapeHtml(prefill?.dropoff_location || "")}" />
          <button type="button" class="btn-map btn-drop-map" data-idx="${idx}" data-target="dropoff">Map</button>
        </div>
        <div class="map-box" id="map-dropoff-${idx}" style="display:none;"></div>
      </div>

      <div class="field">
        <label>Loop / Flight Details</label>
        <textarea class="f-loop" rows="2"
                  placeholder="e.g. 3 loops • AA 3458 from ORD – ETA 18:06">${escapeHtml(prefill?.loop_details || "")}</textarea>
      </div>
    `;

    runsContainer.appendChild(card);

    // Address autocomplete on pickup / drop-off
    card.querySelectorAll(".f-pickup-loc, .f-dropoff-loc").forEach(attachAutocomplete);

    // Remove button
    card.querySelector(".btn-remove").addEventListener("click", () => {
      // Clean up maps
      ["pickup", "dropoff"].forEach((t) => {
        const key = `${t}-${idx}`;
        if (maps[key]) {
          maps[key].remove();
          delete maps[key];
        }
      });
      card.remove();
      renumberRuns();
      syncPricing();
      updateTotalRunsField();
    });

    // Map toggle buttons
    card.querySelectorAll(".btn-map").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.dataset.target;
        const mapId = `map-${target}-${idx}`;
        const mapEl = document.getElementById(mapId);
        if (mapEl.style.display === "none") {
          mapEl.style.display = "block";
          initMap(idx, target, mapEl, card);
        } else {
          mapEl.style.display = "none";
        }
      });
    });

    // Live sync pricing when fields change
    card.querySelectorAll("input, select, textarea").forEach((el) => {
      el.addEventListener("change", () => {
        syncPricing();
        updateTotalRunsField();
      });
      el.addEventListener("input", () => {
        // Debounced light update for text
        if (el.classList.contains("f-pickup-loc") || el.classList.contains("f-dropoff-loc") ||
            el.classList.contains("f-date") || el.classList.contains("f-type")) {
          syncPricing();
        }
      });
    });

    syncPricing();
    updateTotalRunsField();
    return card;
  }

  function renumberRuns() {
    const cards = runsContainer.querySelectorAll(".run-card");
    cards.forEach((card, i) => {
      card.querySelector(".run-label").textContent = i + 1;
    });
  }

  function updateTotalRunsField() {
    const n = runsContainer.querySelectorAll(".run-card").length;
    if (!totalRunsInput.dataset.manual) {
      totalRunsInput.value = n ? `${n} run${n !== 1 ? "s" : ""}` : "";
    }
  }

  totalRunsInput.addEventListener("input", () => {
    totalRunsInput.dataset.manual = "1";
  });

  // ---------- Leaflet map with Nominatim geocoder ----------

  function initMap(idx, target, mapEl, card) {
    const key = `${target}-${idx}`;
    if (maps[key]) {
      maps[key].invalidateSize();
      return;
    }

    // Center on Iowa City area by default
    const map = L.map(mapEl).setView([41.6611, -91.5302], 10);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap",
      maxZoom: 18,
    }).addTo(map);

    const geocoder = L.Control.geocoder({
      defaultMarkGeocode: false,
      placeholder: "Search address (Iowa preferred)…",
      geocoder: L.Control.Geocoder.nominatim({
        geocodingQueryParams: {
          // Bias toward Iowa / Midwest
          countrycodes: "us",
          viewbox: "-96.7,40.3,-90.1,43.6", // rough Iowa bounding box
          bounded: 0, // still allow outside Iowa
        },
      }),
    })
      .on("markgeocode", (e) => {
        const { center, name, bbox } = e.geocode;
        map.fitBounds(bbox);
        L.marker(center).addTo(map);
        // Write address into the corresponding input
        const inputCls = target === "pickup" ? ".f-pickup-loc" : ".f-dropoff-loc";
        const input = card.querySelector(inputCls);
        if (input) {
          input.value = name;
          input.dispatchEvent(new Event("change"));
        }
      })
      .addTo(map);

    // Also allow click-to-set (reverse geocode)
    map.on("click", async (ev) => {
      try {
        const url = `https://nominatim.openstreetmap.org/reverse?format=json&lat=${ev.latlng.lat}&lon=${ev.latlng.lng}`;
        const res = await fetch(url, { headers: { "Accept-Language": "en" } });
        const data = await res.json();
        const addr = data.display_name || `${ev.latlng.lat.toFixed(5)}, ${ev.latlng.lng.toFixed(5)}`;
        L.marker(ev.latlng).addTo(map);
        const inputCls = target === "pickup" ? ".f-pickup-loc" : ".f-dropoff-loc";
        const input = card.querySelector(inputCls);
        if (input) {
          input.value = addr;
          input.dispatchEvent(new Event("change"));
        }
      } catch (err) {
        console.warn("Reverse geocode failed", err);
      }
    });

    maps[key] = map;
    // Leaflet needs a tick after becoming visible
    setTimeout(() => map.invalidateSize(), 100);
  }

  // ---------- Collect runs data ----------

  function collectRuns() {
    const cards = runsContainer.querySelectorAll(".run-card");
    const runs = [];
    cards.forEach((card) => {
      runs.push({
        reservation_number: card.querySelector(".f-reservation")?.value || "",
        date: card.querySelector(".f-date")?.value || "",
        pickup_time: card.querySelector(".f-pickup-time")?.value || "",
        passengers: card.querySelector(".f-passengers")?.value || "",
        type: card.querySelector(".f-type")?.value || "",
        pickup_location: card.querySelector(".f-pickup-loc")?.value || "",
        dropoff_location: card.querySelector(".f-dropoff-loc")?.value || "",
        loop_details: card.querySelector(".f-loop")?.value || "",
        quoted_rate: null, // filled from pricing table
      });
    });
    return runs;
  }

  // ---------- Pricing table sync ----------

  function syncPricing() {
    const runs = collectRuns();
    // Preserve existing rates by reservation number
    const existingRates = {};
    pricingBody.querySelectorAll("tr[data-res]").forEach((tr) => {
      const res = tr.dataset.res;
      const input = tr.querySelector(".rate-input");
      if (res && input) existingRates[res] = input.value;
    });

    pricingBody.innerHTML = "";

    if (runs.length === 0) {
      pricingBody.innerHTML = `<tr class="empty-row"><td colspan="5">Add runs in Section 2 to enter pricing</td></tr>`;
      document.getElementById("run-count").textContent = "0";
      document.getElementById("grand-total").textContent = "0.00";
      return;
    }

    let grand = 0;
    runs.forEach((r) => {
      const rateVal = existingRates[r.reservation_number] ?? "";
      const tr = document.createElement("tr");
      tr.dataset.res = r.reservation_number;
      const route = `${r.pickup_location || "…"} → ${r.dropoff_location || "…"}`;
      tr.innerHTML = `
        <td>${escapeHtml(r.reservation_number)}</td>
        <td>${escapeHtml(r.date)}</td>
        <td>${escapeHtml(r.type)}</td>
        <td>${escapeHtml(route)}</td>
        <td>
          <input type="number" class="rate-input" step="0.01" min="0"
                 placeholder="0.00" value="${escapeHtml(rateVal)}"
                 data-res="${escapeHtml(r.reservation_number)}" />
        </td>
      `;
      pricingBody.appendChild(tr);

      const num = parseFloat(rateVal);
      if (!isNaN(num)) grand += num;
    });

    document.getElementById("run-count").textContent = String(runs.length);
    document.getElementById("grand-total").textContent = grand.toFixed(2);

    // Re-bind rate inputs
    pricingBody.querySelectorAll(".rate-input").forEach((input) => {
      input.addEventListener("input", recalcTotal);
      input.addEventListener("change", recalcTotal);
    });
  }

  function recalcTotal() {
    let grand = 0;
    pricingBody.querySelectorAll(".rate-input").forEach((input) => {
      const n = parseFloat(input.value);
      if (!isNaN(n)) grand += n;
    });
    document.getElementById("grand-total").textContent = grand.toFixed(2);
  }

  // ---------- Form submit ----------

  form.addEventListener("submit", (e) => {
    const runs = collectRuns();

    // Attach quoted rates from pricing table
    const rateMap = {};
    pricingBody.querySelectorAll(".rate-input").forEach((input) => {
      rateMap[input.dataset.res] = input.value;
    });
    runs.forEach((r) => {
      r.quoted_rate = rateMap[r.reservation_number] || null;
    });

    if (runs.length === 0) {
      e.preventDefault();
      alert("Please add at least one run in Section 2 (Service Schedule).");
      return;
    }

    // Basic validation
    for (const r of runs) {
      if (!r.date || !r.pickup_time || !r.type || !r.pickup_location || !r.dropoff_location) {
        e.preventDefault();
        alert("Please complete all required fields (date, time, type, pickup & drop-off) for every run.");
        return;
      }
    }

    runsJsonInput.value = JSON.stringify(runs);
    // Allow normal form submit → PDF download
  });

  // ---------- Init ----------

  document.getElementById("btn-add-run").addEventListener("click", () => addRun());

  // Start with one empty run
  addRun();
})();