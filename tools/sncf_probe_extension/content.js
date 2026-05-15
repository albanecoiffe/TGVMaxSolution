
function hasExtensionContext() {
  try {
    return Boolean(chrome?.runtime?.id);
  } catch (_error) {
    return false;
  }
}

function safeSendMessage(message) {
  if (!hasExtensionContext()) {
    return;
  }

  try {
    chrome.runtime.sendMessage(message);
  } catch (_error) {
    // The old content script can outlive an extension reload.
    // In that case the page must be reloaded to attach the fresh script.
  }
}

(function injectProbe() {
  try {
    if (!hasExtensionContext()) {
      return;
    }

    const script = document.createElement("script");
    script.src = chrome.runtime.getURL("injected.js");
    script.async = false;
    (document.documentElement || document.head).appendChild(script);
    script.remove();
  } catch (_error) {
    // Ignore invalidated extension contexts on stale tabs.
  }
})();

window.addEventListener("message", (event) => {
  if (event.source !== window) {
    return;
  }

  const data = event.data;
  if (!data || data.source !== "sncf-probe" || !data.payload) {
    return;
  }

  if (data.payloadType === "event") {
    safeSendMessage({
      type: "sncf-probe-event",
      payload: data.payload
    });
    return;
  }

  if (data.payloadType === "replay-result") {
    safeSendMessage({
      type: "sncf-probe-replay-result",
      payload: data.payload
    });
  }
});


if (hasExtensionContext()) {
  try {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (message?.type !== "sncf-probe-replay-in-page") {
        return false;
      }

      const listener = (event) => {
        if (event.source !== window) {
          return;
        }
        const data = event.data;
        if (!data || data.source !== "sncf-probe" || data.payloadType !== "replay-result") {
          return;
        }
        window.removeEventListener("message", listener);
        sendResponse({ ok: true, payload: data.payload });
      };

      window.addEventListener("message", listener);
      window.postMessage(
        {
          source: "sncf-probe-control",
          command: "replay-itinerary",
          payload: message.payload
        },
        "*"
      );
      return true;
    });
  } catch (_error) {
    // Ignore invalidated extension contexts on stale tabs.
  }
}
