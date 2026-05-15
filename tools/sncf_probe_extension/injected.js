(function installSncfProbe() {
  if (window.__sncfProbeInstalled) {
    return;
  }
  window.__sncfProbeInstalled = true;

  const BODY_LIMIT = 20_000;
  const KEYWORD_RE = /(api|graphql|itinerary|proposal|pricing|price|fare|max|alert|booking|shop|search)/i;
  const AUTOCOMPLETE_URL = "https://www.sncf-connect.com/bff/api/v1/autocomplete";

  function truncate(value) {
    if (typeof value !== "string") {
      return value;
    }
    if (value.length <= BODY_LIMIT) {
      return value;
    }
    return `${value.slice(0, BODY_LIMIT)}\n...[truncated ${value.length - BODY_LIMIT} chars]`;
  }

  function shouldCapture(url) {
    if (!url || typeof url !== "string") {
      return false;
    }
    try {
      const parsed = new URL(url, window.location.href);
      if (!/sncf-connect\.com$/i.test(parsed.hostname)) {
        return false;
      }
      return KEYWORD_RE.test(parsed.href);
    } catch {
      return KEYWORD_RE.test(url);
    }
  }

  function postPayload(payload) {
    window.postMessage(
      {
        source: "sncf-probe",
        payloadType: "event",
        payload
      },
      "*"
    );
  }

  function postReplayResult(payload) {
    window.postMessage(
      {
        source: "sncf-probe",
        payloadType: "replay-result",
        payload
      },
      "*"
    );
  }

  function normalizeLabel(value) {
    return String(value || "")
      .trim()
      .toLowerCase();
  }

  function summarizeReplayResponse(requestBody, responseBody) {
    const proposalsBlock = responseBody?.longDistance?.proposals || {};
    const bestPrices = Array.isArray(proposalsBlock.bestPrices) ? proposalsBlock.bestPrices : [];
    const bestPriceLabels = bestPrices.map((item) => ({
      label: item?.label || null,
      priceLabel: item?.priceLabel || null,
      bestPriceDateTime: item?.bestPriceDateTime || null,
    }));
    const zeroBestPrices = bestPriceLabels.filter((item) => item.priceLabel === "0 €");

    const zeroOffers = [];
    const proposals = Array.isArray(proposalsBlock.proposals) ? proposalsBlock.proposals : [];
    for (const proposal of proposals) {
      for (const groupName of ["firstComfortClassOffers", "secondComfortClassOffers"]) {
        const offers = proposal?.[groupName]?.offers || [];
        for (const offer of offers) {
          if (offer?.priceLabel !== "0 €") {
            continue;
          }
          const fareNames = [];
          for (const travelerFare of offer?.travelersFares || []) {
            for (const segmentFare of travelerFare?.segmentFares || []) {
              if (segmentFare?.fareName && !fareNames.includes(segmentFare.fareName)) {
                fareNames.push(segmentFare.fareName);
              }
            }
          }
          zeroOffers.push({
            travelId: proposal?.travelId || null,
            departureTime: proposal?.departure?.timeLabel || null,
            arrivalTime: proposal?.arrival?.timeLabel || null,
            origin: proposal?.departure?.originStationLabel || null,
            destination: proposal?.arrival?.destinationStationLabel || null,
            offerTitle: offer?.header?.title || null,
            offerSubtitle: offer?.header?.subtitle || null,
            priceLabel: offer?.priceLabel || null,
            fareNames,
          });
        }
      }
    }

    return {
      ok: true,
      request: {
        origin: requestBody?.mainJourney?.origin?.label || null,
        destination: requestBody?.mainJourney?.destination?.label || null,
        outwardDate: requestBody?.schedule?.outward?.date || null,
        branch: requestBody?.branch || null,
      },
      response: {
        bestPriceLabels,
        zeroBestPriceDays: zeroBestPrices.length,
        zeroOfferCount: zeroOffers.length,
        zeroOffers,
      },
      capturedAt: new Date().toISOString(),
    };
  }

  async function resolveStation(headers, searchTerm) {
    const response = await window.fetch(AUTOCOMPLETE_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({
        searchTerm,
        keepStationsOnly: false,
        returnsSuggestions: false,
      }),
      credentials: "include",
    });
    const text = await response.text();
    let parsedBody = null;
    try {
      parsedBody = JSON.parse(text);
    } catch {
      parsedBody = null;
    }
    if (!response.ok) {
      throw new Error(`Autocomplete ${response.status}: ${truncate(text)}`);
    }

    const transportPlaces = parsedBody?.places?.transportPlaces || [];
    const station =
      transportPlaces.find((item) => item?.type?.placeType === "STATION") ||
      transportPlaces.find((item) =>
        Array.isArray(item?.codes) && item.codes.some((code) => code?.type === "RESARAIL")
      );
    if (!station) {
      throw new Error(`Aucune gare resolue pour ${searchTerm}`);
    }

    return {
      id: station.id,
      label: station.label,
      geolocation: false,
      isEditable: true,
      codes: station.codes || [],
    };
  }

  async function serializeResponseBody(response) {
    const contentType = response.headers.get("content-type") || "";
    if (
      !contentType.includes("application/json") &&
      !contentType.includes("text/") &&
      !contentType.includes("application/problem+json")
    ) {
      return {
        bodyPreview: `[skipped content-type: ${contentType || "unknown"}]`
      };
    }

    try {
      const text = await response.text();
      return {
        bodyPreview: truncate(text)
      };
    } catch (error) {
      return {
        bodyPreview: `[unreadable body: ${String(error)}]`
      };
    }
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function patchedFetch(input, init) {
    const startedAt = Date.now();
    const requestUrl =
      typeof input === "string" ? input : input?.url || String(input);

    try {
      const response = await originalFetch(input, init);
      if (shouldCapture(requestUrl)) {
        const cloned = response.clone();
        const body = await serializeResponseBody(cloned);
        postPayload({
          transport: "fetch",
          url: cloned.url || requestUrl,
          method: init?.method || (typeof input !== "string" ? input?.method : null) || "GET",
          status: cloned.status,
          ok: cloned.ok,
          startedAt: new Date(startedAt).toISOString(),
          durationMs: Date.now() - startedAt,
          requestBodyPreview: truncate(typeof init?.body === "string" ? init.body : null),
          responseHeaders: Object.fromEntries(cloned.headers.entries()),
          ...body
        });
      }
      return response;
    } catch (error) {
      if (shouldCapture(requestUrl)) {
        postPayload({
          transport: "fetch",
          url: requestUrl,
          method: init?.method || "GET",
          status: null,
          ok: false,
          startedAt: new Date(startedAt).toISOString(),
          durationMs: Date.now() - startedAt,
          requestBodyPreview: truncate(typeof init?.body === "string" ? init.body : null),
          error: String(error)
        });
      }
      throw error;
    }
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;

  XMLHttpRequest.prototype.open = function patchedOpen(method, url, ...rest) {
    this.__sncfProbe = {
      method,
      url,
      startedAt: Date.now(),
      requestHeaders: {}
    };
    return originalOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.setRequestHeader = function patchedSetRequestHeader(name, value) {
    if (this.__sncfProbe) {
      this.__sncfProbe.requestHeaders[name] = value;
    }
    return originalSetRequestHeader.call(this, name, value);
  };

  XMLHttpRequest.prototype.send = function patchedSend(body) {
    const meta = this.__sncfProbe;
    if (meta) {
      meta.requestBodyPreview = truncate(typeof body === "string" ? body : null);
    }

    this.addEventListener("loadend", () => {
      if (!meta || !shouldCapture(meta.url)) {
        return;
      }

      let responseHeaders = {};
      try {
        responseHeaders = Object.fromEntries(
          this.getAllResponseHeaders()
            .trim()
            .split(/[\r\n]+/)
            .filter(Boolean)
            .map((line) => {
              const index = line.indexOf(":");
              const key = line.slice(0, index).trim();
              const value = line.slice(index + 1).trim();
              return [key, value];
            })
        );
      } catch {
        responseHeaders = {};
      }

      postPayload({
        transport: "xhr",
        url: this.responseURL || meta.url,
        method: meta.method || "GET",
        status: this.status,
        ok: this.status >= 200 && this.status < 400,
        startedAt: new Date(meta.startedAt).toISOString(),
        durationMs: Date.now() - meta.startedAt,
        requestHeaders: meta.requestHeaders,
        requestBodyPreview: meta.requestBodyPreview || null,
        responseHeaders,
        bodyPreview: truncate(typeof this.responseText === "string" ? this.responseText : null)
      });
    });

    return originalSend.call(this, body);
  };

  window.addEventListener("message", async (event) => {
    if (event.source !== window) {
      return;
    }
    const data = event.data;
    if (!data || data.source !== "sncf-probe-control" || data.command !== "replay-itinerary") {
      return;
    }

    const payload = data.payload || {};
    let requestBody;
    try {
      requestBody = JSON.parse(payload.requestBodyPreview || "{}");
    } catch (error) {
      postReplayResult({
        ok: false,
        error: `Impossible de parser le body capture: ${String(error)}`,
      });
      return;
    }

    try {
      const headers = { ...(payload.headers || {}) };
      const overrides = payload.overrides || {};
      const currentOriginLabel = requestBody?.mainJourney?.origin?.label || "";
      const currentDestinationLabel = requestBody?.mainJourney?.destination?.label || "";
      if (overrides.originLabel && normalizeLabel(overrides.originLabel) !== normalizeLabel(currentOriginLabel)) {
        requestBody.mainJourney = requestBody.mainJourney || {};
        requestBody.mainJourney.origin = await resolveStation(headers, overrides.originLabel);
      }
      if (
        overrides.destinationLabel &&
        normalizeLabel(overrides.destinationLabel) !== normalizeLabel(currentDestinationLabel)
      ) {
        requestBody.mainJourney = requestBody.mainJourney || {};
        requestBody.mainJourney.destination = await resolveStation(headers, overrides.destinationLabel);
      }
      if (overrides.outwardDate) {
        requestBody.schedule = requestBody.schedule || {};
        requestBody.schedule.outward = requestBody.schedule.outward || {};
        requestBody.schedule.outward.date = overrides.outwardDate;
      }

      const response = await window.fetch(payload.url, {
        method: payload.method || "POST",
        headers,
        body: JSON.stringify(requestBody),
        credentials: "include",
      });
      const text = await response.text();
      let parsedBody = null;
      try {
        parsedBody = JSON.parse(text);
      } catch {
        parsedBody = null;
      }

      if (!response.ok) {
        postReplayResult({
          ok: false,
          status: response.status,
          bodyPreview: truncate(text),
          capturedAt: new Date().toISOString(),
        });
        return;
      }

      postReplayResult(summarizeReplayResponse(requestBody, parsedBody));
    } catch (error) {
      postReplayResult({
        ok: false,
        error: String(error),
        capturedAt: new Date().toISOString(),
      });
    }
  });
})();
