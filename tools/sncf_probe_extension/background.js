const STORAGE_KEY = "sncf_probe_events";
const REPLAY_STORAGE_KEY = "sncf_probe_last_replay";
const WATCHES_STORAGE_KEY = "sncf_probe_watches";
const WATCH_TAB_STORAGE_KEY = "sncf_probe_watch_tab_id";
const BACKEND_BASE_URL_STORAGE_KEY = "sncf_probe_backend_base_url";
const MAX_EVENTS = 200;
const WATCH_ALARM_NAME = "sncf-probe-watch-alarm";
const WATCH_INTERVAL_MINUTES = 1;
const WATCH_HISTORY_LIMIT = 12;
const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000";
const WATCH_TAB_URL = "https://www.sncf-connect.com/home/search";
const NOTIFICATION_ICON_DATA_URL =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAQAAAAAYLlVAAAA8ElEQVR4Ae3XwQmDQBRF0V8p2Ih2YCPYgI1gAzaCDdgINqAj2IAQ9vuK8d/3rWvJgjHchJwUeN9zzvE2tm3bTgAAAAAAAAAAwM5rjDE+L5fL8m7bNm7btm3LJEmS9Hq9fJ7n+XEc53meZ9m2bdM0TZqmKYoikmVZlmVZliRJkiRJ0jRNmqaJoiiiKIqiKIrC8zxPmqaJoiiqqirLsgzDMIwxDMO+73u+75IkSZIkSZqm6bouyzJNmqbpui7LskzTNM0wDMMwDMMwDMPwPM/zfN/3fd/3fd/3fd/3AQAAAAAAAAB4M/oANL7f36U4nHMAAAAASUVORK5CYII=";

async function loadEvents() {
  const stored = await chrome.storage.local.get(STORAGE_KEY);
  return stored[STORAGE_KEY] || [];
}

async function saveEvents(events) {
  await chrome.storage.local.set({ [STORAGE_KEY]: events });
}

async function loadLastReplay() {
  const stored = await chrome.storage.local.get(REPLAY_STORAGE_KEY);
  return stored[REPLAY_STORAGE_KEY] || null;
}

async function saveLastReplay(payload) {
  await chrome.storage.local.set({ [REPLAY_STORAGE_KEY]: payload });
}

async function loadWatches() {
  const stored = await chrome.storage.local.get(WATCHES_STORAGE_KEY);
  return stored[WATCHES_STORAGE_KEY] || [];
}

async function saveWatches(watches) {
  await chrome.storage.local.set({ [WATCHES_STORAGE_KEY]: watches });
}

async function loadWatchTabId() {
  const stored = await chrome.storage.local.get(WATCH_TAB_STORAGE_KEY);
  return stored[WATCH_TAB_STORAGE_KEY] || null;
}

async function saveWatchTabId(tabId) {
  await chrome.storage.local.set({ [WATCH_TAB_STORAGE_KEY]: tabId });
}

async function loadBackendBaseUrl() {
  const stored = await chrome.storage.local.get(BACKEND_BASE_URL_STORAGE_KEY);
  return stored[BACKEND_BASE_URL_STORAGE_KEY] || DEFAULT_BACKEND_BASE_URL;
}

async function saveBackendBaseUrl(value) {
  await chrome.storage.local.set({ [BACKEND_BASE_URL_STORAGE_KEY]: value });
}

async function buildBackendUrl(path) {
  const baseUrl = await loadBackendBaseUrl();
  return `${baseUrl.replace(/\/+$/, "")}${path}`;
}

function nowIso() {
  return new Date().toISOString();
}

function buildWatchId(payload) {
  return [
    payload.originLabel || "",
    payload.destinationLabel || "",
    payload.watchDate || "",
  ].join("|");
}

function buildWatchReplayIso(watchDate) {
  return `${watchDate}T04:00:00.000Z`;
}

function latestItinerariesEvent(events) {
  const itineraryUrl = "https://www.sncf-connect.com/bff/api/v1/itineraries";
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.url === itineraryUrl) {
      return events[index];
    }
  }
  return null;
}

