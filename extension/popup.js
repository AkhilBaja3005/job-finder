// popup.js - ATS Tailor Extension Controller (v2.4.0)

document.addEventListener("DOMContentLoaded", () => {
  const activeRoleTitle = document.getElementById("active-role-title");
  const activeCompanyName = document.getElementById("active-company-name");
  const scoreSection = document.getElementById("score-section");
  const scoreCircle = document.getElementById("ats-score-circle");
  const scoreSub = document.getElementById("ats-score-sub");
  const missingSkillsSection = document.getElementById("missing-skills-section");
  const missingSkillsContainer = document.getElementById("missing-skills-container");

  const previewWrapper = document.getElementById("text-preview-wrapper");
  const previewTitle = document.getElementById("preview-title");
  const previewContent = document.getElementById("text-preview-content");
  const btnCopyPreview = document.getElementById("btn-copy-preview");

  const btnTailor = document.getElementById("btn-tailor-resume");
  const btnCoverLetter = document.getElementById("btn-cover-letter");
  const btnOutreach = document.getElementById("btn-outreach");
  const btnEmailTailor = document.getElementById("btn-email-tailor");
  const userTokenInput = document.getElementById("user-token");
  const toast = document.getElementById("popup-toast");

  let currentJobInfo = null;
  let activePreviewText = "";

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.style.display = "block";
    setTimeout(() => { toast.style.display = "none"; }, 3500);
  }

  // Copy Preview Button handler
  if (btnCopyPreview) {
    btnCopyPreview.addEventListener("click", () => {
      if (activePreviewText) {
        navigator.clipboard.writeText(activePreviewText);
        btnCopyPreview.textContent = "✓ Copied!";
        setTimeout(() => { btnCopyPreview.textContent = "📋 Copy to Clipboard"; }, 2000);
      }
    });
  }

  // Load active tab details reliably via runtime message
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    const activeTab = tabs[0];

    chrome.tabs.sendMessage(activeTab.id, { action: "GET_JOB_DETAILS" }, (response) => {
      if (chrome.runtime.lastError || !response) {
        const pageTitle = activeTab.title || "";
        if (pageTitle && !pageTitle.includes("New Tab")) {
          activeRoleTitle.textContent = pageTitle.slice(0, 45);
          activeCompanyName.textContent = activeTab.url ? new URL(activeTab.url).hostname : "Active Page";
          currentJobInfo = { title: pageTitle, company: "", description: pageTitle, url: activeTab.url };
        } else {
          activeRoleTitle.textContent = "Open LinkedIn, Indeed, or Workday";
          activeCompanyName.textContent = "No job posting detected on active tab";
        }
        return;
      }

      currentJobInfo = response;
      if (currentJobInfo.title) {
        activeRoleTitle.textContent = currentJobInfo.title;
        activeCompanyName.textContent = currentJobInfo.company || "Target Company";

        chrome.storage.local.get(["userToken"], (items) => {
          const token = items ? items.userToken || "guest" : "guest";
          if (currentJobInfo.description && currentJobInfo.description.length > 30) {
            fetch("http://127.0.0.1:8000/analyze_job", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Authorization": `Bearer ${token}`
              },
              body: JSON.stringify({
                job_description: currentJobInfo.description,
                job_title: currentJobInfo.title,
                company: currentJobInfo.company,
                job_url: currentJobInfo.url
              })
            })
              .then(res => res.json())
              .then(data => {
                const score = data.match_analysis?.overall_score || 78;
                const missing = data.match_analysis?.missing_skills || [];
                scoreCircle.textContent = `${score}%`;
                scoreSub.textContent = score >= 70 ? "Strong match profile" : "Missing key keywords";
                scoreSection.style.display = "flex";

                if (missing.length > 0) {
                  missingSkillsContainer.innerHTML = missing.slice(0, 6).map(s => `<span class="skill-chip">${s}</span>`).join("");
                  missingSkillsSection.style.display = "block";
                }
              })
              .catch(() => {});
          }
        });
      } else {
        activeRoleTitle.textContent = "Open LinkedIn, Indeed, or Workday";
        activeCompanyName.textContent = "No job posting detected on active tab";
      }
    });
  });



  // Direct 1-Click Email Tailored Package to Inbox
  if (btnEmailTailor) {
    btnEmailTailor.addEventListener("click", () => {
      if (!currentJobInfo) {
        showToast("⚠️ Open a job page first!");
        return;
      }
      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        showToast("📧 Sending tailored package to email...");
        fetch("http://127.0.0.1:8000/analyze_job", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${token}`
          },
          body: JSON.stringify({
            job_url: currentJobInfo.url,
            job_title: currentJobInfo.title,
            job_description: currentJobInfo.description,
            send_email: true
          })
        })
          .then(res => res.json())
          .then(data => {
            showToast("✅ Tailored package emailed seamlessly!");
          })
          .catch(err => showToast("❌ Email dispatch failed: " + err.message));
      });
    });
  }

  // Generate & Preview Cover Letter
  btnCoverLetter.addEventListener("click", () => {
    if (!currentJobInfo) return;
    chrome.storage.local.get(["userToken"], (items) => {
      const token = items ? items.userToken || "guest" : "guest";
      showToast("⏳ Generating Cover Letter...");
      fetch("http://127.0.0.1:8000/generate_cover_letter_history", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          job_title: currentJobInfo.title,
          company: currentJobInfo.company,
          job_url: currentJobInfo.url
        })
      })
        .then(res => res.json())
        .then(data => {
          if (data.cover_letter) {
            activePreviewText = data.cover_letter;
            previewTitle.textContent = "📝 Generated Cover Letter";
            previewContent.textContent = data.cover_letter;
            previewWrapper.style.display = "block";
            showToast("📝 Cover letter generated! Preview below.");
          }
        })
        .catch(err => showToast("❌ Error: " + err.message));
    });
  });

  // Generate & Preview Recruiter Outreach
  btnOutreach.addEventListener("click", () => {
    if (!currentJobInfo) return;
    chrome.storage.local.get(["userToken"], (items) => {
      const token = items ? items.userToken || "guest" : "guest";
      showToast("⏳ Generating Recruiter Outreach...");
      fetch("http://127.0.0.1:8000/generate_outreach", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          job_title: currentJobInfo.title || "Target Role",
          company_name: currentJobInfo.company || "Target Company",
          job_description: currentJobInfo.description || currentJobInfo.title || "Target Role",
          job_url: currentJobInfo.url || ""
        })
      })
        .then(res => res.json())
        .then(data => {
          const msg = data.message?.email_body || data.message?.linkedin_message || "Outreach generated!";
          activePreviewText = msg;
          previewTitle.textContent = "✉️ Generated Outreach Message";
          previewContent.textContent = msg;
          previewWrapper.style.display = "block";
          showToast("✉️ Outreach generated! Preview below.");
        })
        .catch(err => showToast("❌ Error: " + err.message));
    });
  });

  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");

  // Fetch user profile for confirmation
  function fetchUserInfo(syncKey) {
    if (!syncKey || !syncKey.trim()) {
      if (userInfoCard) userInfoCard.style.display = "none";
      return;
    }
    const cleanKey = syncKey.trim();
    fetch("http://127.0.0.1:8000/user/me", {
      headers: { "Authorization": `Bearer ${cleanKey}` }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data && (data.email || data.id)) {
          const email = data.email || "akhilbaja.work@gmail.com";
          const candidateName = data.resume_name || (data.email ? data.email.split("@")[0] : "Akhilbaja.work");
          if (userNameDisplay) userNameDisplay.textContent = `✓ Synced User: ${candidateName}`;
          if (userEmailDisplay) userEmailDisplay.textContent = `📧 Destination: ${email}`;
          if (userInfoCard) userInfoCard.style.display = "block";
        } else {
          if (userInfoCard) userInfoCard.style.display = "none";
        }
      })
      .catch(() => {
        if (userInfoCard) userInfoCard.style.display = "none";
      });
  }

  // Sync Key state binding
  chrome.storage.local.get(["userToken"], (items) => {
    if (items.userToken) {
      userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
  });

  userTokenInput.addEventListener("input", (e) => {
    const key = e.target.value.trim();
    chrome.storage.local.set({ userToken: key });
    fetchUserInfo(key);
  });
});
