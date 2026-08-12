// popup.js - Extension popup controller

document.addEventListener("DOMContentLoaded", () => {
  const statusBadge = document.getElementById("backend-status");
  const btnFill = document.getElementById("btn-autofill");
  const btnToggleAuto = document.getElementById("btn-toggle-auto");
  const autoStatusText = document.getElementById("auto-status-text");

  const statApplied = document.getElementById("stat-applied");
  const statSkipped = document.getElementById("stat-skipped");
  const logWindow = document.getElementById("log-window");

  const userTokenInput = document.getElementById("user-token");
  const cfgMaxYears = document.getElementById("cfg-max-years");
  const cfgBlacklist = document.getElementById("cfg-blacklist");

  const eeoWorkAuth = document.getElementById("eeo-work-auth");
  const eeoSponsorship = document.getElementById("eeo-sponsorship");
  const btnSaveProfile = document.getElementById("btn-save-profile");

  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");

  let isAutoRunning = false;

  // Fetch user details from backend using Sync Key
  function fetchUserInfo(syncKey) {
    if (!syncKey || syncKey.trim().length !== 6) {
      if (userInfoCard) userInfoCard.style.display = "none";
      return;
    }
    const cleanKey = syncKey.trim().toUpperCase();
    fetch("http://127.0.0.1:8000/user/me", {
      headers: { "Authorization": `Bearer ${cleanKey}` }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && (data.email || data.id)) {
          const email = data.email || 'User Account';
          const name = email.split('@')[0];
          if (userNameDisplay) userNameDisplay.textContent = `👤 Synced: ${name.charAt(0).toUpperCase() + name.slice(1)}`;
          if (userEmailDisplay) userEmailDisplay.textContent = `📧 ${email}`;
          if (userInfoCard) userInfoCard.style.display = "block";
        } else {
          if (userInfoCard) userInfoCard.style.display = "none";
        }
      })
      .catch(() => {
        if (userInfoCard) userInfoCard.style.display = "none";
      });
  }

  // Render logs in logWindow
  function renderLogs(logs) {
    if (!logWindow || !logs) return;
    logWindow.innerHTML = logs.map(l => `<div>${l}</div>`).join('');
    logWindow.scrollTop = logWindow.scrollHeight;
  }

  // Load saved preferences & state from storage
  chrome.storage.local.get([
    "userToken", "eeoProfile", "maxYears", "blacklistKeywords",
    "isAutoRunning", "appliedCount", "skippedCount", "appLogs"
  ], (items) => {
    if (items.userToken) {
      userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
    const eeo = items.eeoProfile || {};
    if (eeo.workAuth) eeoWorkAuth.value = eeo.workAuth;
    if (eeo.sponsorship) eeoSponsorship.value = eeo.sponsorship;

    if (items.maxYears) cfgMaxYears.value = items.maxYears;
    if (items.blacklistKeywords) cfgBlacklist.value = items.blacklistKeywords;

    statApplied.textContent = items.appliedCount || 0;
    statSkipped.textContent = items.skippedCount || 0;

    isAutoRunning = !!items.isAutoRunning;
    updateAutoUI(isAutoRunning);

    if (items.appLogs) renderLogs(items.appLogs);
  });

  // Listen for background/content log updates
  chrome.storage.onChanged.addListener((changes) => {
    if (changes.appliedCount) statApplied.textContent = changes.appliedCount.newValue || 0;
    if (changes.skippedCount) statSkipped.textContent = changes.skippedCount.newValue || 0;
    if (changes.appLogs) renderLogs(changes.appLogs.newValue || []);
    if (changes.isAutoRunning) {
      isAutoRunning = !!changes.isAutoRunning.newValue;
      updateAutoUI(isAutoRunning);
    }
  });

  function updateAutoUI(running) {
    if (running) {
      btnToggleAuto.textContent = "⏸️ Stop Batch Auto-Apply";
      btnToggleAuto.className = "btn btn-stop";
      autoStatusText.textContent = "Running 🟢";
      autoStatusText.style.color = "#34d399";
    } else {
      btnToggleAuto.textContent = "▶️ Start Batch Auto-Apply";
      btnToggleAuto.className = "btn btn-auto";
      autoStatusText.textContent = "Idle";
      autoStatusText.style.color = "#94a3b8";
    }
  }

  // Check Backend Connection Health
  chrome.runtime.sendMessage({ action: "GET_BACKEND_HEALTH" }, (response) => {
    if (response && response.success) {
      statusBadge.textContent = "Online 🟢";
      statusBadge.style.color = "#34d399";
    } else {
      statusBadge.textContent = "Offline 🔴";
      statusBadge.style.color = "#f87171";
    }
  });

  // Sync key input listeners
  userTokenInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const val = userTokenInput.value.trim().toUpperCase();
      userTokenInput.value = val;
      fetchUserInfo(val);
      btnSaveProfile.click();
    }
  });

  userTokenInput.addEventListener("input", (e) => {
    fetchUserInfo(e.target.value);
  });

  // Save profile & filters
  btnSaveProfile.addEventListener("click", () => {
    const userToken = userTokenInput.value.trim();
    const eeoProfile = {
      workAuth: eeoWorkAuth.value,
      sponsorship: eeoSponsorship.value
    };
    const maxYears = cfgMaxYears.value;
    const blacklistKeywords = cfgBlacklist.value;

    chrome.storage.local.set({ userToken, eeoProfile, maxYears, blacklistKeywords }, () => {
      btnSaveProfile.textContent = "✅ Saved!";
      setTimeout(() => {
        btnSaveProfile.textContent = "💾 Save Preferences";
      }, 1500);
    });
  });

  // Toggle Batch Auto-Apply Loop
  btnToggleAuto.addEventListener("click", () => {
    isAutoRunning = !isAutoRunning;
    chrome.storage.local.set({ isAutoRunning }, () => {
      updateAutoUI(isAutoRunning);
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (tabs[0]) {
          chrome.tabs.sendMessage(tabs[0].id, {
            action: "TOGGLE_BATCH_AUTO",
            state: isAutoRunning
          });
        }
      });
    });
  });

  // Trigger single-page active auto-fill
  btnFill.addEventListener("click", () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { action: "TRIGGER_AUTOFILL" });
      }
    });
  });
});
