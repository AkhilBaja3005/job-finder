const DEFAULT_BACKEND_URL = "https://www.job-finder.space";
let BACKEND_URL = DEFAULT_BACKEND_URL;

chrome.storage.local.get(["backendUrl"], (items) => {
  if (items && items.backendUrl && items.backendUrl.trim()) {
    BACKEND_URL = items.backendUrl.trim().replace(/\/+$/, "");
  }
});

// Handle messages from popup or content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "GET_BACKEND_HEALTH") {
    fetch(`${BACKEND_URL}/healthz`)
      .then((res) => res.json())
      .then((data) => sendResponse({ success: true, data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (request.action === "PARSE_PAGE_QUESTION") {
    chrome.storage.local.get(["userToken", "resumeData", "customApiKey"], (items) => {
      fetch(`${BACKEND_URL}/user/solve_field`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${items.userToken || "guest"}`
        },
        body: JSON.stringify({
          question: request.question,
          context: request.context,
          resume_data: items.resumeData || {},
          api_key: items.customApiKey || null
        })
      })
        .then((res) => res.json())
        .then((data) => sendResponse({ success: true, answer: data.answer }))
        .catch((err) => sendResponse({ success: false, error: err.message }));
    });
    return true;
  }

  // Relay logs or state updates from content.js to popup or storage
  if (request.type === "LOG_EVENT") {
    chrome.storage.local.get(["appLogs"], (items) => {
      const logs = items.appLogs || [];
      logs.push(`[${new Date().toLocaleTimeString()}] ${request.message}`);
      if (logs.length > 50) logs.shift();
      chrome.storage.local.set({ appLogs: logs });
    });
  }
});

// Enable Chrome native Side Panel on extension action click
if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch((err) => {
    console.log("[SidePanel] Panel behavior notice:", err);
  });
}

// Handle 1-Click Sync Key initialization from web app
chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  if (request.action === "SYNC_USER_KEY" && request.syncKey) {
    chrome.storage.local.set({ userToken: request.syncKey }, () => {
      sendResponse({ success: true, syncedKey: request.syncKey });
    });
    return true;
  }
});

// ── Development Auto-Reload / Hot-Reload Watcher ──────────────────────────
let lastExtHash = null;
async function checkHotReload() {
  try {
    const res = await fetch("http://127.0.0.1:8000/extension_version_hash");
    if (res.ok) {
      const data = await res.json();
      if (lastExtHash && data.hash && data.hash !== lastExtHash) {
        console.log("[AutoReload] Extension file changes detected on disk! Auto-reloading extension...");
        chrome.runtime.reload();
        return;
      }
      lastExtHash = data.hash;
    }
  } catch (e) {
    // Backend offline or running in pure remote mode, ignore silently
  }
}
setInterval(checkHotReload, 2000);
checkHotReload();
