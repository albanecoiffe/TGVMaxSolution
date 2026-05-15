const meta = window.MAX_EXPLORER_META;
const page = window.MAX_EXPLORER_PAGE;
const initialFilters = window.MAX_EXPLORER_FILTERS;

const originInput = document.getElementById("origin-input");
const dateInput = document.getElementById("date-input");
const returnDateInput = document.getElementById("return-date-input");
const minStayInput = document.getElementById("min-stay-input");
const minConnectionInput = document.getElementById("min-connection-input");
const maxConnectionInput = document.getElementById("max-connection-input");
const maxConnectionsInput = document.getElementById("max-connections-input");
const latestReturnInput = document.getElementById("latest-return-input");
const searchForm = document.getElementById("search-form");
const exploreButton = document.getElementById("explore-button");
const refreshButton = document.getElementById("refresh-button");
const stationSuggestions = document.getElementById("station-suggestions");
const resultsContainer = document.getElementById("results");
const resultSummary = document.getElementById("result-summary");
const mapLegend = document.getElementById("map-legend");
const resultActions = document.getElementById("result-actions");
const loadingOverlay = document.getElementById("loading-overlay");

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
  live_watch: [],
};

let map;
let markerLayer;
let polylineLayer;
let currentMapModel = null;
let currentDirectTrips = [];
let currentDirectPayload = null;

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
  if (maxConnectionInput) {
    maxConnectionInput.value = initialFilters.max_connection_minutes || "";
  }
  if (maxConnectionsInput) {
    maxConnectionsInput.value = initialFilters.max_connections || "2";
  }
  if (latestReturnInput) {
    latestReturnInput.value = initialFilters.latest_return_time || "23:30";
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

async function apiPost(url) {
  const response = await fetch(url, { method: "POST" });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.reason || "Erreur de chargement");
  }
  return payload;
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function setLoadingState(isLoading) {
  loadingOverlay?.classList.toggle("is-visible", isLoading);
  loadingOverlay?.setAttribute("aria-hidden", isLoading ? "false" : "true");
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
    max_connection_minutes: maxConnectionInput?.value?.trim() || "",
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

function totalTravelMinutes(segments) {
  return (segments || []).reduce((sum, segment) => sum + Number(segment.duration_minutes || 0), 0);
}

function routeOptionKey(destination, index) {
  return makeResultKey("route-option", `${destination}-${index}`);
}

function uniqueStationPoints(entries) {
  const points = [];
  const seen = new Set();

  entries.forEach((entry) => {
    const name = entry?.name;
    const coordinates = entry?.coordinates;
    if (!name || !coordinates) {
      return;
    }

    const identity = `${name}-${coordinates.latitude}-${coordinates.longitude}`;
    if (seen.has(identity)) {
      return;
    }

    seen.add(identity);
    points.push({
      name,
      coordinates,
    });
  });

  return points;
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

function escapeAttribute(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
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

  const orderedPoints = [
    ...(model.points || []).filter((point) => point.kind !== "origin"),
    ...(model.points || []).filter((point) => point.kind === "origin"),
  ];

  orderedPoints.forEach((point) => {
    const coordinates = point.coordinates;
    if (!coordinates) {
      return;
    }

    const marker = L.marker([coordinates.latitude, coordinates.longitude], {
      icon: createMapIcon(point.kind, point.key && point.key === model.activeKey),
      keyboard: point.selectable !== false,
      zIndexOffset: point.kind === "origin" ? 1200 : point.key && point.key === model.activeKey ? 900 : 0,
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

function updateResultActions() {
  if (!resultActions) {
    return;
  }

  if (page.key === "live_watch") {
    resultActions.innerHTML = `
      <div class="result-actions-stack">
        <span class="live-status-note">Cette page lit l'etat persistant pousse par l'extension navigateur vers l'application locale.</span>
        <span class="live-status-note">Elle se recharge automatiquement toutes les 30 secondes.</span>
      </div>
    `;
    return;
  }

  if (page.key !== "direct") {
    resultActions.innerHTML = "";
    return;
  }

  const generatedAt = meta.generated_at ? new Date(meta.generated_at) : null;
  const generatedLabel = generatedAt
    ? new Intl.DateTimeFormat("fr-FR", {
        day: "numeric",
        month: "long",
        hour: "2-digit",
        minute: "2-digit",
      }).format(generatedAt)
    : "inconnue";
  resultActions.innerHTML = `
    <div class="result-actions-stack">
      <span class="live-status-note">Vu dans le dataset SNCF tgvmax recharge par l'application le ${escapeHtml(generatedLabel)}.</span>
      <span class="live-status-note">Cette vue montre le dataset SNCF tel qu'il a ete charge, sans verification live complementaire.</span>
    </div>
  `;
}

function groupDirectTripsByDestination(payload, trips = currentDirectTrips) {
  const destinationMeta = new Map((payload.destinations || []).map((item) => [item.destination, item]));
  const groups = new Map();

  trips.forEach((trip) => {
    if (!groups.has(trip.destination)) {
      groups.set(trip.destination, {
        destination: trip.destination,
        origin: trip.origin,
        resultKey: makeResultKey("direct", trip.destination),
        destinationMeta: destinationMeta.get(trip.destination) || null,
        trips: [],
      });
    }
    groups.get(trip.destination).trips.push(trip);
  });

  const orderedDestinations = (payload.destinations || []).map((item) => item.destination);
  const destinationIndex = new Map(orderedDestinations.map((name, index) => [name, index]));

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      trips: group.trips.sort((left, right) => {
        if (left.departure_time !== right.departure_time) {
          return left.departure_time.localeCompare(right.departure_time);
        }
        return left.arrival_time.localeCompare(right.arrival_time);
      }),
    }))
    .sort((left, right) => {
      const leftIndex = destinationIndex.get(left.destination) ?? Number.MAX_SAFE_INTEGER;
      const rightIndex = destinationIndex.get(right.destination) ?? Number.MAX_SAFE_INTEGER;
      if (leftIndex !== rightIndex) {
        return leftIndex - rightIndex;
      }
      return left.destination.localeCompare(right.destination);
    });
}

function renderDirectOption(trip) {
  return `
    <section class="direct-option" data-trip-id="${escapeAttribute(trip.id)}">
      <div class="direct-option-head">
        <div>
          <h4>${escapeHtml(trip.departure_time)} -> ${escapeHtml(trip.arrival_time)}</h4>
          <p class="muted">Train ${escapeHtml(trip.train_no || "n/a")}</p>
        </div>
        <a class="result-link" href="${escapeHtml(trip.booking_url)}" title="Ouvrir ce trajet sur SNCF Connect">Ouvrir sur SNCF Connect</a>
      </div>
      <div class="result-meta">
        <span class="result-pill">${escapeHtml(trip.duration_label)}</span>
      </div>
      ${renderReturnOptions(trip)}
    </section>
  `;
}

function buildDirectMapModel(trips, activeKey = null) {
  const originStations = uniqueStationPoints(
    trips.map((trip) => ({
      name: trip.origin,
      coordinates: trip.coordinates?.origin,
    }))
  );
  const baseRoutes = [];
  const routesByKey = {};
  const points = [];
  const groupedDestinations = new Map();

  originStations.forEach((originStation) => {
    points.push({
      name: originStation.name,
      detail: "Point de depart",
      coordinates: originStation.coordinates,
      kind: "origin",
      selectable: false,
    });
  });

  trips.forEach((trip) => {
    if (!trip.destination) {
      return;
    }

    if (!groupedDestinations.has(trip.destination)) {
      groupedDestinations.set(trip.destination, {
        coordinates: trip.coordinates?.destination || null,
        trips: [],
      });
    }

    const destinationGroup = groupedDestinations.get(trip.destination);
    if (!destinationGroup.coordinates && trip.coordinates?.destination) {
      destinationGroup.coordinates = trip.coordinates.destination;
    }
    destinationGroup.trips.push(trip);
  });

  groupedDestinations.forEach((destinationGroup, destinationName) => {
    const resultKey = makeResultKey("direct", destinationName);

    points.push({
      key: resultKey,
      name: destinationName,
      detail: `${destinationGroup.trips.length} train(s) direct(s)`,
      coordinates: destinationGroup.coordinates,
      kind: "destination",
    });

    const destinationRoutes = destinationGroup.trips
      .map((trip) => makeStraightRoute(trip.coordinates?.origin, trip.coordinates?.destination))
      .filter(Boolean);

    destinationRoutes.forEach((route) => {
      baseRoutes.push({
        route,
        color: "#9fc0ff",
        weight: 5,
        opacity: 0.22,
      });
    });

    if (destinationRoutes.length) {
      routesByKey[resultKey] = destinationRoutes.map((route) => ({
        route,
        color: "#4782ee",
        weight: 6,
        opacity: 0.9,
      }));
    }
  });

  const availableKeys = points.filter((point) => point.key).map((point) => point.key);
  const nextActiveKey = availableKeys.includes(activeKey) ? activeKey : availableKeys[0] || null;

  return {
    points,
    baseRoutes,
    routesByKey,
    activeKey: nextActiveKey,
    legend: PAGE_LEGENDS.direct,
  };
}

function renderReturnOptions(trip, renderOptions = {}) {
  const showSegments = Boolean(renderOptions.showSegments);
  const returnOptions = trip.return_options;
  if (!returnOptions) {
    return "";
  }

  if (!returnOptions.has_any) {
    const emptyMessage = returnOptions.requested_return_date
      ? `Aucun retour a 0 EUR le ${formatFrenchDate(returnOptions.requested_return_date)}.`
      : "Aucun retour a 0 EUR trouve dans la fenetre de donnees apres ce trajet.";
    return `
      <div class="return-panel return-panel-empty">
        <strong>Retours</strong>
        <p class="muted">${escapeHtml(emptyMessage)}</p>
      </div>
    `;
  }

  const heading = returnOptions.requested_return_date
    ? `Retours a 0 EUR a partir du ${formatFrenchDate(returnOptions.requested_return_date)}`
    : `Retours a 0 EUR les plus proches (${returnOptions.total_dates} date(s))`;
  const hint = returnOptions.total_dates > returnOptions.available_dates.length
    ? `Apercu des ${returnOptions.available_dates.length} prochaines dates retour.`
    : `${returnOptions.total_trips} train(s) retour a 0 EUR repere(s).`;

  return `
    <div class="return-panel">
      <div class="return-panel-body is-static">
        <h4>${escapeHtml(heading)}</h4>
        <p class="live-status-note">${escapeHtml(hint)}</p>
        <div class="return-date-list">
          ${returnOptions.available_dates
            .map(
              (group) => `
                <section class="return-date-group">
                  <div class="return-date-chip">${escapeHtml(formatFrenchDate(group.date))}</div>
                  <div class="return-time-list">
                    ${group.times
                      .map(
                        (returnTrip) => `
                          <div class="return-time-card">
                            <a class="return-time-chip" href="${escapeHtml(returnTrip.booking_url)}" title="Ouvrir le retour sur SNCF Connect">
                              <span>${escapeHtml(returnTrip.departure_time)}</span>
                              <small>${escapeHtml(returnTrip.arrival_time)}</small>
                            </a>
                            ${
                              showSegments && Array.isArray(returnTrip.segments)
                                ? `
                                  <div class="return-itinerary-meta">
                                    <span class="result-pill">${escapeHtml(returnTrip.duration_label)}</span>
                                    <span class="result-pill">${returnTrip.connections} correspondance(s)</span>
                                  </div>
                                  <div class="segment-list return-segment-list">
                                    ${returnTrip.segments
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
                                `
                                : ""
                            }
                          </div>
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
    </div>
  `;
}

function renderDirectResults() {
  if (!currentDirectPayload) {
    return;
  }

  const payload = currentDirectPayload;
  const visibleTrips = currentDirectTrips;
  const returnSummary = payload.includes_return_options && payload.return_date
    ? ` | retours proposes a partir du ${formatFrenchDate(payload.return_date)}`
    : payload.includes_return_options
      ? " | retours proposes sur les dates disponibles"
      : " | retours non precharges sur cette vue pour garder une recherche rapide";
  resultSummary.textContent = `${payload.destinations.length} destination(s) | ${payload.trip_count} train(s) marques a 0 EUR dans le dataset SNCF depuis ${payload.matched_origins.join(", ")}${returnSummary}`;

  if (!currentDirectTrips.length) {
    resultsContainer.innerHTML = emptyState("Aucun train marque a 0 EUR dans le dataset SNCF pour ce depart et cette date.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.direct }, { focusSelection: false, scrollSelection: false });
    return;
  }

  const directGroups = groupDirectTripsByDestination(currentDirectPayload, visibleTrips);

  resultsContainer.innerHTML = directGroups
    .map((group) => {
      const firstTrip = group.trips[0];
      const summary = group.trips.length > 1
        ? `${group.trips.length} creneaux issus du dataset SNCF`
        : "1 train issu du dataset SNCF";
      return `
        <article class="result-item" data-result-key="${group.resultKey}">
          <div class="result-item-head">
            <div>
              <h3>${escapeHtml(firstTrip.origin)} -> ${escapeHtml(group.destination)}</h3>
              <p class="muted">${escapeHtml(summary)}</p>
            </div>
          </div>
          <div class="direct-time-chip-list">
            ${group.trips
              .map(
                (trip) => `
                  <a class="direct-time-chip" href="${escapeHtml(trip.booking_url)}" title="Ouvrir ce trajet sur SNCF Connect">
                    <span>${escapeHtml(trip.departure_time)}</span>
                    <small>${escapeHtml(trip.arrival_time)}</small>
                  </a>
                `
              )
              .join("")}
          </div>
          <div class="direct-option-list">
            ${group.trips.map((trip) => renderDirectOption(trip)).join("")}
          </div>
        </article>
      `;
    })
    .join("");

  bindSelectableCards();

  renderMapModel(
    buildDirectMapModel(visibleTrips),
    {
      focusSelection: false,
      scrollSelection: false,
    }
  );
}

function renderDirect(payload) {
  currentDirectPayload = payload;
  currentDirectTrips = payload.trips || [];
  updateResultActions();
  renderDirectResults();
}

function renderDayTrips(payload) {
  currentDirectTrips = [];
  updateResultActions();

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

  const originStations = uniqueStationPoints(
    payload.results.map((item) => ({
      name: item.outbound.origin,
      coordinates: item.outbound.coordinates?.origin,
    }))
  );
  const baseRoutes = [];
  const routesByKey = {};
  const points = [];

  originStations.forEach((originStation) => {
    points.push({
      name: originStation.name,
      detail: "Point de depart",
      coordinates: originStation.coordinates,
      kind: "origin",
      selectable: false,
    });
  });

  payload.results.forEach((item) => {
    const resultKey = makeResultKey("day-trip", item.destination);
    const route = makeStraightRoute(item.outbound.coordinates?.origin, item.coordinates);

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
  const bestTravelMinutes = totalTravelMinutes(best.segments);
  const returnSummary = group.return_date
    ? ` | retours a partir du ${formatFrenchDate(group.return_date)}`
    : " | retours proposes sur dates disponibles";
  return `
    <article class="result-item" data-result-key="${group.resultKey}">
      <h3>${escapeHtml(group.destination)}</h3>
      <p class="muted">Premier parcours propose ${escapeHtml(best.departure_time)} -> ${escapeHtml(best.arrival_time)}${escapeHtml(returnSummary)}</p>
      <div class="result-meta">
        <span class="route-swatch" style="--route-color: ${group.color};"></span>
        <span class="result-pill">Duree totale ${escapeHtml(best.duration_label)}</span>
        <span class="result-pill">Temps en train ${escapeHtml(formatDuration(bestTravelMinutes))}</span>
        <span class="result-pill">${best.connections} correspondance(s)</span>
      </div>
      <div class="segment-list route-option-list">
        ${group.itineraries
          .map((itinerary, index) => {
            const travelMinutes = totalTravelMinutes(itinerary.segments);
            return `
              <div class="route-option">
                <div class="result-item-head">
                  <div>
                    <strong>Parcours ${index + 1} ${escapeHtml(itinerary.departure_time)} -> ${escapeHtml(itinerary.arrival_time)}</strong>
                    <p class="muted">Duree totale ${escapeHtml(itinerary.duration_label)} | Temps en train ${escapeHtml(formatDuration(travelMinutes))}</p>
                  </div>
                  <button class="result-pill show-route-button" data-result-key="${routeOptionKey(group.destination, index)}">Tracer</button>
                </div>
                <div class="result-meta">
                  <span class="result-pill">${itinerary.connections} correspondance(s)</span>
                </div>
                <div class="segment-list">
                  ${itinerary.segments
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
                ${renderReturnOptions(itinerary, { showSegments: true })}
              </div>
            `;
          })
          .join("")}
      </div>
    </article>
  `;
}

function formatDuration(totalMinutes) {
  const safeMinutes = Math.max(0, Number(totalMinutes || 0));
  const hours = Math.floor(safeMinutes / 60);
  const minutes = safeMinutes % 60;
  if (hours === 0) {
    return `${minutes} min`;
  }
  if (minutes === 0) {
    return `${hours}h`;
  }
  return `${hours}h${String(minutes).padStart(2, "0")}`;
}

function renderRoutes(payload) {
  currentDirectTrips = [];
  updateResultActions();

  const returnSummary = payload.return_date
    ? ` Retours proposes a partir du ${formatFrenchDate(payload.return_date)}.`
    : " Retours proposes sur les dates disponibles.";
  resultSummary.textContent = `${payload.results.length} destination(s) accessibles avec correspondances MAX.${returnSummary} Clique une destination ou un point de la carte pour tracer un seul chemin proprement.`;

  if (!payload.results.length) {
    resultsContainer.innerHTML = emptyState("Aucune correspondance MAX trouvee.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS.routes_max }, { focusSelection: false, scrollSelection: false });
    return;
  }

  const routeGroups = payload.results.map((group, index) => ({
    ...group,
    color: getRouteColor(index),
    route: group.itineraries[0],
    return_date: payload.return_date,
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
  const originStations = uniqueStationPoints(
    routeGroups.map((group) => ({
      name: group.route?.origin,
      coordinates: group.route?.segments?.[0]?.coordinates?.origin,
    }))
  );

  originStations.forEach((originStation) => {
    points.push({
      name: originStation.name,
      detail: "Point de depart",
      coordinates: originStation.coordinates,
      kind: "origin",
      selectable: false,
    });
  });

  const routesByKey = {};
  routeGroups.forEach((group) => {
    points.push({
      key: group.resultKey,
      name: group.destination,
      detail: `Duree totale ${group.itineraries[0].duration_label} - ${group.itineraries[0].connections} correspondance(s)`,
      coordinates: group.coordinates,
      kind: "destination",
    });

    routesByKey[group.resultKey] = {
      route: group.route,
      color: group.color,
      weight: 6,
      opacity: 0.92,
    };
    group.itineraries.forEach((itinerary, index) => {
      routesByKey[routeOptionKey(group.destination, index)] = {
        route: itinerary,
        color: group.color,
        weight: 6,
        opacity: 0.92,
      };
    });
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
  currentDirectTrips = [];
  updateResultActions();

  if (!payload.enabled) {
    resultSummary.textContent = payload.reason || "Mode hybride indisponible.";
    resultsContainer.innerHTML = emptyState(
      `${payload.reason || "Mode hybride indisponible."} Verifie la presence du GTFS SNCF ouvert cote serveur puis relance l'application.`
    );
    renderMapModel({ points: [], legend: PAGE_LEGENDS.hybrid }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultSummary.textContent = `${payload.results.length} prolongement(s) hybride(s) trouves.`;
  if (!payload.results.length) {
    resultsContainer.innerHTML = emptyState("Aucun prolongement ferroviaire n'a ete trouve depuis les gares atteignables en MAX.");
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
            ${item.ter_extension.price_label ? `<span class="result-pill">TER ${escapeHtml(item.ter_extension.price_label)}</span>` : ""}
            ${!item.ter_extension.price_label && item.ter_extension.sections?.some((section) => section.booking_url) ? '<span class="result-pill">Prix par segment ci-dessous</span>' : ""}
            ${!item.ter_extension.price_label && !(item.ter_extension.sections?.some((section) => section.booking_url)) ? '<span class="result-pill">Prix TER indisponible</span>' : ""}
            ${item.direct_max_available ? '<span class="result-pill">Aussi en MAX direct</span>' : ""}
          </div>
          <div class="segment-list">
            ${item.max_itinerary.segments
              .map(
                (segment) => `
                  <div class="segment">
                    <div>
                      <strong>${escapeHtml(segment.origin)} -> ${escapeHtml(segment.destination)}</strong>
                      <span class="segment-kind">TGV MAX</span>
                    </div>
                    <div class="segment-actions">
                      <span>${escapeHtml(segment.departure_time)} -> ${escapeHtml(segment.arrival_time)}</span>
                      ${segment.booking_url ? `<a class="result-link" href="${escapeHtml(segment.booking_url)}" target="_blank" rel="noopener noreferrer">Voir train SNCF</a>` : ""}
                    </div>
                  </div>
                `
              )
              .join("")}
            ${
              item.direct_max_available && item.direct_max_trip
                ? `
                  <div class="segment">
                    <div>
                      <strong>${escapeHtml(item.direct_max_trip.origin)} -> ${escapeHtml(item.direct_max_trip.destination)}</strong>
                      <span class="segment-kind">TGV MAX direct</span>
                    </div>
                    <div class="segment-actions">
                      <span>${escapeHtml(item.direct_max_trip.departure_time)} -> ${escapeHtml(item.direct_max_trip.arrival_time)}</span>
                      ${item.direct_max_trip.booking_url ? `<a class="result-link" href="${escapeHtml(item.direct_max_trip.booking_url)}" target="_blank" rel="noopener noreferrer">Voir train SNCF</a>` : ""}
                    </div>
                  </div>
                `
                : ""
            }
            ${item.ter_extension.sections
              .map(
                (section) => `
                  <div class="segment">
                    <div>
                      <strong>${escapeHtml(section.from)} -> ${escapeHtml(section.to)}</strong>
                      <span class="segment-kind">${escapeHtml(section.mode)}${section.label ? ` ${escapeHtml(section.label)}` : ""}</span>
                    </div>
                    <div class="segment-actions">
                      <span>${escapeHtml(section.departure_time)} -> ${escapeHtml(section.arrival_time)}</span>
                      ${section.booking_url ? `<a class="result-link" href="${escapeHtml(section.booking_url)}" target="_blank" rel="noopener noreferrer">Voir prix</a>` : ""}
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
  uniqueStationPoints(
    payload.results.map((item) => ({
      name: item.max_itinerary?.origin,
      coordinates: item.max_itinerary?.segments?.[0]?.coordinates?.origin,
    }))
  ).forEach((originStation) => {
    points.push({
      name: originStation.name,
      detail: "Point de depart",
      coordinates: originStation.coordinates,
      kind: "origin",
      selectable: false,
    });
  });

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

    const targetPointIdentity = `target-${resultKey}-${targetCoordinates?.latitude}-${targetCoordinates?.longitude}`;
    if (targetCoordinates && !seenPointKeys.has(targetPointIdentity)) {
      seenPointKeys.add(targetPointIdentity);
      points.push({
        key: resultKey,
        name: item.destination,
        detail: item.direct_max_available
          ? `Accessible depuis ${item.via_max_station} et aussi en MAX direct`
          : `Accessible depuis ${item.via_max_station}`,
        coordinates: targetCoordinates,
        kind: "target",
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

async function renderLiveWatch(payload) {
  currentDirectTrips = [];
  updateResultActions();

  if (!payload?.has_live_watch) {
    resultSummary.textContent = payload?.message || "Aucune surveillance live disponible.";
    resultsContainer.innerHTML = emptyState(
      "Aucune synchronisation live n'a encore ete recue. Lance une verification depuis l'extension pour alimenter cette page."
    );
    renderMapModel({ points: [], legend: PAGE_LEGENDS.live_watch }, { focusSelection: false, scrollSelection: false });
    return;
  }

  const summary = payload.summary || {};
  const watches = payload.watches || [];
  const activity = payload.recent_activity || [];
  const capturedAt = payload.captured_at ? formatDateTime(payload.captured_at) : "inconnue";
  let plan = null;
  let worker = null;
  try {
    plan = await apiGet("/api/live-watch/plan");
  } catch (_error) {
    plan = null;
  }
  try {
    worker = await apiGet("/api/live-worker/latest");
  } catch (_error) {
    worker = null;
  }

  resultSummary.textContent = `${summary.watch_count || 0} surveillance(s) | ${summary.zero_watch_count || 0} avec 0 € | ${summary.zero_offer_count || 0} train(s) 0 € visibles | derniere sync ${capturedAt}`;
  const planLabel = plan?.has_plan
    ? `${plan.watch_count || plan.watches?.length || 0} surveillance(s) planifiee(s)`
    : "Aucun plan automatique actif";
  const planGroups = groupPlanWatches(plan?.watches || [], watches);
  const planCounts = plannedVsActiveCounts(plan?.watches || [], watches);

  const summaryHtml = `
    <div class="live-plan-actions">
      <button type="button" class="primary-button" id="activate-default-plan">Activer Bordeaux/Paris weekend</button>
      <button type="button" class="secondary-button" id="clear-default-plan">Supprimer le plan</button>
      <span class="live-status-note">${escapeHtml(planLabel)}</span>
      ${
        plan?.has_plan
          ? `<span class="live-status-note">${planCounts.activeCount}/${planCounts.plannedCount} prises en charge par l'extension</span>`
          : ""
      }
    </div>
    <section class="live-summary-grid">
      <div class="live-stat"><div class="live-stat-label">Surveillances</div><div class="live-stat-value">${summary.watch_count || 0}</div></div>
      <div class="live-stat"><div class="live-stat-label">Checks OK</div><div class="live-stat-value">${summary.ok_count || 0}</div></div>
      <div class="live-stat"><div class="live-stat-label">Watches avec 0 €</div><div class="live-stat-value">${summary.zero_watch_count || 0}</div></div>
      <div class="live-stat"><div class="live-stat-label">Trains 0 € visibles</div><div class="live-stat-value">${summary.zero_offer_count || 0}</div></div>
    </section>
  `;

  const workerHtml = worker?.has_worker
    ? `
      <div class="activity-item">
        <strong>Statut worker</strong>
        <div class="muted">${escapeHtml(formatDateTime(worker.captured_at))} | ${escapeHtml(worker.worker?.status || "unknown")}</div>
        <div>${escapeHtml(worker.worker?.session_hint || "")}</div>
        <div class="muted">Backend ${escapeHtml(worker.backend_base_url || "")}</div>
        ${worker.worker?.last_error ? `<div>${escapeHtml(worker.worker.last_error)}</div>` : ""}
      </div>
    `
    : `<div class="empty-state">Aucun heartbeat worker recu.</div>`;

  const activityHtml = activity.length
    ? activity
        .map(
          (item) => `
            <div class="activity-item">
              <strong>${escapeHtml(item.route || "Trajet")}</strong>
              <div class="muted">${escapeHtml(item.watch_date || "")} | ${escapeHtml(formatDateTime(item.at))}</div>
              <div>${escapeHtml(historyLabelFromApi(item))}</div>
            </div>
          `
        )
        .join("")
    : `<div class="empty-state">Aucune activite recente.</div>`;

  const watchHtml = watches.length
    ? watches
        .map((watch) => {
          const zeroOffers = watch.zero_offers || [];
          const departureList = zeroOffers.map((offer) => offer.departureTime).filter(Boolean).slice(0, 5).join(", ");
          return `
            <article class="watch-card">
              <h3>${escapeHtml(watch.origin_label)} -> ${escapeHtml(watch.destination_label)}</h3>
              <p class="muted">${escapeHtml(formatWatchDate(watch.watch_date))} | statut ${escapeHtml(watch.status || "pending")} | checks ${watch.check_count || 0} | succes ${watch.success_count || 0}</p>
              <div class="watch-badges">
                <span class="watch-badge${watch.zero_offer_count ? " is-alert" : ""}">${watch.zero_offer_count || 0} train(s) a 0 €</span>
                <span class="watch-badge">Dernier succes ${escapeHtml(formatDateTime(watch.last_success_at))}</span>
                ${
                  watch.last_error
                    ? `<span class="watch-badge is-error">${escapeHtml(watch.last_error)}</span>`
                    : ""
                }
              </div>
              ${
                departureList
                  ? `<div class="watch-history"><span class="history-chip">Departs 0 €: ${escapeHtml(departureList)}</span></div>`
                  : ""
              }
              ${
                (watch.history || []).length
                  ? `
                    <div class="watch-history">
                      ${(watch.history || [])
                        .slice(0, 4)
                        .map(
                          (entry) => `
                            <span class="history-chip">${escapeHtml(formatDateTime(entry.at))} · ${escapeHtml(historyLabel(entry))}</span>
                          `
                        )
                        .join("")}
                    </div>
                  `
                  : ""
              }
            </article>
          `;
        })
        .join("")
    : `<div class="empty-state">Aucune surveillance synchronisee.</div>`;

  const planHtml = planGroups.length
    ? planGroups
        .map(
          (group) => `
            <article class="plan-group">
              <h4>${escapeHtml(group.route)}</h4>
              <div class="muted">${group.dates.length} date(s) planifiee(s)${group.ruleLabel ? ` | regle ${escapeHtml(group.ruleLabel)}` : ""}</div>
              <div class="plan-group-dates">
                ${group.dates
                  .map(
                    (item) => `
                      <span class="plan-date-chip${item.isSynced ? " is-synced" : " is-pending"}">
                        ${escapeHtml(formatWatchDate(item.watchDate))}${item.isSynced ? " · prise en charge" : " · planifiee"}
                      </span>
                    `
                  )
                  .join("")}
              </div>
            </article>
          `
        )
        .join("")
    : `<div class="empty-state">Aucun plan automatique configure.</div>`;

  resultsContainer.innerHTML = `
    ${summaryHtml}
    <section class="live-watch-layout">
      <article class="live-watch-panel">
        <h3>Worker navigateur</h3>
        <div class="activity-list">${workerHtml}</div>
      </article>
      <article class="live-watch-panel">
        <h3>Plan actif</h3>
        <div class="plan-group-list">${planHtml}</div>
      </article>
      <article class="live-watch-panel">
        <h3>Activite recente</h3>
        <div class="activity-list">${activityHtml}</div>
      </article>
      <article class="live-watch-panel">
        <h3>Surveillances</h3>
        <div class="watch-grid">${watchHtml}</div>
      </article>
    </section>
  `;

  document.getElementById("activate-default-plan")?.addEventListener("click", async () => {
    setLoadingState(true);
    try {
      await apiPost("/api/live-watch/plan/default-weekend-bordeaux-paris");
      resultSummary.textContent = "Plan active. L'extension l'adoptera automatiquement au prochain cycle, en general sous 1 minute.";
      await loadCurrentPage();
    } finally {
      setLoadingState(false);
    }
  });

  document.getElementById("clear-default-plan")?.addEventListener("click", async () => {
    setLoadingState(true);
    try {
      await apiPost("/api/live-watch/plan/clear");
      await loadCurrentPage();
    } finally {
      setLoadingState(false);
    }
  });

  renderMapModel({ points: [], legend: PAGE_LEGENDS.live_watch }, { focusSelection: false, scrollSelection: false });
}

function historyLabel(entry) {
  switch (entry?.type) {
    case "zero_added":
      return `Nouveau 0 €: ${entry.count || 0} train(s)`;
    case "zero_removed":
      return `0 € retire: ${entry.count || 0} train(s)`;
    case "check_error":
      return `Erreur: ${entry.error || "Replay impossible"}`;
    case "check_ok":
      return `Check OK: ${entry.zeroOfferCount || entry.zero_offer_count || 0} train(s) a 0 €`;
    default:
      return "Evenement";
  }
}

function historyLabelFromApi(item) {
  return historyLabel({
    type: item?.type,
    ...(item?.details || {}),
  });
}

function groupPlanWatches(planWatches = [], activeWatches = []) {
  const activeIds = new Set((activeWatches || []).map((watch) => watch.id));
  const groups = new Map();

  for (const watch of planWatches) {
    const route = `${watch.origin_label} -> ${watch.destination_label}`;
    if (!groups.has(route)) {
      groups.set(route, {
        route,
        ruleLabel: watch.rule_label || null,
        dates: [],
      });
    }
    groups.get(route).dates.push({
      watchDate: watch.watch_date,
      isSynced: activeIds.has(watch.id),
    });
  }

  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      dates: group.dates.sort((left, right) => (left.watchDate || "").localeCompare(right.watchDate || "")),
    }))
    .sort((left, right) => left.route.localeCompare(right.route));
}

function plannedVsActiveCounts(planWatches = [], activeWatches = []) {
  const activeIds = new Set((activeWatches || []).map((watch) => watch.id));
  let activeCount = 0;
  for (const watch of planWatches || []) {
    if (activeIds.has(watch.id)) {
      activeCount += 1;
    }
  }
  return {
    plannedCount: (planWatches || []).length,
    activeCount,
  };
}

function formatWatchDate(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(`${value}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("fr-FR", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(parsed);
}

function formatDateTime(value) {
  if (!value) {
    return "jamais";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}

async function loadCurrentPage() {
  const params = syncUrlAndNav();
  const values = getParamsObject();

  if (page.key === "live_watch") {
    resultSummary.textContent = "Chargement...";
    setLoadingState(true);
    try {
      const payload = await apiGet("/api/live-watch/latest");
      await renderLiveWatch(payload);
    } catch (error) {
      resultSummary.textContent = error.message;
      resultsContainer.innerHTML = emptyState(error.message);
      renderMapModel({ points: [], legend: PAGE_LEGENDS.live_watch }, { focusSelection: false, scrollSelection: false });
    } finally {
      setLoadingState(false);
    }
    return;
  }

  if (!values.origin || !values.date) {
    resultSummary.textContent = "Renseigne au moins un depart et une date.";
    resultsContainer.innerHTML = emptyState("Complete les parametres pour lancer la recherche.");
    renderMapModel({ points: [], legend: PAGE_LEGENDS[page.key] || [] }, { focusSelection: false, scrollSelection: false });
    return;
  }

  resultSummary.textContent = "Chargement...";
  setLoadingState(true);

  try {
    if (page.key === "direct") {
      const directParams = new URLSearchParams(params);
      directParams.set("include_returns", "false");
      const payload = await apiGet(`/api/direct?${directParams.toString()}`);
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
        resultSummary.textContent = "Mode indisponible : le GTFS SNCF ouvert manque cote serveur.";
        resultsContainer.innerHTML = emptyState(
          "Le calcul MAX + TER automatique a besoin du GTFS SNCF ouvert charge cote serveur."
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
  } finally {
    setLoadingState(false);
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
    const response = await fetch("/api/refresh", { method: "POST" });
    const payload = await response.json();
    await loadCurrentPage();
    const zeroWatch = payload.zero_watch;
    if (zeroWatch) {
      const parts = [];
      if (zeroWatch.initialized) {
        parts.push(`Premier snapshot enregistre (${zeroWatch.current_zero_count} trajets a 0 EUR).`);
      } else {
        parts.push(
          `Snapshot mis a jour: ${zeroWatch.new_zero_count} nouveaux, ${zeroWatch.removed_zero_count} disparus, ${zeroWatch.current_zero_count} trajets a 0 EUR actuellement.`
        );
      }
      window.alert(parts.join(" "));
    }
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = "Rafraichir les donnees";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  renderMapLegend(PAGE_LEGENDS[page.key] || []);
  updateResultActions();
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

  exploreButton.addEventListener("click", () => {
    loadCurrentPage();
  });

  if (page.key === "live_watch") {
    refreshButton.textContent = "Rafraichir la surveillance";
    refreshButton.addEventListener("click", loadCurrentPage);
  } else {
    refreshButton.addEventListener("click", refreshData);
  }

  if (page.key === "live_watch") {
    window.setInterval(() => {
      loadCurrentPage();
    }, 30_000);
  }
});