function buildReplayPayload(event, overrides = {}) {
  return {
    url: event.url,
    method: event.method || "POST",
    headers: event.requestHeaders || {},
    requestBodyPreview: event.requestBodyPreview || "",
    overrides,
  };
}

function extractWatchSeed(event) {
  return {
    headers: event?.requestHeaders || {},
    requestBodyPreview: event?.requestBodyPreview || "",
    seedCapturedAt: event?.startedAt || nowIso(),
  };
}

function applyWatchSeed(watch, event) {
  if (!event) {
    return watch;
  }
  const seed = extractWatchSeed(event);
  return {
    ...watch,
    ...seed,
  };
}

function buildStoredWatchFromPlan(plannedWatch, existing, latestEvent) {
  const baseWatch = {
    id: plannedWatch.id,
    originLabel: plannedWatch.origin_label,
    destinationLabel: plannedWatch.destination_label,
    watchDate: plannedWatch.watch_date,
    createdAt: existing?.createdAt || nowIso(),
    lastCheckedAt: existing?.lastCheckedAt || null,
    lastSuccessAt: existing?.lastSuccessAt || null,
    lastAlertAt: existing?.lastAlertAt || null,
    lastAlertCount: existing?.lastAlertCount || 0,
    lastStatus: existing?.lastStatus || "pending",
    checkCount: existing?.checkCount || 0,
    successCount: existing?.successCount || 0,
    lastZeroTravelIds: existing?.lastZeroTravelIds || [],
    lastReplay: existing?.lastReplay || null,
    lastError: existing?.lastError || null,
    history: existing?.history || [],
    headers: existing?.headers || {},
    requestBodyPreview: existing?.requestBodyPreview || "",
    seedCapturedAt: existing?.seedCapturedAt || null,
  };
  return applyWatchSeed(baseWatch, latestEvent);
}

async function replayOnActiveTab(payload, sendResponse) {
  const [tab] = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });
  if (!tab?.id) {
    sendResponse({ ok: false, error: "Aucun onglet actif detecte" });
    return;
  }

  chrome.tabs.sendMessage(
    tab.id,
    {
      type: "sncf-probe-replay-in-page",
      payload,
    },
    (response) => {
      if (chrome.runtime.lastError) {
        sendResponse({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      sendResponse(response || { ok: false, error: "Pas de reponse de l'onglet" });
    }
  );
}

async function findSncfTabs() {
  const tabs = await chrome.tabs.query({
    url: ["https://www.sncf-connect.com/*"],
  });
  return tabs.filter((tab) => typeof tab.id === "number");
}

async function waitForTabComplete(tabId, timeoutMs = 15000) {
  return new Promise((resolve) => {
    let settled = false;
    const timeoutId = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, timeoutMs);

    const listener = (_updatedTabId, changeInfo, tab) => {
      if (_updatedTabId !== tabId) {
        return;
      }
      if (changeInfo.status === "complete" && /^https:\/\/www\.sncf-connect\.com\//.test(tab?.url || "")) {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeoutId);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(true);
      }
    };

    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function ensureDedicatedWatchTab() {
  const storedTabId = await loadWatchTabId();
  if (storedTabId) {
    try {
      const existing = await chrome.tabs.get(storedTabId);
      if (existing?.id && /^https:\/\/www\.sncf-connect\.com\//.test(existing.url || "")) {
        return existing;
      }
    } catch (_error) {
      // Ignore stale tab ids.
    }
  }

  const tabs = await findSncfTabs();
  if (tabs.length) {
    await saveWatchTabId(tabs[0].id);
    return tabs[0];
  }

  const created = await chrome.tabs.create({
    url: WATCH_TAB_URL,
    active: false,
    pinned: true,
  });
  if (created?.id) {
    await saveWatchTabId(created.id);
    await waitForTabComplete(created.id);
  }
  return created || null;
}

async function replayOnSpecificTab(tabId, payload) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(
      tabId,
      {
        type: "sncf-probe-replay-in-page",
        payload,
      },
      (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { ok: false, error: "Pas de reponse de l'onglet" });
      }
    );
  });
}

