const meta = window.MAX_EXPLORER_META;
const page = window.MAX_EXPLORER_PAGE;
const initialFilters = window.MAX_EXPLORER_FILTERS;

const originInput = document.getElementById("origin-input");
const dateInput = document.getElementById("date-input");
const returnDateInput = document.getElementById("return-date-input");
const minStayInput = document.getElementById("min-stay-input");
const minConnectionInput = document.getElementById("min-connection-input");
const maxConnectionsInput = document.getElementById("max-connections-input");
const latestReturnInput = document.getElementById("latest-return-input");
const hybridDestinationInput = document.getElementById("hybrid-destination-input");
const searchForm = document.getElementById("search-form");
const refreshButton = document.getElementById("refresh-button");
const stationSuggestions = document.getElementById("station-suggestions");
const resultsContainer = document.getElementById("results");
const resultSummary = document.getElementById("result-summary");
const mapLegend = document.getElementById("map-legend");

const ROUTE_COLORS = [
  "#db5f32",
  "#0f7a73",
  "#2f5bd3",
  "#9b3bd2",
  "#d1980b",
  "#d43f6d",
  "#247f3d",
  "#6c4dff",
];

const PAGE_LEGENDS = {
  direct: [
    { kind: "origin", label: "Gare de depart" },
    { kind: "destination", label: "Gare d'arrivee" },
  ],
  day_trips: [
    { kind: "origin", label: "Gare de depart" },
    { kind: "destination", label: "Destination" },
  ],
  routes_max: [
    { kind: "origin", label: "Gare de depart" },
    { kind: "destination", label: "Destination" },
  ],
  hybrid: [
    { kind: "origin", label: "Gare de depart" },
    { kind: "via", label: "Gare MAX" },
    { kind: "target", label: "Destination finale" },
  ],
};

let map;
let markerLayer;
let polylineLayer;
let currentMapModel = null;

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([46.6, 2.5], 6);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);
  markerLayer = L.layerGroup().addTo(map);
  polylineLayer = L.layerGroup().addTo(map);
}

function setDefaultInputs() {
  if (originInput) {
    originInput.value = initialFilters.origin || "Paris";
  }
  if (dateInput) {
    dateInput.value = initialFilters.date || meta.available_dates?.[0] || "";
  }
  if (returnDateInput) {
    returnDateInput.value = initialFilters.return_date || "";
  }
  if (minStayInput) {
    minStayInput.value = initialFilters.min_stay_minutes || "240";
  }
  if (minConnectionInput) {
    minConnectionInput.value = initialFilters.min_connection_minutes || "25";
  }
  if (maxConnectionsInput) {
    maxConnectionsInput.value = initialFilters.max_connections || "2";
  }
  if (latestReturnInput) {
    latestReturnInput.value = initialFilters.latest_return_time || "23:30";
  }
  if (hybridDestinationInput) {
    hybridDestinationInput.value = initialFilters.destination || "";
    if (!meta.hybrid_enabled && !hybridDestinationInput.value) {
      hybridDestinationInput.placeholder = "Fonction indisponible sans SNCF_API_TOKEN";
    }
  }
}

async function apiGet(url) {
  const response = await fetch(url);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.reason || "Erreur de chargement");
  }
  return payload;
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function getParamsObject() {
  return {
    origin: originInput?.value?.trim() || "",
    date: dateInput?.value?.trim() || "",
    return_date: returnDateInput?.value?.trim() || "",
    min_stay_minutes: minStayInput?.value?.trim() || "",
    latest_return_time: latestReturnInput?.value?.trim() || "",
    max_connections: maxConnectionsInput?.value?.trim() || "",
    min_connection_minutes: minConnectionInput?.value?.trim() || "",
    destination: hybridDestinationInput?.value?.trim() || "",
  };
}

function getParams() {
  const params = new URLSearchParams();
  const values = getParamsObject();
  Object.entries(values).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  return params;
}

function syncUrlAndNav() {
  const params = getParams();
  const queryString = params.toString();
  const nextUrl = queryString ? `${window.location.pathname}?${queryString}` : window.location.pathname;
  window.history.replaceState({}, "", nextUrl);
  document.querySelectorAll(".section-link").forEach((link) => {
    const baseHref = link.dataset.baseHref;
    link.href = queryString ? `${baseHref}?${queryString}` : baseHref;
  });
  return params;
}

