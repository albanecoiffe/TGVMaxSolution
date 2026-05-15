const statusNode = document.getElementById("status");
const eventsNode = document.getElementById("events");
const replayResultNode = document.getElementById("replay-result");
const originLabelInput = document.getElementById("origin-label");
const destinationLabelInput = document.getElementById("destination-label");
const outwardDatetimeInput = document.getElementById("outward-datetime");
const backendBaseUrlInput = document.getElementById("backend-base-url");
const watchesNode = document.getElementById("watches");
const watchHintNode = document.getElementById("watch-hint");
const watchSummaryNode = document.getElementById("watch-summary");

function setStatus(message) {
  statusNode.textContent = message;
}

function renderEvents(events) {
  eventsNode.innerHTML = "";
  const items = [...events].reverse();
  for (const event of items) {
    const li = document.createElement("li");
    const summary = document.createElement("div");
    summary.innerHTML = `<strong>${event.method}</strong> ${event.status ?? "ERR"} <code>${event.url}</code>`;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${event.transport} | ${event.durationMs} ms | ${event.startedAt}`;
    li.append(summary, meta);
    eventsNode.appendChild(li);
  }
}

async function request(type) {
  return chrome.runtime.sendMessage({ type });
}

function isoToLocalDateTimeInput(value) {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const offsetMs = parsed.getTimezoneOffset() * 60_000;
  return new Date(parsed.getTime() - offsetMs).toISOString().slice(0, 16);
}

function localDateTimeInputToIso(value) {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toISOString();
}

function renderReplay(payload) {
  replayResultNode.textContent = payload ? JSON.stringify(payload, null, 2) : "";
}

function fillFormFromWatch(watch) {
  originLabelInput.value = watch.originLabel || "";
  destinationLabelInput.value = watch.destinationLabel || "";
  outwardDatetimeInput.value = watch.watchDate ? `${watch.watchDate}T06:00` : "";
}

function watchIdFromForm() {
  return [
    originLabelInput.value.trim(),
    destinationLabelInput.value.trim(),
    dateOnlyFromInput(outwardDatetimeInput.value) || "",
  ].join("|");
}

function dateOnlyFromInput(value) {
  if (!value) {
    return null;
  }
  return value.slice(0, 10);
}

function formatWatchDate(value) {
  if (!value) {
    return "";
  }
  try {
    return new Date(`${value}T00:00:00`).toLocaleDateString("fr-FR");
  } catch {
    return value;
  }
}

function formatDateTime(value) {
  if (!value) {
    return "jamais";
  }
  try {
    return new Date(value).toLocaleString("fr-FR");
  } catch {
    return value;
  }
}

function watchStatusLabel(watch) {
  if (watch.lastError && !watch.lastStatus) {
    return "Erreur";
  }
  switch (watch.lastStatus) {
    case "ok":
      return "OK";
    case "waiting_tab":
      return "En attente d'un onglet SNCF Connect";
    case "error":
      return "Erreur";
    default:
      return "En attente du premier check";
  }
}

function watchStatusPriority(watch) {
  if ((watch.lastZeroTravelIds?.length || 0) > 0) {
    return 0;
  }
  switch (watch.lastStatus) {
    case "ok":
      return 1;
    case "error":
      return 2;
    case "waiting_tab":
      return 3;
    default:
      return 4;
  }
}

function summarizeZeroDepartures(watch) {
  const offers = watch?.lastReplay?.response?.zeroOffers || [];
  const departures = offers
    .map((offer) => offer?.departureTime)
    .filter(Boolean)
    .slice(0, 4);
  return departures.length ? departures.join(", ") : null;
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
      return `Check OK: ${entry.zeroOfferCount || 0} train(s) a 0 €`;
    default:
      return "Evenement";
  }
}

function renderWatchHistory(watch) {
  const entries = (watch.history || []).slice(0, 4);
  if (!entries.length) {
    return null;
  }
  const wrapper = document.createElement("div");
  wrapper.className = "watch-history";
  const title = document.createElement("div");
  title.className = "watch-history-title";
  title.textContent = "Historique recent";
  const list = document.createElement("div");
  list.className = "watch-history-list";
  list.innerHTML = entries
    .map((entry) => `${formatDateTime(entry.at)}: ${historyLabel(entry)}`)
    .join("<br>");
  wrapper.append(title, list);
  return wrapper;
}

function sortWatches(watches) {
  return [...watches].sort((left, right) => {
    const zeroDiff = (right.lastZeroTravelIds?.length || 0) - (left.lastZeroTravelIds?.length || 0);
    if (zeroDiff !== 0) {
      return zeroDiff;
    }
    const statusDiff = watchStatusPriority(left) - watchStatusPriority(right);
    if (statusDiff !== 0) {
      return statusDiff;
    }
    const alertDiff = (right.lastAlertAt || "").localeCompare(left.lastAlertAt || "");
    if (alertDiff !== 0) {
      return alertDiff;
    }
    return (left.watchDate || "").localeCompare(right.watchDate || "");
  });
}

function renderWatchSummary(watches) {
  if (!watchSummaryNode) {
    return;
  }
  if (!watches?.length) {
    watchSummaryNode.textContent = "Aucune surveillance active.";
    return;
  }

  const total = watches.length;
  const okCount = watches.filter((watch) => watch.lastStatus === "ok").length;
  const liveZeroCount = watches.filter((watch) => (watch.lastZeroTravelIds?.length || 0) > 0).length;
  const errorCount = watches.filter((watch) => watch.lastStatus === "error").length;
  const pendingCount = watches.filter((watch) => watch.lastStatus === "waiting_tab" || watch.lastStatus === "pending").length;
  const totalZeroTrains = watches.reduce((sum, watch) => sum + (watch.lastZeroTravelIds?.length || 0), 0);

  watchSummaryNode.innerHTML = `
    <div class="summary-row">
      <span class="summary-chip">${total} surveillance(s)</span>
      <span class="summary-chip">${okCount} OK</span>
      <span class="summary-chip">${liveZeroCount} avec 0 €</span>
      <span class="summary-chip">${totalZeroTrains} train(s) 0 € visibles</span>
      <span class="summary-chip">${errorCount} erreur(s)</span>
      <span class="summary-chip">${pendingCount} en attente</span>
    </div>
  `;
}

function renderWatches(watches) {
  watchesNode.innerHTML = "";
  renderWatchSummary(watches || []);
  if (!watches?.length) {
    watchesNode.textContent = "Aucune surveillance active.";
    return;
  }
  for (const watch of sortWatches(watches)) {
    const container = document.createElement("div");
    container.className = "watch";
    const route = document.createElement("div");
    route.className = "watch-route";
    route.textContent = `${watch.originLabel} → ${watch.destinationLabel}`;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `${formatWatchDate(watch.watchDate)} | journée entière | ${watch.lastZeroTravelIds?.length || 0} train(s) à 0 €`;
    const health = document.createElement("div");
    health.className = "meta";
    health.textContent = `Etat: ${watchStatusLabel(watch)} | checks: ${watch.checkCount || 0} | succes: ${watch.successCount || 0}`;
    const timing = document.createElement("div");
    timing.className = "meta";
    timing.textContent = `Dernier check: ${formatDateTime(watch.lastCheckedAt)} | dernier succes: ${formatDateTime(watch.lastSuccessAt)} | derniere alerte: ${formatDateTime(watch.lastAlertAt)}`;
    const row = document.createElement("div");
    row.className = "watch-row";
    const actions = document.createElement("div");
    actions.className = "watch-actions";
    const useButton = document.createElement("button");
    useButton.textContent = "Charger";
    useButton.addEventListener("click", () => {
      fillFormFromWatch(watch);
      setStatus(`Formulaire recharge avec ${watch.originLabel} → ${watch.destinationLabel} le ${formatWatchDate(watch.watchDate)}.`);
    });
    const removeButton = document.createElement("button");
    removeButton.textContent = "Retirer";
    removeButton.addEventListener("click", async () => {
      const response = await chrome.runtime.sendMessage({
        type: "sncf-probe-remove-watch",
        payload: { id: watch.id },
      });
      if (!response?.ok) {
        setStatus(`Erreur suppression: ${response?.error || "inconnue"}`);
        return;
      }
      await refresh();
    });
    actions.append(useButton, removeButton);
    row.append(route, actions);
    container.append(row, meta);
    const highlights = summarizeZeroDepartures(watch);
    if (highlights) {
      const highlightNode = document.createElement("div");
      highlightNode.className = "watch-highlights";
      highlightNode.innerHTML = `<strong>Departs 0 €:</strong> ${highlights}`;
      container.appendChild(highlightNode);
    }
    container.append(health, timing);
    const historyNode = renderWatchHistory(watch);
    if (historyNode) {
      container.appendChild(historyNode);
    }
    if (watch.lastError) {
      const error = document.createElement("div");
      error.className = "meta";
      error.textContent = `Erreur: ${watch.lastError}`;
      container.appendChild(error);
    }
    watchesNode.appendChild(container);
  }
}

function fillFormFromEvent(event) {
  if (!event?.requestBodyPreview) {
    return;
  }
  try {
    const body = JSON.parse(event.requestBodyPreview);
    originLabelInput.value = body?.mainJourney?.origin?.label || "";
    destinationLabelInput.value = body?.mainJourney?.destination?.label || "";
    outwardDatetimeInput.value = isoToLocalDateTimeInput(body?.schedule?.outward?.date || "");
  } catch (_error) {
    // Ignore parse failures for the popup form.
  }
}

async function refresh() {
  await chrome.runtime.sendMessage({
    type: "sncf-probe-hydrate-plan-now",
  });
  const response = await request("sncf-probe-list");
  if (!response?.ok) {
    setStatus(`Erreur: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus(`${response.events.length} evenement(s) captures`);
  renderEvents(response.events);
  const replayResponse = await request("sncf-probe-last-replay");
  if (replayResponse?.ok) {
    renderReplay(replayResponse.payload);
  }
  const itineraryResponse = await request("sncf-probe-last-itinerary");
  if (itineraryResponse?.ok) {
    fillFormFromEvent(itineraryResponse.event);
  }
  const watchesResponse = await chrome.runtime.sendMessage({
    type: "sncf-probe-list-watches",
  });
  if (watchesResponse?.ok) {
    renderWatches(watchesResponse.watches);
  } else if (watchSummaryNode) {
    watchSummaryNode.textContent = "Impossible de charger les surveillances.";
  }
  const backendResponse = await chrome.runtime.sendMessage({
    type: "sncf-probe-get-backend-base-url",
  });
  if (backendResponse?.ok && backendBaseUrlInput) {
    backendBaseUrlInput.value = backendResponse.baseUrl || "";
  }
}

document.getElementById("refresh").addEventListener("click", refresh);
document.getElementById("clear").addEventListener("click", async () => {
  const response = await request("sncf-probe-clear");
  if (!response?.ok) {
    setStatus(`Erreur: ${response?.error || "inconnue"}`);
    return;
  }
  await refresh();
});
document.getElementById("export").addEventListener("click", async () => {
  const response = await request("sncf-probe-export");
  if (!response?.ok) {
    setStatus(`Erreur: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus(`Export lance pour ${response.count} evenement(s)`);
});
document.getElementById("replay").addEventListener("click", async () => {
  setStatus("Replay du dernier itineraries en cours...");
  const response = await request("sncf-probe-replay-last-itinerary");
  if (!response?.ok) {
    setStatus(`Erreur replay: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus("Replay termine");
  renderReplay(response.payload);
});
document.getElementById("replay-custom").addEventListener("click", async () => {
  setStatus("Replay parametre en cours...");
  const response = await chrome.runtime.sendMessage({
    type: "sncf-probe-replay-custom-itinerary",
    payload: {
      originLabel: originLabelInput.value.trim() || null,
      destinationLabel: destinationLabelInput.value.trim() || null,
      outwardDate: localDateTimeInputToIso(outwardDatetimeInput.value),
    },
  });
  if (!response?.ok) {
    setStatus(`Erreur replay: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus("Replay parametre termine");
  renderReplay(response.payload);
});
document.getElementById("watch").addEventListener("click", async () => {
  const payload = {
    id: watchIdFromForm(),
    originLabel: originLabelInput.value.trim(),
    destinationLabel: destinationLabelInput.value.trim(),
    watchDate: dateOnlyFromInput(outwardDatetimeInput.value),
  };
  if (!payload.originLabel || !payload.destinationLabel || !payload.watchDate) {
    setStatus("Origine, destination et date sont obligatoires pour surveiller.");
    return;
  }
  const response = await chrome.runtime.sendMessage({
    type: "sncf-probe-add-watch",
    payload,
  });
  if (!response?.ok) {
    setStatus(`Erreur surveillance: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus("Surveillance active. Premier check lance, puis verification toutes les 5 minutes si un onglet SNCF Connect est ouvert.");
  await refresh();
});

document.getElementById("watch-now").addEventListener("click", async () => {
  setStatus("Verification immediate des surveillances en cours...");
  const response = await chrome.runtime.sendMessage({
    type: "sncf-probe-run-watches-now",
  });
  if (!response?.ok) {
    setStatus(`Erreur verification: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus("Verification immediate terminee.");
  await refresh();
});

backendBaseUrlInput?.addEventListener("change", async () => {
  const value = backendBaseUrlInput.value.trim();
  if (!value) {
    return;
  }
  const response = await chrome.runtime.sendMessage({
    type: "sncf-probe-set-backend-base-url",
    payload: {
      baseUrl: value,
    },
  });
  if (!response?.ok) {
    setStatus(`Erreur backend: ${response?.error || "inconnue"}`);
    return;
  }
  setStatus(`Backend live-watch mis a jour: ${value}`);
  await chrome.runtime.sendMessage({
    type: "sncf-probe-hydrate-plan-now",
  });
  await refresh();
});

refresh();

if (watchHintNode) {
  watchHintNode.textContent = "Pour Surveiller, seule la date est utilisee. L'heure ne sert qu'au replay manuel.";
}