async function replayOnAnySncfTab(payload) {
  const primaryTab = await ensureDedicatedWatchTab();
  const tabs = primaryTab?.id
    ? [primaryTab, ...(await findSncfTabs()).filter((tab) => tab.id !== primaryTab.id)]
    : await findSncfTabs();
  if (!tabs.length) {
    return { ok: false, error: "Impossible d'ouvrir un onglet SNCF Connect" };
  }

  let lastError = null;
  for (const tab of tabs) {
    let response = await replayOnSpecificTab(tab.id, payload);
    if (!response?.ok && /Receiving end does not exist/i.test(response?.error || "")) {
      try {
        await chrome.tabs.reload(tab.id);
        await waitForTabComplete(tab.id);
        response = await replayOnSpecificTab(tab.id, payload);
      } catch (_error) {
        // Keep the original response error below.
      }
    }
    if (response?.ok) {
      await saveWatchTabId(tab.id);
      return response;
    }
    lastError = response?.error || "Pas de reponse de l'onglet";
  }

  return {
    ok: false,
    error: lastError || "Aucun onglet SNCF Connect exploitable",
  };
}

async function ensureWatchAlarm() {
  await chrome.alarms.create(WATCH_ALARM_NAME, {
    delayInMinutes: 1,
    periodInMinutes: WATCH_INTERVAL_MINUTES,
  });
}

function extractZeroTravelIds(replayPayload) {
  const offers = replayPayload?.response?.zeroOffers || [];
  return offers
    .map((offer) => offer?.travelId)
    .filter((value) => typeof value === "string" && value);
}

async function notifyNewZeroOffers(watch, newTravelIds, replayPayload) {
  const routeLabel = `${watch.originLabel} → ${watch.destinationLabel}`;
  const departures = (replayPayload?.response?.zeroOffers || [])
    .filter((offer) => newTravelIds.includes(offer?.travelId))
    .map((offer) => offer?.departureTime)
    .filter(Boolean)
    .slice(0, 5)
    .join(", ");
  const message = departures
    ? `${newTravelIds.length} nouveau(x) train(s) à 0 €: ${departures}`
    : `${newTravelIds.length} nouveau(x) train(s) à 0 € détecté(s).`;

  await chrome.notifications.create(`sncf-probe-${Date.now()}`, {
    type: "basic",
    iconUrl: NOTIFICATION_ICON_DATA_URL,
    title: routeLabel,
    message,
  });
}

function updateWatchState(watch, updates = {}) {
  return {
    ...watch,
    ...updates,
  };
}

function buildLiveWatchPayload(watches) {
  const normalizedWatches = (watches || []).map((watch) => ({
    id: watch.id,
    origin_label: watch.originLabel,
    destination_label: watch.destinationLabel,
    watch_date: watch.watchDate,
    status: watch.lastStatus || "pending",
    zero_offer_count: watch.lastZeroTravelIds?.length || 0,
    check_count: watch.checkCount || 0,
    success_count: watch.successCount || 0,
    last_checked_at: watch.lastCheckedAt || null,
    last_success_at: watch.lastSuccessAt || null,
    last_alert_at: watch.lastAlertAt || null,
    last_error: watch.lastError || null,
    zero_offers: watch.lastReplay?.response?.zeroOffers || [],
    history: watch.history || [],
  }));

  return {
    source: "sncf-probe-extension",
    captured_at: nowIso(),
    summary: {
      watch_count: normalizedWatches.length,
      ok_count: normalizedWatches.filter((watch) => watch.status === "ok").length,
      error_count: normalizedWatches.filter((watch) => watch.status === "error").length,
      waiting_count: normalizedWatches.filter((watch) => watch.status === "waiting_tab" || watch.status === "pending").length,
      zero_watch_count: normalizedWatches.filter((watch) => watch.zero_offer_count > 0).length,
      zero_offer_count: normalizedWatches.reduce((sum, watch) => sum + watch.zero_offer_count, 0),
    },
    watches: normalizedWatches,
  };
}