function formatFrenchDate(dateText) {
  if (!dateText) {
    return "";
  }
  const value = dateText.includes("T") ? dateText : `${dateText}T12:00:00`;
  const date = new Date(value);
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(date);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => {
    const replacements = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return replacements[character];
  });
}

function normalizeKeyPart(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function makeResultKey(prefix, value) {
  return `${prefix}-${normalizeKeyPart(value)}`;
}

function createMapIcon(kind = "destination", isActive = false) {
  const safeKind = ["origin", "destination", "via", "target"].includes(kind) ? kind : "destination";
  const activeClass = isActive ? " is-active" : "";
  return L.divIcon({
    className: "map-dot-wrapper",
    html: `<span class="map-dot map-dot-${safeKind}${activeClass}"></span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    popupAnchor: [0, -10],
  });
}

function renderMapLegend(items = []) {
  if (!mapLegend) {
    return;
  }
  mapLegend.innerHTML = items
    .map(
      (item) => `
        <span class="map-legend-item">
          <span class="legend-dot legend-dot-${escapeHtml(item.kind)}"></span>
          <span>${escapeHtml(item.label)}</span>
        </span>
      `
    )
    .join("");
}

function getRouteColor(index) {
  return ROUTE_COLORS[index % ROUTE_COLORS.length];
}

function makeStraightRoute(originCoordinates, destinationCoordinates) {
  if (!originCoordinates || !destinationCoordinates) {
    return null;
  }
  return {
    segments: [
      {
        coordinates: {
          origin: originCoordinates,
          destination: destinationCoordinates,
        },
      },
    ],
  };
}

function drawRoute(route, style, bounds) {
  if (!route || !route.segments) {
    return;
  }

  route.segments.forEach((segment) => {
    const origin = segment.coordinates?.origin;
    const destination = segment.coordinates?.destination;
    if (!origin || !destination) {
      return;
    }

    const polyline = L.polyline(
      [
        [origin.latitude, origin.longitude],
        [destination.latitude, destination.longitude],
      ],
      style
    );
    polyline.addTo(polylineLayer);
    bounds.push([origin.latitude, origin.longitude], [destination.latitude, destination.longitude]);
  });
}

function toRouteEntries(entries) {
  if (!entries) {
    return [];
  }
  return Array.isArray(entries) ? entries : [entries];
}

function drawRouteEntries(entries, bounds) {
  toRouteEntries(entries).forEach((entry) => {
    if (!entry?.route) {
      return;
    }

    drawRoute(
      entry.route,
      {
        color: entry.color || "#4782ee",
        weight: entry.weight || 4,
        opacity: entry.opacity ?? 0.8,
        dashArray: entry.dashArray || null,
      },
      bounds
    );
  });
}

function highlightResultGroup(resultKey, { scroll = true } = {}) {
  document.querySelectorAll(".result-item.is-selected").forEach((element) => {
    element.classList.remove("is-selected");
  });

  if (!resultKey) {
    return;
  }

  const matches = Array.from(document.querySelectorAll(`.result-item[data-result-key="${resultKey}"]`));
  matches.forEach((element) => element.classList.add("is-selected"));

  if (scroll && matches.length) {
    matches[0].scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function renderMapModel(model, options = {}) {
  currentMapModel = model;
  renderMapLegend(model.legend || PAGE_LEGENDS[page.key] || []);
  markerLayer.clearLayers();
  polylineLayer.clearLayers();
  map.invalidateSize(false);

  const bounds = [];
  const focusBounds = [];

  drawRouteEntries(model.baseRoutes, bounds);

  (model.points || []).forEach((point) => {
    const coordinates = point.coordinates;
    if (!coordinates) {
      return;
    }

    const marker = L.marker([coordinates.latitude, coordinates.longitude], {
      icon: createMapIcon(point.kind, point.key && point.key === model.activeKey),
      keyboard: point.selectable !== false,
    });

    const popupLines = [`<strong>${escapeHtml(point.name)}</strong>`];
    if (point.detail) {
      popupLines.push(escapeHtml(point.detail));
    }
    marker.bindPopup(popupLines.join("<br>"));

    if (point.key && point.selectable !== false) {
      marker.on("click", () => {
        selectMapKey(point.key, { scroll: true, focusSelection: true });
      });
    }

    marker.addTo(markerLayer);
    bounds.push([coordinates.latitude, coordinates.longitude]);
  });

  const activeEntries = toRouteEntries(model.routesByKey?.[model.activeKey]);
  drawRouteEntries(activeEntries, focusBounds);

  if (model.activeKey) {
    highlightResultGroup(model.activeKey, { scroll: options.scrollSelection === true });
  }

  if (options.focusSelection && focusBounds.length) {
    map.fitBounds(focusBounds, { padding: [50, 50] });
    return;
  }

  if (bounds.length) {
    map.fitBounds(bounds, { padding: [50, 50] });
    return;
  }

  map.setView([46.6, 2.5], 6);
}

function selectMapKey(resultKey, { scroll = true, focusSelection = true } = {}) {
  if (!currentMapModel) {
    return;
  }

  currentMapModel = {
    ...currentMapModel,
    activeKey: resultKey,
  };

  renderMapModel(currentMapModel, {
    focusSelection,
    scrollSelection: scroll,
  });
}

function bindSelectableCards() {
  document.querySelectorAll(".result-item[data-result-key]").forEach((card) => {
    card.classList.add("is-interactive");
    card.addEventListener("click", (event) => {
      if (event.target.closest("a, button, summary")) {
        return;
      }
      selectMapKey(card.dataset.resultKey, { scroll: false, focusSelection: true });
    });
  });
}

function renderReturnOptions(trip) {
  const options = trip.return_options;
  if (!options) {
    return "";
  }

  if (!options.has_any) {
    const emptyMessage = options.requested_return_date
      ? `Aucun retour a 0 EUR le ${formatFrenchDate(options.requested_return_date)}.`
      : "Aucun retour a 0 EUR trouve dans la fenetre de donnees apres ce trajet.";
    return `
      <div class="return-panel return-panel-empty">
        <strong>Retours</strong>
        <p class="muted">${escapeHtml(emptyMessage)}</p>
      </div>
    `;
  }

  const summary = options.requested_return_date
    ? `Retours a 0 EUR le ${formatFrenchDate(options.requested_return_date)}`
    : `Voir les retours a 0 EUR (${options.total_dates} date(s))`;

  const heading = options.requested_return_date
    ? `Retours disponibles (${trip.destination} -> ${trip.origin})`
    : `Dates retour possibles (${trip.destination} -> ${trip.origin})`;

  return `
    <details class="return-panel">
      <summary>${escapeHtml(summary)}</summary>
      <div class="return-panel-body">
        <h4>${escapeHtml(heading)}</h4>
        <div class="return-date-list">
          ${options.available_dates
            .map(
              (group) => `
                <section class="return-date-group">
                  <div class="return-date-chip">${escapeHtml(formatFrenchDate(group.date))}</div>
                  <div class="return-time-list">
                    ${group.times
                      .map(
                        (returnTrip) => `
                          <a class="return-time-chip" href="${escapeHtml(returnTrip.booking_url)}" title="Ouvrir le retour sur SNCF Connect">
                            <span>${escapeHtml(returnTrip.departure_time)}</span>
                            <small>${escapeHtml(returnTrip.arrival_time)}</small>
                          </a>
                        `
                      )
                      .join("")}
                  </div>
                </section>
              `
            )
            .join("")}
        </div>
      </div>
    </details>
  `;
}

function renderDirect(payload) {
  const returnSummary = payload.return_date
    ? ` | retours filtres au ${formatFrenchDate(payload.return_date)}`
    : " | retours proposes sur les dates disponibles";
  resultSummary.textContent = `${payload.trip_count} trains a 0 EUR depuis ${payload.matched_origins.join(", ")}${returnSummary}`;

  if (!payload.trips.length) {
    resultsContainer.innerHTML = emptyState("Aucun train a 0 EUR trouve pour ce depart et cette date.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.direct }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultsContainer.innerHTML = payload.trips
    .map((trip) => {
      const resultKey = makeResultKey("direct", trip.destination);
      return `
        <article class="result-item" data-result-key="${resultKey}">
          <div class="result-item-head">
            <div>
              <h3>${escapeHtml(trip.origin)} -> ${escapeHtml(trip.destination)}</h3>
              <p class="muted">${escapeHtml(trip.departure_time)} -> ${escapeHtml(trip.arrival_time)}</p>
            </div>
            <a class="result-link" href="${escapeHtml(trip.booking_url)}" title="Ouvrir ce trajet sur SNCF Connect">Ouvrir sur SNCF Connect</a>
          </div>
          <div class="result-meta">
            <span class="result-pill">${escapeHtml(trip.duration_label)}</span>
            <span class="result-pill">Train ${escapeHtml(trip.train_no || "n/a")}</span>
          </div>
          ${renderReturnOptions(trip)}
        </article>
      `;
    })
    .join("");

  bindSelectableCards();

  const originCoordinates = payload.trips.find((trip) => trip.coordinates?.origin)?.coordinates?.origin || null;
  const matchedOrigin = payload.matched_origins[0] || payload.origin_query;
  const baseRoutes = [];
  const routesByKey = {};
  const points = [];

  if (originCoordinates) {
    points.push({
      name: matchedOrigin,
      detail: "Point de depart",
      coordinates: originCoordinates,
      kind: "origin",
      selectable: false,
    });
  }

  payload.destinations.forEach((destination) => {
    const resultKey = makeResultKey("direct", destination.destination);
    const route = makeStraightRoute(originCoordinates, destination.coordinates);

    points.push({
      key: resultKey,
      name: destination.destination,
      detail: `${destination.trip_count} train(s) direct(s)`,
      coordinates: destination.coordinates,
      kind: "destination",
    });

    if (route) {
      baseRoutes.push({
        route,
        color: "#9fc0ff",
        weight: 5,
        opacity: 0.22,
      });
      routesByKey[resultKey] = {
        route,
        color: "#4782ee",
        weight: 6,
        opacity: 0.9,
      };
    }
  });

  const firstKey = payload.destinations[0] ? makeResultKey("direct", payload.destinations[0].destination) : null;
  renderMapModel(
    {
      points,
      baseRoutes,
      routesByKey,
      activeKey: firstKey,
      legend: PAGE_LEGENDS.direct,
    },
    {
      focusSelection: false,
      scrollSelection: false,
    }
  );
}

function renderDayTrips(payload) {
  const sameDayReturn = payload.return_date === payload.travel_date;
  resultSummary.textContent = sameDayReturn
    ? `${payload.results.length} destination(s) faisables en aller-retour journee.`
    : `${payload.results.length} destination(s) avec retour possible le ${formatFrenchDate(payload.return_date)}.`;

  if (!payload.results.length) {
    resultsContainer.innerHTML = emptyState("Aucun aller-retour journee compatible avec les filtres.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.day_trips }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultsContainer.innerHTML = payload.results
    .map((item) => {
      const resultKey = makeResultKey("day-trip", item.destination);
      return `
        <article class="result-item" data-result-key="${resultKey}">
          <h3>${escapeHtml(item.destination)}</h3>
          <p class="muted">Aller ${escapeHtml(item.outbound.departure_time)} -> ${escapeHtml(item.outbound.arrival_time)} | Retour ${escapeHtml(item.return.departure_time)} -> ${escapeHtml(item.return.arrival_time)}</p>
          <div class="result-meta">
            <span class="result-pill">Sur place ${escapeHtml(item.stay_label)}</span>
            <span class="result-pill">Total ${escapeHtml(item.total_trip_label)}</span>
          </div>
        </article>
      `;
    })
    .join("");

  bindSelectableCards();

  const originCoordinates = payload.results.find((item) => item.outbound.coordinates?.origin)?.outbound.coordinates?.origin || null;
  const matchedOrigin = payload.matched_origins[0] || payload.origin_query;
  const baseRoutes = [];
  const routesByKey = {};
  const points = [];

  if (originCoordinates) {
    points.push({
      name: matchedOrigin,
      detail: "Point de depart",
      coordinates: originCoordinates,
      kind: "origin",
      selectable: false,
    });
  }

  payload.results.forEach((item) => {
    const resultKey = makeResultKey("day-trip", item.destination);
    const route = makeStraightRoute(originCoordinates, item.coordinates);

    points.push({
      key: resultKey,
      name: item.destination,
      detail: `Sur place ${item.stay_label}`,
      coordinates: item.coordinates,
      kind: "destination",
    });

    if (route) {
      baseRoutes.push({
        route,
        color: "#c4d5ff",
        weight: 5,
        opacity: 0.18,
      });
      routesByKey[resultKey] = {
        route,
        color: "#4782ee",
        weight: 6,
        opacity: 0.88,
      };
    }
  });

  const firstKey = payload.results[0] ? makeResultKey("day-trip", payload.results[0].destination) : null;
  renderMapModel(
    {
      points,
      baseRoutes,
      routesByKey,
      activeKey: firstKey,
      legend: PAGE_LEGENDS.day_trips,
    },
    {
      focusSelection: false,
      scrollSelection: false,
    }
  );
}

function routeCard(group) {
  const best = group.itineraries[0];
  return `
    <article class="result-item" data-result-key="${group.resultKey}">
      <h3>${escapeHtml(group.destination)}</h3>
      <p class="muted">Meilleur parcours ${escapeHtml(best.departure_time)} -> ${escapeHtml(best.arrival_time)}</p>
      <div class="result-meta">
        <span class="route-swatch" style="--route-color: ${group.color};"></span>
        <span class="result-pill">${escapeHtml(best.duration_label)}</span>
        <span class="result-pill">${best.connections} correspondance(s)</span>
        <button class="result-pill show-route-button" data-result-key="${group.resultKey}">Tracer</button>
      </div>
      <div class="segment-list">
        ${best.segments
          .map(
            (segment) => `
              <div class="segment">
                <div>
                  <strong>${escapeHtml(segment.origin)} -> ${escapeHtml(segment.destination)}</strong>
                  <span class="muted">Train ${escapeHtml(segment.train_no || "n/a")}</span>
                </div>
                <div>${escapeHtml(segment.departure_time)} -> ${escapeHtml(segment.arrival_time)}</div>
              </div>
            `
          )
          .join("")}
      </div>
    </article>
  `;
}

function renderRoutes(payload) {
  resultSummary.textContent = `${payload.results.length} destination(s) accessibles avec correspondances MAX. Clique une destination ou un point de la carte pour tracer un seul chemin proprement.`;

  if (!payload.results.length) {
    resultsContainer.innerHTML = emptyState("Aucune correspondance MAX trouvee.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.routes_max }, { focusSelection: false, scrollSelection: false });
    return;
  }

  const routeGroups = payload.results.map((group, index) => ({
    ...group,
    color: getRouteColor(index),
    route: group.itineraries[0],
    resultKey: makeResultKey("route", group.destination),
  }));

  resultsContainer.innerHTML = routeGroups.map(routeCard).join("");
  bindSelectableCards();

  document.querySelectorAll(".show-route-button").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      selectMapKey(button.dataset.resultKey, { scroll: true, focusSelection: true });
    });
  });

  const points = [];
  const firstOrigin = routeGroups[0]?.route?.segments?.[0]?.coordinates?.origin || null;
  const matchedOrigin = payload.matched_origins[0] || payload.origin_query;

  if (firstOrigin) {
    points.push({
      name: matchedOrigin,
      detail: "Point de depart",
      coordinates: firstOrigin,
      kind: "origin",
      selectable: false,
    });
  }

  const routesByKey = {};
  routeGroups.forEach((group) => {
    points.push({
      key: group.resultKey,
      name: group.destination,
      detail: `${group.itineraries[0].duration_label} - ${group.itineraries[0].connections} correspondance(s)`,
      coordinates: group.coordinates,
      kind: "destination",
    });

    routesByKey[group.resultKey] = {
      route: group.route,
      color: group.color,
      weight: 6,
      opacity: 0.92,
    };
  });

  renderMapModel(
    {
      points,
      routesByKey,
      activeKey: routeGroups[0]?.resultKey || null,
      legend: PAGE_LEGENDS.routes_max,
    },
    {
      focusSelection: true,
      scrollSelection: false,
    }
  );
}

function buildHybridSelectionKey(item) {
  return makeResultKey("hybrid", `${item.destination}-${item.via_max_station}`);
}

function renderHybrid(payload) {
  if (!payload.enabled) {
    resultSummary.textContent = payload.reason || "Mode hybride indisponible.";
    resultsContainer.innerHTML = emptyState(
      `${payload.reason || "Mode hybride indisponible."} Ajoute SNCF_API_TOKEN dans l'environnement du serveur puis relance l'application.`
    );
    renderMapModel({ points: [], legend: PAGE_LEGENDS.hybrid }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultSummary.textContent = `${payload.results.length} prolongement(s) hybride(s) trouves.`;
  if (!payload.results.length) {
    resultsContainer.innerHTML = emptyState("Aucun prolongement MAX + TER trouve pour cette destination.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.hybrid }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultsContainer.innerHTML = payload.results
    .map((item) => {
      const resultKey = buildHybridSelectionKey(item);
      return `
        <article class="result-item" data-result-key="${resultKey}">
          <h3>${escapeHtml(item.destination)} via ${escapeHtml(item.via_max_station)}</h3>
          <p class="muted">MAX ${escapeHtml(item.max_itinerary.departure_time)} -> ${escapeHtml(item.max_itinerary.arrival_time)} puis TER ${escapeHtml(item.ter_extension.departure_time)} -> ${escapeHtml(item.ter_extension.arrival_time)}</p>
          <div class="result-meta">
            <span class="result-pill">Total ${escapeHtml(item.total_duration_label)}</span>
          </div>
          <div class="segment-list">
            ${item.max_itinerary.segments
              .map(
                (segment) => `
                  <div class="segment">
                    <div>
                      <strong>${escapeHtml(segment.origin)} -> ${escapeHtml(segment.destination)}</strong>
                    </div>
                    <div>${escapeHtml(segment.departure_time)} -> ${escapeHtml(segment.arrival_time)}</div>
                  </div>
                `
              )
              .join("")}
            ${item.ter_extension.sections
              .map(
                (section) => `
                  <div class="segment">
                    <div>
                      <strong>${escapeHtml(section.from)} -> ${escapeHtml(section.to)}</strong>
                      <span class="muted">${escapeHtml(section.mode)}${section.label ? ` ${escapeHtml(section.label)}` : ""}</span>
                    </div>
                  </div>
                `
              )
              .join("")}
          </div>
        </article>
      `;
    })
    .join("");

  bindSelectableCards();

  const points = [];
  const routesByKey = {};
  const seenPointKeys = new Set();
  const firstOrigin = payload.results[0]?.max_itinerary?.segments?.[0]?.coordinates?.origin || null;
  const firstOriginLabel = payload.results[0]?.max_itinerary?.origin || "";

  if (firstOrigin) {
    points.push({
      name: firstOriginLabel,
      detail: "Point de depart",
      coordinates: firstOrigin,
      kind: "origin",
      selectable: false,
    });
  }

  payload.results.forEach((item) => {
    const resultKey = buildHybridSelectionKey(item);
    const lastSegment = item.max_itinerary.segments[item.max_itinerary.segments.length - 1];
    const viaCoordinates = lastSegment?.coordinates?.destination;
    const targetCoordinates = item.target_coordinates;
    const pointIdentity = `${item.via_max_station}-${viaCoordinates?.latitude}-${viaCoordinates?.longitude}`;

    if (viaCoordinates && !seenPointKeys.has(pointIdentity)) {
      seenPointKeys.add(pointIdentity);
      points.push({
        key: resultKey,
        name: item.via_max_station,
        detail: `Derniere gare MAX avant ${item.destination}`,
        coordinates: viaCoordinates,
        kind: "via",
      });
    }

    if (targetCoordinates && !seenPointKeys.has(`target-${targetCoordinates.latitude}-${targetCoordinates.longitude}`)) {
      seenPointKeys.add(`target-${targetCoordinates.latitude}-${targetCoordinates.longitude}`);
      points.push({
        name: item.destination,
        detail: "Destination finale",
        coordinates: targetCoordinates,
        kind: "target",
        selectable: false,
      });
    }

    routesByKey[resultKey] = [
      {
        route: item.max_itinerary,
        color: "#efaf4f",
        weight: 6,
        opacity: 0.9,
      },
      {
        route: makeStraightRoute(viaCoordinates, targetCoordinates),
        color: "#d85f7f",
        weight: 5,
        opacity: 0.78,
        dashArray: "10 10",
      },
    ];
  });

  renderMapModel(
    {
      points,
      routesByKey,
      activeKey: buildHybridSelectionKey(payload.results[0]),
      legend: PAGE_LEGENDS.hybrid,
    },
    {
      focusSelection: true,
      scrollSelection: false,
    }
  );
}

async function loadCurrentPage() {
  const params = syncUrlAndNav();
  const values = getParamsObject();

  if (!values.origin || !values.date) {
    resultSummary.textContent = "Renseigne au moins un depart et une date.";
    resultsContainer.innerHTML = emptyState("Complete les parametres pour lancer la recherche.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS[page.key] || [] }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultSummary.textContent = "Chargement...";

  try {
    if (page.key === "direct") {
      const payload = await apiGet(`/api/direct?${params.toString()}`);
      renderDirect(payload);
      return;
    }

    if (page.key === "day_trips") {
      const payload = await apiGet(`/api/day-trips?${params.toString()}`);
      renderDayTrips(payload);
      return;
    }

    if (page.key === "routes_max") {
      const payload = await apiGet(`/api/routes/max?${params.toString()}`);
      renderRoutes(payload);
      return;
    }

    if (page.key === "hybrid") {
      if (!meta.hybrid_enabled) {
        resultSummary.textContent = "Mode indisponible : la cle SNCF_API_TOKEN manque cote serveur.";
        resultsContainer.innerHTML = emptyState(
          "Le calcul MAX + TER a besoin d'une cle API SNCF/Navitia cote serveur. Ajoute SNCF_API_TOKEN puis relance l'application."
        );
        renderMapModel({ points: [], legend: PAGE_LEGENDS.hybrid }, { focusSelection: false, scrollSelection: false });
        return;
      }

      if (!values.destination) {
        resultSummary.textContent = "Renseigne une destination finale apres le segment MAX.";
        resultsContainer.innerHTML = emptyState(
          "Exemple : si MAX t'emmene a Annecy et que tu veux finir a Chamonix, la destination finale a saisir est Chamonix-Mont-Blanc."
        );
        renderMapModel({ points: [], legend: PAGE_LEGENDS.hybrid }, { focusSelection: false, scrollSelection: false });
        return;
      }

      const payload = await apiGet(`/api/routes/hybrid?${params.toString()}`);
      renderHybrid(payload);
    }
  } catch (error) {
    resultSummary.textContent = error.message;
    resultsContainer.innerHTML = emptyState(error.message);
    renderMapModel({ points: [], legend: PAGE_LEGENDS[page.key] || [] }, { focusSelection: false, scrollSelection: false });
  }
}

async function fetchSuggestions() {
  if (!originInput || !stationSuggestions) {
    return;
  }

  const value = originInput.value.trim();
  if (value.length < 2) {
    stationSuggestions.style.display = "none";
    stationSuggestions.innerHTML = "";
    return;
  }

  try {
    const payload = await apiGet(`/api/stations?q=${encodeURIComponent(value)}`);
    if (!payload.results.length) {
      stationSuggestions.style.display = "none";
      stationSuggestions.innerHTML = "";
      return;
    }

    stationSuggestions.innerHTML = payload.results
      .map(
        (item) => `
          <button type="button" class="suggestion-item" data-value="${escapeHtml(item.label)}">
            ${escapeHtml(item.label)}
          </button>
        `
      )
      .join("");
    stationSuggestions.style.display = "block";

    stationSuggestions.querySelectorAll(".suggestion-item").forEach((button) => {
      button.addEventListener("click", () => {
        originInput.value = button.dataset.value;
        stationSuggestions.style.display = "none";
        stationSuggestions.innerHTML = "";
      });
    });
  } catch {
    stationSuggestions.style.display = "none";
    stationSuggestions.innerHTML = "";
  }
}

async function refreshData() {
  refreshButton.disabled = true;
  refreshButton.textContent = "Rafraichissement...";
  try {
    await fetch("/api/refresh", { method: "POST" });
    await loadCurrentPage();
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "Rafraichir les donnees";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  setDefaultInputs();
  syncUrlAndNav();
  loadCurrentPage();

  if (originInput) {
    originInput.addEventListener("input", fetchSuggestions);
  }

  if (stationSuggestions && originInput) {
    document.addEventListener("click", (event) => {
      if (!stationSuggestions.contains(event.target) && event.target !== originInput) {
        stationSuggestions.style.display = "none";
      }
    });
  }

  searchForm.addEventListener("submit", (event) => {
    event.preventDefault();
    loadCurrentPage();
  });

  refreshButton.addEventListener("click", refreshData);
});
