// popup.js - ATS Tailor Extension Controller (v2.6.0 Parametric Production Ready)

// Parameterized API Base URL (Configurable via chrome.storage.local key "backendUrl")
const DEFAULT_API_BASE_URL = "https://www.job-finder.space";
let API_BASE_URL = DEFAULT_API_BASE_URL;

chrome.storage.local.get(["backendUrl"], (items) => {
  if (items && items.backendUrl && items.backendUrl.trim()) {
    API_BASE_URL = items.backendUrl.trim().replace(/\/+$/, "");
  }
});


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
  const btnSettingsUrl = document.getElementById("btn-settings-url");
  const settingsUrlBox = document.getElementById("settings-url-box");

  if (btnSettingsUrl && settingsUrlBox) {
    btnSettingsUrl.addEventListener("click", () => {
      const isHidden = settingsUrlBox.style.display === "none";
      settingsUrlBox.style.display = isHidden ? "block" : "none";
    });
  }

  let currentJobInfo = null;
  let activePreviewText = "";

  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");
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
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    fetch(`${API_BASE_URL}/user/me`, {
      signal: controller.signal,
      headers: { "Authorization": `Bearer ${cleanKey}` }
    })
      .then((res) => {
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then((data) => {
        if (data && (data.email || data.id)) {
          const email = data.email || "";
          let candidateName = data.resume_name;
          if (!candidateName && email) {
            const handle = email.split("@")[0];
            candidateName = handle.replace(/[._-]/g, " ").toUpperCase();
          }
          if (!candidateName) {
            candidateName = "ACTIVE USER";
          }
          if (userNameDisplay) userNameDisplay.textContent = `✓ ${candidateName}`;
          if (userEmailDisplay) userEmailDisplay.textContent = `📧 ${email}`;
          if (userInfoCard) userInfoCard.style.display = "flex";
          const settingsUserInfo = document.getElementById("settings-user-info");
          if (settingsUserInfo) settingsUserInfo.textContent = `✓ ${candidateName} (${email})`;
        } else {
          if (userInfoCard) userInfoCard.style.display = "none";
        }
      })
      .catch(() => {
        if (userInfoCard) userInfoCard.style.display = "none";
      });
  }

  const backendUrlInput = document.getElementById("backend-url-input");

  // Load saved sync key and custom backend URL on popup boot
  chrome.storage.local.get(["userToken", "backendUrl"], (items) => {
    if (items.backendUrl && backendUrlInput) {
      backendUrlInput.value = items.backendUrl;
      API_BASE_URL = items.backendUrl.trim().replace(/\/+$/, "");
    } else if (backendUrlInput) {
      backendUrlInput.value = DEFAULT_API_BASE_URL;
    }
    if (items.userToken && userTokenInput) {
      userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
  });

  if (backendUrlInput) {
    backendUrlInput.addEventListener("change", (e) => {
      const url = e.target.value.trim().replace(/\/+$/, "");
      if (url) {
        API_BASE_URL = url;
        chrome.storage.local.set({ backendUrl: url }, () => {
          showToast("✓ Server endpoint updated!");
          const syncKey = userTokenInput ? userTokenInput.value.trim() : "";
          if (syncKey) fetchUserInfo(syncKey);
        });
      }
    });
  }

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
      activeCompanyName.textContent = currentJobInfo.company || "Detecting company...";

      // Call dedicated extension endpoint to extract exact Company & Role via LLM
      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        if (currentJobInfo.description && currentJobInfo.description.length > 20) {
          fetch(`${API_BASE_URL}/extension/parse_job_details`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token}`
            },
            body: JSON.stringify({
              page_text: currentJobInfo.pageSource || currentJobInfo.description,
              page_url: currentJobInfo.url,
              page_title: currentJobInfo.title
            })
          })
            .then(res => res.json())
            .then(data => {
              if (data && data.company) {
                currentJobInfo.company = data.company;
                activeCompanyName.textContent = data.company;
              } else if (!currentJobInfo.company || currentJobInfo.company === "Detecting company...") {
                currentJobInfo.company = "Hiring Company";
                activeCompanyName.textContent = "Hiring Company";
              }
              if (data && data.job_title) {
                currentJobInfo.title = data.job_title;
                activeRoleTitle.textContent = data.job_title;
              }
              if (data && data.job_description && data.job_description.length > currentJobInfo.description.length) {
                currentJobInfo.description = data.job_description;
              }
              fetchAtsScore(currentJobInfo);
            })
            .catch(() => {
              if (!currentJobInfo.company || currentJobInfo.company === "Detecting company...") {
                currentJobInfo.company = "Hiring Company";
                activeCompanyName.textContent = "Hiring Company";
              }
              fetchAtsScore(currentJobInfo);
            });
        } else {
          fetchAtsScore(currentJobInfo);
        }
      });
    }

    function fetchAtsScore(jobInfo) {
      scoreSection.style.display = "flex";
      scoreCircle.textContent = "⏳";
      scoreSub.textContent = "Computing ATS match score...";

      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        if (jobInfo.description && jobInfo.description.length > 30) {
          fetch(`${API_BASE_URL}/analyze_job`, {
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

                    const alignCard = document.getElementById("alignment-report-card");
                    const alignSen = document.getElementById("align-seniority");
                    const alignDom = document.getElementById("align-domain");
                    const alignVer = document.getElementById("align-verdict");

                    if (ma.alignment_report && alignCard && alignSen && alignDom && alignVer) {
                      alignSen.textContent = ma.alignment_report.seniority || "Direct Alignment";
                      alignDom.textContent = ma.alignment_report.domain || "High Alignment";
                      alignVer.textContent = ma.alignment_report.verdict || "Strong Match";
                      alignCard.style.display = "block";
                    } else if (alignCard) {
                      alignCard.style.display = "none";
                    }

                    if (missing.length > 0) {
                      window.selectedUserSkills = window.selectedUserSkills || new Set();
                      missingSkillsContainer.innerHTML = missing.slice(0, 8).map(s => {
                        const isSelected = window.selectedUserSkills.has(s);
                        return `<span class="skill-chip ${isSelected ? "selected" : ""}" data-skill="${s}">${isSelected ? "✓ " : "+ "}${s}</span>`;
                      }).join("");
                      missingSkillsSection.style.display = "block";

                      // Add click listener to toggle skill selection & dynamically recalculate score preview
                      window.baseAtsScore = score;
                      missingSkillsContainer.querySelectorAll(".skill-chip").forEach(chip => {
                        chip.addEventListener("click", () => {
                          const sk = chip.getAttribute("data-skill");
                          if (window.selectedUserSkills.has(sk)) {
                            window.selectedUserSkills.delete(sk);
                            chip.classList.remove("selected");
                            chip.textContent = "+ " + sk;
                          } else {
                            window.selectedUserSkills.add(sk);
                            chip.classList.add("selected");
                            chip.textContent = "✓ " + sk;
                          }
                          // Recalculate preview score instantly using exact JD skill importance weights (0.40 * mandatory_weight * weight)
                          const skillWeights = (ev.analysis && ev.analysis.match_analysis && ev.analysis.match_analysis.score_breakdown && ev.analysis.match_analysis.score_breakdown.skill_weights) || {};
                          let totalBoost = 0;
                          window.selectedUserSkills.forEach(s => {
                            const w = skillWeights[s] || (1 / (missing.length || 5));
                            // Boost = 0.40 (skills weight) * 85.0 * w
                            totalBoost += (0.40 * 85.0 * w);
                          });
                          const addedCount = window.selectedUserSkills.size;
                          const boostedScore = Math.min(99, Math.round((window.baseAtsScore || score) + totalBoost));
                          scoreCircle.textContent = `${boostedScore}%`;
                          scoreSub.textContent = boostedScore >= 70 ? `Strong match profile (${addedCount} forced skill${addedCount > 1 ? "s" : ""})` : "Missing key keywords";
                        });
                      });
                    }
                    break;
                  }
                } catch (e) {}
              }
            })
            .catch((err) => {
              scoreCircle.textContent = "⚠️";
              scoreSub.textContent = "Offline / Server non-responsive";
            });
        }
      });
    }

    // Try runtime message first
    chrome.tabs.sendMessage(activeTab.id, { action: "GET_JOB_DETAILS" }, (response) => {
      const err = chrome.runtime.lastError; // Access to suppress unchecked runtime error
      if (!err && response && response.title) {
        handleJobDetails(response);
      } else {
        // Fallback: Execute script directly with error suppression
        try {
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
            const pageSource = document.body ? document.body.innerText.slice(0, 15000) : description;
            return { title, company, description, url, pageSource };
          }
          }, (results) => {
            const err = chrome.runtime.lastError; // Access to suppress unchecked runtime error
            if (!err && results && results[0] && results[0].result) {
              handleJobDetails(results[0].result);
            } else {
              handleJobDetails(null);
            }
          });
        } catch (e) {
          handleJobDetails(null);
        }
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
        fetch(`${API_BASE_URL}/analyze_job`, {
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
            force_tailoring: true,
            source_mode: "extension",
            user_selected_skills: Array.from(window.selectedUserSkills || [])
          })
        })
          .then(async (res) => {
            if (!res.ok) {
              const errJson = await res.json().catch(() => ({}));
              throw new Error(errJson.detail || `Server error (${res.status})`);
            }
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
                    if (!ev.message.includes("Comparing candidate profile") && !ev.message.includes("ATS gap analysis")) {
                      showToast(ev.message);
                    }
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
        fetch(`${API_BASE_URL}/generate_cover_letter_history`, {
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
          .then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `Server error (${res.status})`);
            return data;
          })
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
        fetch(`${API_BASE_URL}/generate_outreach`, {
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
          .then(async (res) => {
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || `Server error (${res.status})`);
            return data;
          })
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