async function syncWatchesToBackend(watches) {
  try {
    const url = await buildBackendUrl("/api/live-watch/ingest");
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(buildLiveWatchPayload(watches)),
    });
    return response.ok;
  } catch (_error) {
    return false;
  }
}

async function syncWorkerHeartbeat(payload) {
  try {
    const url = await buildBackendUrl("/api/live-worker/heartbeat");
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    return response.ok;
  } catch (_error) {
    return false;
  }
}

async function loadWatchesFromBackendPlan() {
  try {
    const url = await buildBackendUrl("/api/live-watch/plan");
    const response = await fetch(url);
    if (!response.ok) {
      return null;
    }
    const payload = await response.json();
    if (!payload?.has_plan || !Array.isArray(payload.watches)) {
      return null;
    }
    return payload.watches;
  } catch (_error) {
    return null;
  }
}

async function hydrateWatchesFromPlan() {
  const [localWatches, plannedWatches, events] = await Promise.all([
    loadWatches(),
    loadWatchesFromBackendPlan(),
    loadEvents(),
  ]);
  if (!plannedWatches?.length) {
    return localWatches;
  }

  const latestEvent = latestItinerariesEvent(events);
  const nextWatches = plannedWatches.map((plannedWatch) => {
    const existing = localWatches.find((item) => item.id === plannedWatch.id);
    return buildStoredWatchFromPlan(plannedWatch, existing, latestEvent);
  });
  await saveWatches(nextWatches);
  return nextWatches;
}

function trimWatchHistory(entries) {
  return (entries || []).slice(0, WATCH_HISTORY_LIMIT);
}

function buildHistoryEntry(type, checkedAt, details = {}) {
  return {
    type,
    at: checkedAt,
    ...details,
  };
}

function prependWatchHistory(watch, entries) {
  const nextEntries = Array.isArray(entries) ? entries.filter(Boolean) : [entries].filter(Boolean);
  if (!nextEntries.length) {
    return watch.history || [];
  }
  return trimWatchHistory([...nextEntries, ...(watch.history || [])]);
}

