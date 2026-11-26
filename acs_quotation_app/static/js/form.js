
/**
 * ACS Quotation Generator
 * Dynamic service runs, address autocomplete, Leaflet maps and pricing.
 */

(function () {
    "use strict";

    let runIndex = 0;

    const runsContainer = document.getElementById("runs-container");
    const pricingBody = document.getElementById("pricing-body");
    const runsJsonInput = document.getElementById("runs_json");
    const totalRunsInput = document.getElementById("total_runs");
    const form = document.getElementById("rfq-form");

    const maps = {};
    const mapMarkers = {};

    // =====================================================
    // HELPERS
    // =====================================================

    async function fetchReservationNumber() {
        try {
            const response = await fetch(
                "/quotation/api/reservation-number"
            );

            if (!response.ok) {
                throw new Error("Reservation API request failed");
            }

            const data = await response.json();

            if (!data.reservation_number) {
                throw new Error("Reservation number missing");
            }

            return String(data.reservation_number);

        } catch (error) {
            console.warn("Reservation number fallback:", error);

            return String(
                Math.floor(100000 + Math.random() * 900000)
            );
        }
    }


    function escapeHtml(value) {
        if (!value) return "";

        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }


    function getRunCards() {
        return runsContainer.querySelectorAll(".run-card");
    }


    // =====================================================
    // ADDRESS AUTOCOMPLETE
    // =====================================================

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
        let requestController = null;
        let requestSequence = 0;


        function hide() {
            list.hidden = true;
            list.innerHTML = "";
            activeIdx = -1;
        }


        function selectSuggestion(label) {
            input.value = label;

            input.dispatchEvent(
                new Event("change", { bubbles: true })
            );

            hide();
        }


        function showSuggestions(features) {

            list.innerHTML = "";
            activeIdx = -1;

            if (!features || !features.length) {
                hide();
                return;
            }

            features.forEach((feature) => {

                const li = document.createElement("li");

                li.textContent = feature.label;
                li.dataset.label = feature.label;

                li.addEventListener("mousedown", (event) => {
                    event.preventDefault();
                    selectSuggestion(feature.label);
                });

                list.appendChild(li);
            });

            list.hidden = false;
        }


        input.addEventListener("input", () => {

            const query = input.value.trim();

            clearTimeout(timer);

            if (requestController) {
                requestController.abort();
                requestController = null;
            }

            if (query.length < 2) {
                hide();
                return;
            }

            const currentSequence = ++requestSequence;

            timer = setTimeout(async () => {

                try {

                    requestController = new AbortController();

                    const response = await fetch(
                        "/quotation/api/geocode/autocomplete?text=" +
                        encodeURIComponent(query),
                        {
                            signal: requestController.signal
                        }
                    );

                    if (!response.ok) {
                        throw new Error("Autocomplete request failed");
                    }

                    const data = await response.json();

                    // Ignore outdated responses.
                    if (currentSequence !== requestSequence) {
                        return;
                    }

                    // Do not show suggestions for an input
                    // that has changed since the request started.
                    if (input.value.trim() !== query) {
                        return;
                    }

                    showSuggestions(data.features || []);

                } catch (error) {

                    if (error.name !== "AbortError") {
                        console.warn("Autocomplete failed:", error);
                    }

                }

            }, 280);

        });


        input.addEventListener("keydown", (event) => {

            const items = list.querySelectorAll("li");

            if (list.hidden || !items.length) return;

            if (event.key === "ArrowDown") {

                event.preventDefault();

                activeIdx = Math.min(
                    activeIdx + 1,
                    items.length - 1
                );

            } else if (event.key === "ArrowUp") {

                event.preventDefault();

                activeIdx = Math.max(
                    activeIdx - 1,
                    0
                );

            } else if (
                event.key === "Enter" &&
                activeIdx >= 0
            ) {

                event.preventDefault();

                selectSuggestion(
                    items[activeIdx].dataset.label
                );

                return;

            } else if (event.key === "Escape") {

                hide();
                return;

            } else {
                return;
            }

            items.forEach((item, index) => {
                item.classList.toggle(
                    "active",
                    index === activeIdx
                );
            });

        });


        input.addEventListener("blur", () => {
            setTimeout(hide, 150);
        });

    }


    // =====================================================
    // CREATE A SERVICE RUN
    // =====================================================

    async function addRun(prefill = null) {

        const idx = runIndex++;

        const reservationNumber =
            prefill?.reservation_number ||
            await fetchReservationNumber();

        const card = document.createElement("div");

        card.className = "run-card";
        card.dataset.idx = idx;

        card.innerHTML = `

            <div class="run-card-header">

                <h3>
                    Run <span class="run-label">${idx + 1}</span>
                    &mdash;
                    Res. # <span class="res-num">${escapeHtml(reservationNumber)}</span>
                </h3>

                <button
                    type="button"
                    class="btn-remove"
                    data-idx="${idx}">
                    <i class="bi bi-trash3"></i>
                    Remove
                </button>

            </div>

            <input
                type="hidden"
                class="f-reservation"
                value="${escapeHtml(reservationNumber)}"
            />


            <div class="grid-2">

                <div class="field">
                    <label>Date <span class="req">*</span></label>

                    <input
                        type="date"
                        class="f-date"
                        required
                        value="${escapeHtml(prefill?.date || "")}"
                    />
                </div>


                <div class="field">
                    <label>Pick-Up Time <span class="req">*</span></label>

                    <input
                        type="time"
                        class="f-pickup-time"
                        required
                        value="${escapeHtml(prefill?.pickup_time || "")}"
                    />
                </div>

            </div>


            <div class="grid-2">

                <div class="field">
                    <label>Passengers</label>

                    <input
                        type="text"
                        class="f-passengers"
                        placeholder="e.g. 55 or 1 bus"
                        value="${escapeHtml(prefill?.passengers || "")}"
                    />
                </div>


                <div class="field">
                    <label>Type <span class="req">*</span></label>

                    <select class="f-type" required>

                        <option value="">Select service type</option>

                        <option value="Airport Transfer"
                            ${prefill?.type === "Airport Transfer" ? "selected" : ""}>
                            Airport Transfer
                        </option>

                        <option value="Shuttle (Hourly)"
                            ${prefill?.type === "Shuttle (Hourly)" ? "selected" : ""}>
                            Shuttle (Hourly)
                        </option>

                        <option value="Limo (Hourly)"
                            ${prefill?.type === "Limo (Hourly)" ? "selected" : ""}>
                            Limo (Hourly)
                        </option>

                        <option value="Van (Hourly)"
                            ${prefill?.type === "Van (Hourly)" ? "selected" : ""}>
                            Van (Hourly)
                        </option>

                    </select>
                </div>

            </div>


            <div class="field">

                <label>Pickup Location <span class="req">*</span></label>

                <div class="addr-row">

                    <input
                        type="text"
                        class="f-pickup-loc"
                        required
                        placeholder="Start typing address or use map..."
                        value="${escapeHtml(prefill?.pickup_location || "")}"
                    />

                    <button
                        type="button"
                        class="btn-map btn-pick-map"
                        data-idx="${idx}"
                        data-target="pickup">

                        <i class="bi bi-map"></i>
                        Map

                    </button>

                </div>

                <div
                    class="map-box"
                    id="map-pickup-${idx}"
                    style="display:none;">
                </div>

            </div>


            <div class="field">

                <label>Drop-Off Location <span class="req">*</span></label>

                <div class="addr-row">

                    <input
                        type="text"
                        class="f-dropoff-loc"
                        required
                        placeholder="Start typing address or use map..."
                        value="${escapeHtml(prefill?.dropoff_location || "")}"
                    />

                    <button
                        type="button"
                        class="btn-map btn-drop-map"
                        data-idx="${idx}"
                        data-target="dropoff">

                        <i class="bi bi-map"></i>
                        Map

                    </button>

                </div>

                <div
                    class="map-box"
                    id="map-dropoff-${idx}"
                    style="display:none;">
                </div>

            </div>


            <div class="field">

                <label>Loop / Flight Details</label>

                <textarea
                    class="f-loop"
                    rows="2"
                    placeholder="e.g. 3 loops • AA 3458 from ORD – ETA 18:06">${escapeHtml(prefill?.loop_details || "")}</textarea>

            </div>

        `;


        runsContainer.appendChild(card);


        // Attach autocomplete.
        card.querySelectorAll(
            ".f-pickup-loc, .f-dropoff-loc"
        ).forEach(attachAutocomplete);


        // ---------------------------------------------
        // Remove run
        // ---------------------------------------------

        card.querySelector(".btn-remove").addEventListener(
            "click",
            () => {

                ["pickup", "dropoff"].forEach((target) => {

                    const key = `${target}-${idx}`;

                    if (maps[key]) {
                        maps[key].remove();
                        delete maps[key];
                    }

                    delete mapMarkers[key];

                });

                card.remove();

                renumberRuns();
                syncPricing();
                updateTotalRunsField();

            }
        );


        // ---------------------------------------------
        // Map controls
        // ---------------------------------------------

        card.querySelectorAll(".btn-map").forEach((button) => {

            button.addEventListener("click", () => {

                const target = button.dataset.target;

                const mapId = `map-${target}-${idx}`;

                const mapElement =
                    document.getElementById(mapId);

                if (mapElement.style.display === "none") {

                    mapElement.style.display = "block";

                    initMap(
                        idx,
                        target,
                        mapElement,
                        card
                    );

                } else {

                    mapElement.style.display = "none";

                }

            });

        });


        // ---------------------------------------------
        // Live pricing synchronization
        // ---------------------------------------------

        card.querySelectorAll(
            "input, select, textarea"
        ).forEach((element) => {

            element.addEventListener("change", () => {

                syncPricing();
                updateTotalRunsField();

            });


            element.addEventListener("input", () => {

                if (
                    element.classList.contains("f-pickup-loc") ||
                    element.classList.contains("f-dropoff-loc") ||
                    element.classList.contains("f-date") ||
                    element.classList.contains("f-type")
                ) {
                    syncPricing();
                }

            });

        });


        syncPricing();
        updateTotalRunsField();

        return card;

    }


    // =====================================================
    // RENUMBER SERVICE RUNS
    // =====================================================

    function renumberRuns() {

        const cards = getRunCards();

        cards.forEach((card, index) => {

            const label = card.querySelector(".run-label");

            if (label) {
                label.textContent = index + 1;
            }

        });

    }


    // =====================================================
    // TOTAL RUNS FIELD
    // =====================================================

    function updateTotalRunsField() {

        const count = getRunCards().length;

        if (!totalRunsInput.dataset.manual) {

            totalRunsInput.value = count
                ? `${count} run${count !== 1 ? "s" : ""}`
                : "";

        }

    }


    totalRunsInput.addEventListener("input", () => {
        totalRunsInput.dataset.manual = "1";
    });


    // =====================================================
    // LEAFLET MAP
    // =====================================================

    function initMap(idx, target, mapElement, card) {

        const key = `${target}-${idx}`;

        if (maps[key]) {

            setTimeout(() => {
                maps[key].invalidateSize();
            }, 100);

            return;
        }


        // Default location: Iowa City, Iowa.
        const map = L.map(mapElement).setView(
            [41.6611, -91.5302],
            10
        );


        L.tileLayer(
            "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            {
                attribution: "&copy; OpenStreetMap contributors",
                maxZoom: 18
            }
        ).addTo(map);


        // Marker helper.
        function setMarker(location, popupText) {

            if (mapMarkers[key]) {
                map.removeLayer(mapMarkers[key]);
            }

            mapMarkers[key] = L.marker(location)
                .addTo(map);

            if (popupText) {
                mapMarkers[key].bindPopup(popupText);
            }

        }


        // Update corresponding address field.
        function updateAddress(address) {

            const inputClass =
                target === "pickup"
                    ? ".f-pickup-loc"
                    : ".f-dropoff-loc";

            const input = card.querySelector(inputClass);

            if (input) {

                input.value = address;

                input.dispatchEvent(
                    new Event("change", { bubbles: true })
                );

            }

        }


        // Address search geocoder.
        const geocoder = L.Control.geocoder({

            defaultMarkGeocode: false,

            placeholder: "Search address...",

            geocoder: L.Control.Geocoder.nominatim({

                geocodingQueryParams: {

                    countrycodes: "us",

                    viewbox: "-96.7,40.3,-90.1,43.6",

                    bounded: 0

                }

            })

        });


        geocoder.on("markgeocode", (event) => {

            const result = event.geocode;

            const center = result.center;

            if (result.bbox) {
                map.fitBounds(result.bbox);
            } else {
                map.setView(center, 15);
            }

            setMarker(center, result.name);

            updateAddress(result.name);

        });


        geocoder.addTo(map);


        // Click-to-select and reverse geocoding.
        map.on("click", async (event) => {

            const latitude = event.latlng.lat;
            const longitude = event.latlng.lng;

            setMarker(event.latlng);

            try {

                const url =
                    "https://nominatim.openstreetmap.org/reverse" +
                    `?format=json&lat=${latitude}&lon=${longitude}`;

                const response = await fetch(url, {

                    headers: {
                        "Accept-Language": "en"
                    }

                });

                if (!response.ok) {
                    throw new Error("Reverse geocoding failed");
                }

                const data = await response.json();

                const address =
                    data.display_name ||
                    `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;

                updateAddress(address);

            } catch (error) {

                console.warn("Reverse geocoding failed:", error);

                updateAddress(
                    `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`
                );

            }

        });


        maps[key] = map;


        // Allow Leaflet to calculate its dimensions
        // after the previously hidden map becomes visible.
        setTimeout(() => {
            map.invalidateSize();
        }, 150);

    }


    // =====================================================
    // COLLECT SERVICE RUNS
    // =====================================================

    function collectRuns() {

        const cards = getRunCards();

        const runs = [];

        cards.forEach((card) => {

            runs.push({

                reservation_number:
                    card.querySelector(".f-reservation")?.value || "",

                date:
                    card.querySelector(".f-date")?.value || "",

                pickup_time:
                    card.querySelector(".f-pickup-time")?.value || "",

                passengers:
                    card.querySelector(".f-passengers")?.value || "",

                type:
                    card.querySelector(".f-type")?.value || "",

                pickup_location:
                    card.querySelector(".f-pickup-loc")?.value || "",

                dropoff_location:
                    card.querySelector(".f-dropoff-loc")?.value || "",

                loop_details:
                    card.querySelector(".f-loop")?.value || "",

                quoted_rate: null

            });

        });

        return runs;

    }


    // =====================================================
    // PRICING TABLE
    // =====================================================

    function syncPricing() {

        const runs = collectRuns();

        // Preserve existing rates.
        const existingRates = {};

        pricingBody.querySelectorAll(
            "tr[data-res]"
        ).forEach((row) => {

            const reservation = row.dataset.res;

            const input = row.querySelector(".rate-input");

            if (reservation && input) {
                existingRates[reservation] = input.value;
            }

        });


        pricingBody.innerHTML = "";


        // Empty state.
        if (runs.length === 0) {

            pricingBody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="5">
                        <div class="empty-pricing">
                            <i class="bi bi-receipt"></i>
                            <span>No scheduled runs yet.</span>
                            <small>
                                Add service runs above to begin pricing.
                            </small>
                        </div>
                    </td>
                </tr>
            `;

            document.getElementById("run-count").textContent = "0";

            document.getElementById("grand-total").textContent = "0.00";

            return;

        }


        let grandTotal = 0;


        runs.forEach((run) => {

            const reservation = run.reservation_number;

            const rateValue =
                existingRates[reservation] ?? "";

            const row = document.createElement("tr");

            row.dataset.res = reservation;

            const route =
                `${run.pickup_location || "…"} → ${run.dropoff_location || "…"}`;


            row.innerHTML = `

                <td>${escapeHtml(reservation)}</td>

                <td>${escapeHtml(run.date)}</td>

                <td>${escapeHtml(run.type)}</td>

                <td>${escapeHtml(route)}</td>

                <td>

                    <input
                        type="number"
                        class="rate-input"
                        step="0.01"
                        min="0"
                        placeholder="0.00"
                        value="${escapeHtml(rateValue)}"
                        data-res="${escapeHtml(reservation)}"
                        aria-label="Quoted rate for reservation ${escapeHtml(reservation)}"
                    />

                </td>

            `;


            pricingBody.appendChild(row);


            const numericRate = parseFloat(rateValue);

            if (!isNaN(numericRate)) {
                grandTotal += numericRate;
            }

        });


        document.getElementById("run-count").textContent =
            String(runs.length);

        document.getElementById("grand-total").textContent =
            grandTotal.toFixed(2);


        // Rebind rate inputs.
        pricingBody.querySelectorAll(
            ".rate-input"
        ).forEach((input) => {

            input.addEventListener("input", recalcTotal);

            input.addEventListener("change", recalcTotal);

        });

    }


    // =====================================================
    // RECALCULATE GRAND TOTAL
    // =====================================================

    function recalcTotal() {

        let grandTotal = 0;

        pricingBody.querySelectorAll(
            ".rate-input"
        ).forEach((input) => {

            const amount = parseFloat(input.value);

            if (!isNaN(amount)) {
                grandTotal += amount;
            }

        });


        document.getElementById("grand-total").textContent =
            grandTotal.toFixed(2);

    }


    // =====================================================
    // FORM SUBMISSION
    // =====================================================

    form.addEventListener("submit", (event) => {

        const runs = collectRuns();


        // Collect rates.
        const rateMap = {};

        pricingBody.querySelectorAll(
            ".rate-input"
        ).forEach((input) => {

            rateMap[input.dataset.res] = input.value;

        });


        runs.forEach((run) => {

            run.quoted_rate =
                rateMap[run.reservation_number] || null;

        });


        // Require at least one service run.
        if (runs.length === 0) {

            event.preventDefault();

            alert(
                "Please add at least one run in Section 2 (Service Schedule)."
            );

            return;

        }


        // Validate individual service runs.
        for (const run of runs) {

            if (
                !run.date ||
                !run.pickup_time ||
                !run.type ||
                !run.pickup_location ||
                !run.dropoff_location
            ) {

                event.preventDefault();

                alert(
                    "Please complete all required fields " +
                    "(date, time, type, pickup and drop-off) " +
                    "for every run."
                );

                return;

            }

        }


        // Store the completed quotation data.
        runsJsonInput.value = JSON.stringify(runs);

        // Normal Flask form submission continues.
    });


    // =====================================================
    // INITIALIZATION
    // =====================================================

    document.getElementById("btn-add-run").addEventListener(
        "click",
        () => addRun()
    );


    // Start with one empty service run.
    addRun();


})();
