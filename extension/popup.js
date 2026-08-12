// popup.js - Extension popup controller

document.addEventListener("DOMContentLoaded", () => {
  const statusBadge = document.getElementById("backend-status");
  const btnFill = document.getElementById("btn-autofill");
  const userTokenInput = document.getElementById("user-token");
  const eeoWorkAuth = document.getElementById("eeo-work-auth");
  const eeoSponsorship = document.getElementById("eeo-sponsorship");
  const eeoGender = document.getElementById("eeo-gender");
  const eeoDisability = document.getElementById("eeo-disability");
  const btnSaveProfile = document.getElementById("btn-save-profile");

  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");

  // Function to fetch user info from backend using Sync Key
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

  // Load saved profile data from chrome.storage
  chrome.storage.local.get(["userToken", "eeoProfile"], (items) => {
    if (items.userToken) {
      userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
    const eeo = items.eeoProfile || {};
    if (eeo.workAuth) eeoWorkAuth.value = eeo.workAuth;
    if (eeo.sponsorship) eeoSponsorship.value = eeo.sponsorship;
    if (eeo.gender) eeoGender.value = eeo.gender;
    if (eeo.disability) eeoDisability.value = eeo.disability;
  });

  // Check Backend Connection Health
  chrome.runtime.sendMessage({ action: "GET_BACKEND_HEALTH" }, (response) => {
    if (response && response.success) {
      statusBadge.textContent = "Online 🟢";
      statusBadge.style.color = "#34d399";
    } else {
      statusBadge.textContent = "Offline 🔴";
      statusBadge.style.color = "#f87171";
      statusBadge.style.background = "rgba(248, 113, 113, 0.15)";
      statusBadge.style.borderColor = "rgba(248, 113, 113, 0.3)";
    }
  });

  // Fetch user info & save when user presses Enter key on Sync Key input
  userTokenInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const val = userTokenInput.value.trim().toUpperCase();
      userTokenInput.value = val;
      fetchUserInfo(val);
      btnSaveProfile.click();
    }
  });

  // Fetch user info dynamically as key is typed
  userTokenInput.addEventListener("input", (e) => {
    fetchUserInfo(e.target.value);
  });

  // Save User Profile
  btnSaveProfile.addEventListener("click", () => {
    const userToken = userTokenInput.value.strip ? userTokenInput.value.strip() : userTokenInput.value.trim();
    const eeoProfile = {
      workAuth: eeoWorkAuth.value,
      sponsorship: eeoSponsorship.value,
      gender: eeoGender.value,
      disability: eeoDisability.value
    };

    chrome.storage.local.set({ userToken, eeoProfile }, () => {
      btnSaveProfile.textContent = "✅ Saved!";
      setTimeout(() => {
        btnSaveProfile.textContent = "💾 Save User Profile";
      }, 1500);
    });
  });

  // Trigger auto-fill on active tab
  btnFill.addEventListener("click", () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]) {
        chrome.tabs.sendMessage(tabs[0].id, { action: "TRIGGER_AUTOFILL" }, (response) => {
          if (chrome.runtime.lastError) {
            console.log("AutoFill notice: Content script not active on this page or page reloaded.", chrome.runtime.lastError.message);
          }
        });
      }
    });
  });
});