async function runWatchCycle() {
  const watches = await hydrateWatchesFromPlan();
  if (!watches.length) {
    return;
  }

  const checkedAt = nowIso();
  const dedicatedTab = await ensureDedicatedWatchTab();
  if (!dedicatedTab?.id) {
    const nextWatches = watches.map((watch) =>
      updateWatchState(watch, {
        lastCheckedAt: checkedAt,
        lastStatus: "waiting_tab",
        lastError: "Impossible d'ouvrir un onglet SNCF Connect",
        checkCount: (watch.checkCount || 0) + 1,
      })
    );
    await saveWatches(nextWatches);
    await syncWatchesToBackend(nextWatches);
    await syncWorkerHeartbeat({
      captured_at: checkedAt,
      backend_base_url: await loadBackendBaseUrl(),
      status: "error",
      watch_tab_url: null,
      watch_tab_id: null,
      watch_count: nextWatches.length,
      browser_open: true,
      sncf_tab_ready: false,
      last_error: "Impossible d'ouvrir un onglet SNCF Connect",
      session_hint: "reconnexion_sncf_possible",
    });
    return;
  }

  const nextWatches = [];
  for (const watch of watches) {
    const preparedWatch = watch;
    const response = await replayOnAnySncfTab({
      url: "https://www.sncf-connect.com/bff/api/v1/itineraries",
      method: "POST",
      headers: preparedWatch.headers,
      requestBodyPreview: preparedWatch.requestBodyPreview,
      overrides: {
        originLabel: preparedWatch.originLabel,
        destinationLabel: preparedWatch.destinationLabel,
        outwardDate: buildWatchReplayIso(preparedWatch.watchDate),
      },
    });

    const previousTravelIds = Array.isArray(preparedWatch.lastZeroTravelIds) ? preparedWatch.lastZeroTravelIds : [];
    const currentTravelIds = response?.ok ? extractZeroTravelIds(response.payload) : previousTravelIds;
    const newTravelIds = currentTravelIds.filter((travelId) => !previousTravelIds.includes(travelId));
    const removedTravelIds = previousTravelIds.filter((travelId) => !currentTravelIds.includes(travelId));
    const alertAt = response?.ok && previousTravelIds.length > 0 && newTravelIds.length > 0 ? nowIso() : null;
    const historyEntries = [];

    if (alertAt) {
      await notifyNewZeroOffers(watch, newTravelIds, response.payload);
      historyEntries.push(
        buildHistoryEntry("zero_added", checkedAt, {
          count: newTravelIds.length,
          travelIds: newTravelIds,
        })
      );
    }

    if (response?.ok && removedTravelIds.length > 0) {
      historyEntries.push(
        buildHistoryEntry("zero_removed", checkedAt, {
          count: removedTravelIds.length,
          travelIds: removedTravelIds,
        })
      );
    }

    if (response?.ok) {
      historyEntries.push(
        buildHistoryEntry("check_ok", checkedAt, {
          zeroOfferCount: currentTravelIds.length,
        })
      );
    } else {
      historyEntries.push(
        buildHistoryEntry("check_error", checkedAt, {
          error: response?.error || "Replay impossible",
        })
      );
    }

    nextWatches.push(
      updateWatchState(preparedWatch, {
        lastCheckedAt: checkedAt,
        lastSuccessAt: response?.ok ? checkedAt : preparedWatch.lastSuccessAt || null,
        lastAlertAt: alertAt || preparedWatch.lastAlertAt || null,
        lastAlertCount: alertAt ? newTravelIds.length : preparedWatch.lastAlertCount || 0,
        lastStatus: response?.ok ? "ok" : "error",
        checkCount: (preparedWatch.checkCount || 0) + 1,
        successCount: response?.ok ? (preparedWatch.successCount || 0) + 1 : preparedWatch.successCount || 0,
        lastZeroTravelIds: currentTravelIds,
        lastReplay: response?.ok ? response.payload : preparedWatch.lastReplay || null,
        lastError: response?.ok ? null : response?.error || "Replay impossible",
        history: prependWatchHistory(preparedWatch, historyEntries),
      })
    );
  }

  await saveWatches(nextWatches);
  await syncWatchesToBackend(nextWatches);
  const workerError = nextWatches.find((watch) => watch.lastStatus === "error")?.lastError || null;
  await syncWorkerHeartbeat({
    captured_at: checkedAt,
    backend_base_url: await loadBackendBaseUrl(),
    status: workerError ? "degraded" : "ok",
    watch_tab_url: dedicatedTab.url || WATCH_TAB_URL,
    watch_tab_id: dedicatedTab.id,
    watch_count: nextWatches.length,
    browser_open: true,
    sncf_tab_ready: true,
    last_error: workerError,
    session_hint: workerError ? "verifier_session_sncf" : "session_sncf_active",
  });
}

