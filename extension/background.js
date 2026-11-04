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

  // Live Toolbar ATS Match Badge
  if (request.action === "SET_BADGE") {
    const tabId = sender.tab ? sender.tab.id : request.tabId;
    const score = request.score;
    if (score !== undefined && score !== null && tabId) {
      const text = `${Math.round(score)}%`;
      chrome.action.setBadgeText({ text, tabId });
      let color = "#64748B"; // default gray
      if (score >= 80) color = "#10B981"; // green
      else if (score >= 65) color = "#F59E0B"; // amber
      else if (score > 0) color = "#EF4444"; // red
      chrome.action.setBadgeBackgroundColor({ color, tabId });
    } else if (tabId) {
      chrome.action.setBadgeText({ text: "", tabId });
    }
    sendResponse({ success: true });
    return true;
  }

  // UK Visa Sponsor Lookup & Refresh Actions
  if (request.action === "CHECK_SPONSOR") {
    checkCompanySponsorLocal(request.company).then((res) => sendResponse(res));
    return true;
  }

  if (request.action === "REFRESH_SPONSORS") {
    fetchLatestGovUkSponsorRegister(true).then((res) => sendResponse(res));
    return true;
  }

  if (request.action === "GET_SPONSOR_STATS") {
    getSponsorRegisterStats().then((res) => sendResponse(res));
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

// Handle 1-Click Sync Key initialization & Live Resume Sync from web app
chrome.runtime.onMessageExternal.addListener((request, sender, sendResponse) => {
  if (request.action === "SYNC_USER_KEY" && request.syncKey) {
    chrome.storage.local.set({ userToken: request.syncKey }, () => {
      sendResponse({ success: true, syncedKey: request.syncKey });
    });
    return true;
  }

  if (request.action === "SYNC_RESUME_DATA" && request.resumeData) {
    chrome.storage.local.set({
      resumeData: request.resumeData,
      rawResumeText: request.rawResumeText || "",
      lastSyncedAt: new Date().toISOString()
    }, () => {
      // Notify active popup or tabs of the live update
      chrome.runtime.sendMessage({ action: "PROFILE_UPDATED", resumeData: request.resumeData }).catch(() => {});
      sendResponse({ success: true, timestamp: Date.now() });
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
// Poll once every 15 minutes (15 * 60 * 1000 ms) in development
setInterval(checkHotReload, 15 * 60 * 1000);
checkHotReload();

// ── UK Visa Sponsor Checker Background Engine ─────────────────────────────
const SUFFIX_REGEX = /\b(ltd|limited|plc|llp|gmbh|inc|incorporated|corp|corporation|group|holdings|services|solutions|uk|international|technologies|technology|consulting)\b/gi;

function normalizeCompanyNameLocal(name) {
  if (!name) return "";
  let s = String(name).toLowerCase();
  s = s.replace(/['’`]/g, "");
  s = s.replace(/&/g, " and ");
  s = s.replace(/[^a-z0-9\s]/g, " ");
  s = s.replace(SUFFIX_REGEX, " ");
  return s.replace(/\s+/g, " ").trim();
}

async function getSponsorRegisterStats() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["ukSponsorNames", "ukSponsorLastSync", "ukSponsorCount"], (items) => {
      const names = items.ukSponsorNames || [];
      resolve({
        total_sponsors: items.ukSponsorCount || names.length,
        last_sync: items.ukSponsorLastSync || "Never"
      });
    });
  });
}

async function checkCompanySponsorLocal(company) {
  if (!company || !company.trim()) {
    return { is_sponsor: false, badge: "✗ Not on sponsor", badge_color: "red" };
  }

  const norm = normalizeCompanyNameLocal(company);
  if (!norm || norm.length < 2) {
    return { is_sponsor: false, badge: "✗ Not on sponsor", badge_color: "red" };
  }

  return new Promise((resolve) => {
    chrome.storage.local.get(["ukSponsorNames"], (items) => {
      const names = items.ukSponsorNames || [];
      if (!names.length) {
        // Fallback: check via backend API if local storage empty
        fetch(`${BACKEND_URL}/api/sponsor/check?company=${encodeURIComponent(company)}`)
          .then((r) => r.json())
          .then((data) => resolve(data))
          .catch(() => resolve({ is_sponsor: false, badge: "✗ Not on sponsor", badge_color: "red" }));
        return;
      }

      // 1. Direct Set check
      const nameSet = new Set(names);
      if (nameSet.has(norm)) {
        resolve({
          is_sponsor: true,
          badge: "✓ UK Visa Sponsor",
          badge_color: "green",
          matched_name: norm
        });
        return;
      }

      // 2. Prefix check (brand name matches leading token of official name)
      const prefix = `${norm} `;
      const foundPrefix = names.find((n) => n.startsWith(prefix));
      if (foundPrefix) {
        resolve({
          is_sponsor: true,
          badge: "✓ UK Visa Sponsor",
          badge_color: "green",
          matched_name: foundPrefix
        });
        return;
      }

      // 3. Reverse check (query starts with official brand, e.g. "Amazon Web Services")
      if (norm.includes(" ")) {
        const foundSub = names.find((n) => norm.startsWith(`${n} `) && n.length >= 4);
        if (foundSub) {
          resolve({
            is_sponsor: true,
            badge: "✓ UK Visa Sponsor",
            badge_color: "green",
            matched_name: foundSub
          });
          return;
        }
      }

      resolve({
        is_sponsor: false,
        badge: "✗ Not on sponsor",
        badge_color: "red",
        company_name: company,
        notice: {
          title: "Company Could Not Be Found in Sponsor Database",
          description: `${company} is not currently registered as a visa sponsor with the UK government.`,
          advice: "This doesn't necessarily mean they can't sponsor - they may be able to apply for a sponsor license. Consider reaching out directly to ask about their sponsorship policy or future plans."
        }
      });
    });
  });
}

async function fetchLatestGovUkSponsorRegister(force = false) {
  try {
    const stats = await getSponsorRegisterStats();
    if (!force && stats.total_sponsors > 10000) {
      return { status: "cached", count: stats.total_sponsors };
    }

    console.log("[UKSponsor] Fetching latest Gov.UK publication page...");
    // 1. First try fetching pre-computed register from backend to save extension bandwidth
    try {
      const backendRes = await fetch(`${BACKEND_URL}/api/sponsor/check?company=Google`);
      if (backendRes.ok) {
        // Trigger backend sync & load stats
        fetch(`${BACKEND_URL}/api/sponsor/sync`, { method: "POST" }).catch(() => {});
      }
    } catch (_) {}

    // 2. Direct download from Gov.UK publication portal
    const pubUrl = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers";
    const pubResp = await fetch(pubUrl);
    const pubHtml = await pubResp.text();

    const csvMatch = pubHtml.match(/https?:\/\/assets\.publishing\.service\.gov\.uk\/media\/[^\s"'<>]+\.csv/i);
    const csvUrl = csvMatch ? csvMatch[0] : null;

    if (!csvUrl) {
      console.warn("[UKSponsor] Could not locate CSV link on Gov.UK");
      return { status: "error", message: "CSV URL not found" };
    }

    console.log("[UKSponsor] Downloading latest CSV:", csvUrl);
    const csvResp = await fetch(csvUrl);
    const csvText = await csvResp.text();

    const lines = csvText.split(/\r?\n/);
    const normalizedNames = new Set();

    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (!line) continue;
      // First column is Organisation Name
      let compName = "";
      if (line.startsWith('"')) {
        const nextQuote = line.indexOf('"', 1);
        compName = nextQuote !== -1 ? line.substring(1, nextQuote) : "";
      } else {
        compName = line.split(",")[0] || "";
      }
      const norm = normalizeCompanyNameLocal(compName);
      if (norm && norm.length >= 2) {
        normalizedNames.add(norm);
      }
    }

    const namesArray = Array.from(normalizedNames).sort();
    const nowStr = new Date().toISOString().replace("T", " ").substring(0, 19) + " UTC";

    await chrome.storage.local.set({
      ukSponsorNames: namesArray,
      ukSponsorCount: namesArray.length,
      ukSponsorLastSync: nowStr
    });

    console.log(`[UKSponsor] Successfully loaded & indexed ${namesArray.length} sponsors!`);
    return { status: "success", count: namesArray.length, last_sync: nowStr };
  } catch (err) {
    console.error("[UKSponsor] Error refreshing register:", err);
    return { status: "error", message: err.message };
  }
}

// Set up daily background alarm to refresh the Home Office register
if (chrome.alarms) {
  chrome.alarms.create("REFRESH_UK_SPONSORS_ALARM", {
    periodInMinutes: 1440 // 24 hours
  });

  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "REFRESH_UK_SPONSORS_ALARM") {
      console.log("[UKSponsor] Daily alarm triggered: refreshing register...");
      fetchLatestGovUkSponsorRegister(true);
    }
  });
}

// Initial check on worker boot
setTimeout(() => {
  chrome.storage.local.get(["ukSponsorCount"], (res) => {
    if (!res.ukSponsorCount || res.ukSponsorCount === 0) {
      fetchLatestGovUkSponsorRegister(false);
    }
  });
}, 2000);

