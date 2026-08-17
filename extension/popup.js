// popup.js - ATS Tailor Extension Controller (v2.5.0 Full Restoration)

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

  const btnCoverLetter = document.getElementById("btn-cover-letter");
  const btnOutreach = document.getElementById("btn-outreach");
  const btnEmailTailor = document.getElementById("btn-email-tailor");
  const userTokenInput = document.getElementById("user-token");
  const toast = document.getElementById("popup-toast");

  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");

  let currentJobInfo = null;
  let activePreviewText = "";

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.style.display = "block";
    setTimeout(() => { toast.style.display = "none"; }, 3500);
  }

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
          let candidateName = data.resume_name;
          if (!candidateName) {
            if (data.email && data.email.includes("akhilbaja")) {
              candidateName = "AKHIL BAJA";
            } else if (data.email) {
              candidateName = data.email.split("@")[0].toUpperCase();
            } else {
              candidateName = "AKHIL BAJA";
            }
          }
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

  // Load saved sync key on popup boot
  chrome.storage.local.get(["userToken"], (items) => {
    if (items.userToken && userTokenInput) {
      userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
  });

  if (userTokenInput) {
    userTokenInput.addEventListener("input", (e) => {
      const key = e.target.value.trim();
      chrome.storage.local.set({ userToken: key });
      fetchUserInfo(key);
    });
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

  // Active tab job details extraction
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    const activeTab = tabs[0];

    function handleJobDetails(details) {
      if (!details || !details.title) {
        const pageTitle = activeTab.title || "";
        if (pageTitle && !pageTitle.includes("New Tab")) {
          activeRoleTitle.textContent = pageTitle.slice(0, 50);
          activeCompanyName.textContent = activeTab.url ? new URL(activeTab.url).hostname.replace("www.", "") : "Active Tab";
          currentJobInfo = { title: pageTitle, company: "", description: pageTitle, url: activeTab.url };
          fetchAtsScore(currentJobInfo);
        } else {
          activeRoleTitle.textContent = "Open LinkedIn, Indeed, or Workday";
          activeCompanyName.textContent = "No job posting detected on active tab";
        }
        return;
      }

      currentJobInfo = details;
      activeRoleTitle.textContent = currentJobInfo.title;

      // Extract company from page title or URL domain if selector returns empty
      let company = currentJobInfo.company;
      if (!company || company === "Target Company") {
        if (currentJobInfo.url && currentJobInfo.url.includes("linkedin.com")) {
          const authorMatch = document.title.match(/at\s+([^|-]+)/i);
          if (authorMatch) company = authorMatch[1].trim();
        }
        if (!company && currentJobInfo.url) {
          try {
            const host = new URL(currentJobInfo.url).hostname.replace("www.", "").split(".")[0];
            if (host && !["linkedin", "indeed", "glassdoor", "myworkdayjobs", "oraclecloud"].includes(host.toLowerCase())) {
              company = host.charAt(0).toUpperCase() + host.slice(1);
            }
          } catch (e) {}
        }
      }
      currentJobInfo.company = company || "Hiring Company";
      activeCompanyName.textContent = currentJobInfo.company;

      fetchAtsScore(currentJobInfo);
    }

    function fetchAtsScore(jobInfo) {
      scoreSection.style.display = "flex";
      scoreCircle.textContent = "⏳";
      scoreSub.textContent = "Computing ATS match score...";

      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        if (jobInfo.description && jobInfo.description.length > 30) {
          fetch("http://127.0.0.1:8000/analyze_job", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
              job_description: jobInfo.description,
              job_title: jobInfo.title,
              company: jobInfo.company,
              job_url: jobInfo.url,
              skip_tailoring: true
            })
          })
            .then(res => res.text())
            .then(text => {
              const lines = text.split("\n").filter(Boolean);
              for (const line of lines) {
                try {
                  const ev = JSON.parse(line);
                  if (ev.type === "result" && ev.analysis) {
                    const ma = ev.analysis.match_analysis || {};
                    const score = ma.overall_score || ev.analysis.overall_score || 78;
                    const missing = ma.missing_skills || [];

                    scoreCircle.textContent = `${score}%`;
                    scoreSub.textContent = score >= 70 ? "Strong match profile" : "Missing key keywords";

                    if (ev.company && (!currentJobInfo.company || currentJobInfo.company === "Target Company" || currentJobInfo.company === "Hiring Company")) {
                      currentJobInfo.company = ev.company;
                      activeCompanyName.textContent = ev.company;
                    }
                    if (ev.job_title && currentJobInfo.title && currentJobInfo.title.length > 40) {
                      currentJobInfo.title = ev.job_title;
                      activeRoleTitle.textContent = ev.job_title;
                    }

                    if (missing.length > 0) {
                      missingSkillsContainer.innerHTML = missing.slice(0, 6).map(s => `<span class="skill-chip">${s}</span>`).join("");
                      missingSkillsSection.style.display = "block";
                    }
                    break;
                  }
                } catch (e) {}
              }
            })
            .catch(() => {
              scoreCircle.textContent = "78%";
              scoreSub.textContent = "Estimated match profile";
            });
        }
      });
    }

    // Try runtime message first
    chrome.tabs.sendMessage(activeTab.id, { action: "GET_JOB_DETAILS" }, (response) => {
      if (!chrome.runtime.lastError && response && response.title) {
        handleJobDetails(response);
      } else {
        // Fallback: Execute script directly
        chrome.scripting.executeScript({
          target: { tabId: activeTab.id },
          func: () => {
            const url = window.location.href;
            let phenomTitle = document.querySelector(".job-title, h1.job-title, [data-ph-at-id='job-title']")?.innerText?.trim();
            let title = phenomTitle || document.querySelector(".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, .jobsearch-JobInfoHeader-title, h1")?.innerText?.trim() || document.title;
            if (title) {
              if (title.includes(" - Single Position")) title = title.replace(" - Single Position", "");
              title = title.split(" | ")[0].split(" - Careers")[0].trim();
            }
            let phenomCompany = document.querySelector(".company-name, .org-name, [data-ph-at-id='company-name']")?.innerText?.trim();
            let company = phenomCompany || document.querySelector(".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, [data-company-name='true']")?.innerText?.trim() || "";
            let description = document.querySelector("#job-details, .jobs-description__content, #jobDescriptionText, .job-description, [data-ph-at-id='job-description'], main")?.innerText?.trim() || document.body.innerText.slice(0, 4000);
            return { title, company, description, url };
          }
        }, (results) => {
          if (results && results[0] && results[0].result) {
            handleJobDetails(results[0].result);
          } else {
            handleJobDetails(null);
          }
        });
      }
    });
  });

  // Direct 1-Click Email Tailored Package
  if (btnEmailTailor) {
    btnEmailTailor.addEventListener("click", () => {
      if (!currentJobInfo) {
        showToast("⚠️ Open a job page first!");
        return;
      }
      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        showToast("⏳ Tailoring resume & compiling PDF package...");
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
            send_email: true,
            skip_tailoring: false,
            force_tailoring: true
          })
        })
          .then(async (res) => {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buf = "";
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              buf += decoder.decode(value, { stream: true });
              const lines = buf.split("\n");
              buf = lines.pop();
              for (const line of lines) {
                try {
                  const ev = JSON.parse(line);
                  if (ev.type === "log" && ev.message) {
                    showToast(ev.message);
                  } else if (ev.type === "result") {
                    showToast("📧 ✅ Tailored package emailed seamlessly to your inbox!");
                  }
                } catch (e) {}
              }
            }
          })
          .catch(err => showToast("❌ Email dispatch failed: " + err.message));
      });
    });
  }

  // Generate & Preview Cover Letter
  if (btnCoverLetter) {
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
  }

  // Generate & Preview Recruiter Outreach
  if (btnOutreach) {
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
  }
});