function sanitizeFilename(value) {
  return value.replace(/[^a-z0-9._-]+/gi, "-").replace(/-+/g, "-");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "sncf-probe-event") {
    loadEvents()
      .then((events) => {
        const next = [
          ...events,
          {
            ...message.payload,
            tabId: sender.tab?.id ?? null,
            tabUrl: sender.tab?.url ?? null
          }
        ].slice(-MAX_EVENTS);
        return saveEvents(next).then(() => next.length);
      })
      .then((count) => sendResponse({ ok: true, count }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-list") {
    loadEvents()
      .then((events) => sendResponse({ ok: true, events }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-clear") {
    saveEvents([])
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-export") {
    loadEvents()
      .then(async (events) => {
        const encoded = encodeURIComponent(JSON.stringify(events, null, 2));
        const url = `data:application/json;charset=utf-8,${encoded}`;
        const filename = sanitizeFilename(
          `sncf-probe-${new Date().toISOString()}.json`
        );
        await chrome.downloads.download({
          url,
          filename,
          saveAs: true
        });
        sendResponse({ ok: true, count: events.length });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-replay-result") {
    saveLastReplay(message.payload)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-last-replay") {
    loadLastReplay()
      .then((payload) => sendResponse({ ok: true, payload }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-last-itinerary") {
    loadEvents()
      .then((events) => {
        const event = latestItinerariesEvent(events);
        if (!event) {
          sendResponse({ ok: false, error: "Aucun evenement itineraries capture" });
          return;
        }
        sendResponse({ ok: true, event });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-list-watches") {
    hydrateWatchesFromPlan()
      .then((watches) => sendResponse({ ok: true, watches }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-get-backend-base-url") {
    loadBackendBaseUrl()
      .then((baseUrl) => sendResponse({ ok: true, baseUrl }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-set-backend-base-url") {
    saveBackendBaseUrl(message.payload?.baseUrl || DEFAULT_BACKEND_BASE_URL)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-hydrate-plan-now") {
    hydrateWatchesFromPlan()
      .then((watches) => sendResponse({ ok: true, watches }))
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-add-watch") {
    loadEvents()
      .then(async (events) => {
        const event = latestItinerariesEvent(events);
        if (!event) {
          sendResponse({ ok: false, error: "Aucun evenement itineraries capture" });
          return;
        }

        const payload = message.payload || {};
        const watch = {
          id: buildWatchId(payload),
          originLabel: payload.originLabel,
          destinationLabel: payload.destinationLabel,
          watchDate: payload.watchDate,
          headers: event.requestHeaders || {},
          requestBodyPreview: event.requestBodyPreview || "",
          seedCapturedAt: event.startedAt || nowIso(),
          createdAt: new Date().toISOString(),
          lastCheckedAt: null,
          lastSuccessAt: null,
          lastAlertAt: null,
          lastAlertCount: 0,
          lastStatus: "pending",
          checkCount: 0,
          successCount: 0,
          lastZeroTravelIds: [],
          lastReplay: null,
          lastError: null,
          history: [],
        };

        const watches = await loadWatches();
        const nextWatches = [...watches.filter((item) => item.id !== watch.id), watch];
        await saveWatches(nextWatches);
        await ensureWatchAlarm();
        await runWatchCycle();
        const refreshedWatches = await loadWatches();
        sendResponse({
          ok: true,
          watch: refreshedWatches.find((item) => item.id === watch.id) || watch,
        });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-remove-watch") {
    loadWatches()
      .then(async (watches) => {
        const nextWatches = watches.filter((watch) => watch.id !== message.payload?.id);
        await saveWatches(nextWatches);
        sendResponse({ ok: true, watches: nextWatches });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-replay-last-itinerary") {
    loadEvents()
      .then(async (events) => {
        const event = latestItinerariesEvent(events);
        if (!event) {
          sendResponse({ ok: false, error: "Aucun evenement itineraries capture" });
          return;
        }
        await replayOnActiveTab(buildReplayPayload(event), sendResponse);
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-replay-custom-itinerary") {
    loadEvents()
      .then(async (events) => {
        const event = latestItinerariesEvent(events);
        if (!event) {
          sendResponse({ ok: false, error: "Aucun evenement itineraries capture" });
          return;
        }
        await replayOnActiveTab(buildReplayPayload(event, message.payload || {}), sendResponse);
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  if (message?.type === "sncf-probe-run-watches-now") {
    runWatchCycle()
      .then(async () => {
        const watches = await loadWatches();
        sendResponse({ ok: true, watches });
      })
      .catch((error) => sendResponse({ ok: false, error: String(error) }));
    return true;
  }

  return false;
});

chrome.runtime.onInstalled.addListener(() => {
  ensureWatchAlarm();
  runWatchCycle().catch(() => {
    // Ignore startup polling errors.
  });
});

chrome.runtime.onStartup.addListener(() => {
  ensureWatchAlarm();
  runWatchCycle().catch(() => {
    // Ignore startup polling errors.
  });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name !== WATCH_ALARM_NAME) {
    return;
  }
  runWatchCycle().catch(() => {
    // Ignore background polling errors.
  });
});
