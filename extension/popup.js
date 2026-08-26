// popup.js - Job Finder ATS Tailor Controller (v2.9.0 Fast JSON Sync Edition)

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
let API_BASE_URL = DEFAULT_API_BASE_URL;

document.addEventListener("DOMContentLoaded", () => {
  // Elements - Header & Tabs
  const statusBadge = document.getElementById("backend-status");
  const navTabs = document.querySelectorAll(".nav-tab");
  const tabPanes = document.querySelectorAll(".tab-pane");

  // Tab 1 Elements: ATS & Apply
  const activeRoleTitle = document.getElementById("active-role-title");
  const activeCompanyName = document.getElementById("active-company-name");
  const scoreCircle = document.getElementById("ats-score-circle");
  const scoreSub = document.getElementById("ats-score-sub");
  const alignCard = document.getElementById("alignment-report-card");
  const alignSen = document.getElementById("align-seniority");
  const alignDom = document.getElementById("align-domain");
  const alignVer = document.getElementById("align-verdict");
  const alignFlagsBox = document.getElementById("align-flags-box");
  const alignFlags = document.getElementById("align-flags");
  const missingSkillsSection = document.getElementById("missing-skills-section");
  const missingSkillsContainer = document.getElementById("missing-skills-container");

  const previewWrapper = document.getElementById("text-preview-wrapper");
  const previewTitle = document.getElementById("preview-title");
  const previewContent = document.getElementById("text-preview-content");
  const btnCopyPreview = document.getElementById("btn-copy-preview");

  // Custom JD Paste & Edit Elements
  const linkEditJd = document.getElementById("link-edit-jd");
  const jdMissingAlert = document.getElementById("jd-missing-alert");
  const btnToggleCustomJd = document.getElementById("btn-toggle-custom-jd");
  const customJdBox = document.getElementById("custom-jd-box");
  const btnCloseCustomJd = document.getElementById("btn-close-custom-jd");
  const customJdTitle = document.getElementById("custom-jd-title");
  const customJdCompany = document.getElementById("custom-jd-company");
  const customJdText = document.getElementById("custom-jd-text");
  const btnSubmitCustomJd = document.getElementById("btn-submit-custom-jd");

  const btnFill = document.getElementById("btn-autofill");
  const btnTailorPdf = document.getElementById("btn-tailor-pdf");
  const btnEmailTailor = document.getElementById("btn-email-tailor");
  const btnCoverLetter = document.getElementById("btn-cover-letter");
  const btnOutreach = document.getElementById("btn-outreach");

  // Tab 2 Elements: Profile
  const btnSyncBackendNow = document.getElementById("btn-sync-backend-now");
  const profFirstName = document.getElementById("prof-firstName");
  const profLastName = document.getElementById("prof-lastName");
  const profEmail = document.getElementById("prof-email");
  const profPhone = document.getElementById("prof-phone");
  const profLocation = document.getElementById("prof-location");
  const profLinkedin = document.getElementById("prof-linkedin");
  const profGithub = document.getElementById("prof-github");
  const profPortfolio = document.getElementById("prof-portfolio");
  const profSkills = document.getElementById("prof-skills");
  const profNotice = document.getElementById("prof-notice");
  const profSalary = document.getElementById("prof-salary");
  const eeoWorkAuth = document.getElementById("eeo-work-auth");
  const eeoSponsorship = document.getElementById("eeo-sponsorship");
  const profSummary = document.getElementById("prof-summary");
  const btnSaveProfile = document.getElementById("btn-save-profile");

  // Tab 3 Elements: Settings
  const userTokenInput = document.getElementById("user-token");
  const backendUrlInput = document.getElementById("backend-url-input");
  const userInfoCard = document.getElementById("user-info-card");
  const userNameDisplay = document.getElementById("user-name-display");
  const userEmailDisplay = document.getElementById("user-email-display");
  const btnSaveSettings = document.getElementById("btn-save-settings");
  const toast = document.getElementById("popup-toast");

  let currentJobInfo = null;
  let activePreviewText = "";
  window.selectedUserSkills = new Set();
  window.baseAtsScore = null;

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.style.display = "block";
    setTimeout(() => { toast.style.display = "none"; }, 3500);
  }

  // ----------------------------------------------------
  // Helper: Recursive Skill Extractor
  // ----------------------------------------------------
  function extractSkillsList(skills) {
    if (!skills) return [];
    if (typeof skills === "string") {
      return skills.split(",").map((s) => s.trim()).filter(Boolean);
    }
    if (Array.isArray(skills)) {
      const list = [];
      skills.forEach((item) => {
        if (typeof item === "string") {
          list.push(item.trim());
        } else if (item && typeof item === "object") {
          if (item.skill) list.push(String(item.skill).trim());
          else if (item.name) list.push(String(item.name).trim());
          else if (Array.isArray(item.skills)) list.push(...extractSkillsList(item.skills));
          else {
            Object.values(item).forEach((v) => {
              if (typeof v === "string") list.push(v.trim());
              else if (Array.isArray(v)) list.push(...extractSkillsList(v));
            });
          }
        }
      });
      return Array.from(new Set(list)).filter(Boolean);
    }
    if (typeof skills === "object") {
      const list = [];
      Object.values(skills).forEach((val) => {
        if (typeof val === "string") list.push(val.trim());
        else if (Array.isArray(val)) list.push(...extractSkillsList(val));
      });
      return Array.from(new Set(list)).filter(Boolean);
    }
    return [];
  }

  // ----------------------------------------------------
  // Tab Switching
  // ----------------------------------------------------
  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      navTabs.forEach((t) => t.classList.remove("active"));
      tabPanes.forEach((p) => p.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-target");
      const targetPane = document.getElementById(targetId);
      if (targetPane) targetPane.classList.add("active");
    });
  });

  // ----------------------------------------------------
  // User & Base URL Sync
  // ----------------------------------------------------
  function getBaseUrl() {
    return API_BASE_URL;
  }

  function getAuthToken() {
    return (userTokenInput?.value || "").trim().toUpperCase();
  }

  function checkHealth() {
    fetch(`${API_BASE_URL}/healthz`, { headers: { "Accept": "application/json" } })
      .then((res) => {
        if (res.ok) {
          statusBadge.innerHTML = '<span class="status-dot"></span><span>Connected</span>';
          statusBadge.style.color = "#34d399";
        } else {
          statusBadge.innerHTML = '<span>Offline 🔴</span>';
          statusBadge.style.color = "#f87171";
        }
      })
      .catch(() => {
        statusBadge.innerHTML = '<span>Offline 🔴</span>';
        statusBadge.style.color = "#f87171";
      });
  }

  async function fetchUserInfo(syncKey, showAlert = false) {
    const key = (syncKey || getAuthToken()).trim().toUpperCase();
    if (!key) {
      if (showAlert) showToast("⚠️ Set your 6-digit Sync Key in Settings first!");
      return;
    }

    try {
      // 1. Fetch user data from /user/me
      const res = await fetch(`${API_BASE_URL}/user/me`, {
        headers: { "Authorization": `Bearer ${key}`, "Accept": "application/json" }
      });
      const ct = res.headers.get("content-type") || "";

      let resume = null;
      let userEmail = "";
      let userName = "";

      if (res.ok && ct.includes("application/json")) {
        const data = await res.json();
        if (data) {
          userEmail = data.email || "";
          userName = data.resume_name || "";
          if (data.resume_data) {
            resume = data.resume_data;
            if (resume.name) userName = resume.name;
          }
        }
      }

      // 2. Fallback / Enrichment from /get_session_resume
      if (!resume || !resume.name) {
        try {
          const sessRes = await fetch(`${API_BASE_URL}/get_session_resume`, {
            headers: { "Authorization": `Bearer ${key}`, "Accept": "application/json" }
          });
          if (sessRes.ok) {
            const sessData = await sessRes.json();
            if (sessData && sessData.data && sessData.data.name) {
              resume = sessData.data;
              if (resume.name) userName = resume.name;
            }
          }
        } catch (e) {}
      }

      const displayName = userName || (userEmail ? userEmail.split("@")[0] : "Candidate Profile");
      if (userNameDisplay) userNameDisplay.textContent = `👤 Synced: ${displayName}`;
      if (userEmailDisplay && userEmail) userEmailDisplay.textContent = `📧 ${userEmail}`;
      if (userInfoCard) userInfoCard.style.display = "flex";

      if (resume) {
        populateProfileUI(resume, true);
        chrome.storage.local.set({ resumeData: resume, userToken: key });
        if (showAlert) showToast("⚡ Synced profile & resume from web app!");
      } else {
        if (showAlert) showToast("⚡ Connected! No resume uploaded yet in web app.");
      }
    } catch (e) {
      if (showAlert) showToast("❌ Could not connect to backend server");
    }
  }

  function populateProfileUI(resume, forceOverwrite = false) {
    if (!resume) return;

    const fullName = (resume.name || "").trim().split(/\s+/);
    if (profFirstName && (forceOverwrite || !profFirstName.value)) profFirstName.value = fullName[0] || "";
    if (profLastName && (forceOverwrite || !profLastName.value)) profLastName.value = fullName.slice(1).join(" ") || "";
    if (profEmail && (forceOverwrite || !profEmail.value)) profEmail.value = resume.email || "";
    if (profPhone && (forceOverwrite || !profPhone.value)) profPhone.value = resume.phone || "";
    if (profLocation && (forceOverwrite || !profLocation.value)) profLocation.value = resume.location || "";

    const links = Array.isArray(resume.links) ? resume.links : [];
    const linkedin = links.find((l) => l.toLowerCase().includes("linkedin")) || resume.linkedin || "";
    const github = links.find((l) => l.toLowerCase().includes("github")) || resume.github || "";
    const portfolio = links.find((l) => !l.toLowerCase().includes("linkedin") && !l.toLowerCase().includes("github")) || resume.portfolio || "";

    if (profLinkedin && (forceOverwrite || !profLinkedin.value)) profLinkedin.value = linkedin;
    if (profGithub && (forceOverwrite || !profGithub.value)) profGithub.value = github;
    if (profPortfolio && (forceOverwrite || !profPortfolio.value)) profPortfolio.value = portfolio;

    const skillsList = extractSkillsList(resume.skills);
    const skillsStr = skillsList.join(", ");
    if (profSkills && (forceOverwrite || !profSkills.value)) profSkills.value = skillsStr;

    const notice = resume.notice_period || resume.noticePeriod || "";
    if (profNotice && (forceOverwrite || !profNotice.value)) profNotice.value = notice || "Available immediately";

    const salary = resume.salary_expectations || resume.salary || "";
    if (profSalary && (forceOverwrite || !profSalary.value)) profSalary.value = salary || "Competitive market rate";

    const workAuth = resume.work_auth || resume.workAuth || (resume.eeo && resume.eeo.workAuth) || "";
    if (eeoWorkAuth && (forceOverwrite || !eeoWorkAuth.value)) eeoWorkAuth.value = workAuth || "Yes";

    const sponsorship = resume.sponsorship || (resume.eeo && resume.eeo.sponsorship) || "";
    if (eeoSponsorship && (forceOverwrite || !eeoSponsorship.value)) eeoSponsorship.value = sponsorship || "No";

    if (profSummary && (forceOverwrite || !profSummary.value)) {
      if (typeof resume === "object") {
        profSummary.value = JSON.stringify(resume, null, 2);
      } else {
        profSummary.value = String(resume || "");
      }
    }
  }

  // ----------------------------------------------------
  // Load Storage Initialization
  // ----------------------------------------------------
  chrome.storage.local.get(["backendUrl", "userToken", "resumeData", "eeoProfile", "noticePeriod", "salaryExpectations"], (items) => {
    if (items && items.backendUrl && items.backendUrl.trim()) {
      API_BASE_URL = items.backendUrl.trim().replace(/\/+$/, "");
      if (backendUrlInput) backendUrlInput.value = API_BASE_URL;
    } else if (backendUrlInput) {
      backendUrlInput.value = DEFAULT_API_BASE_URL;
    }

    if (items && items.userToken) {
      if (userTokenInput) userTokenInput.value = items.userToken;
      fetchUserInfo(items.userToken);
    }
    if (items && items.resumeData) populateProfileUI(items.resumeData);

    const eeo = items?.eeoProfile || {};
    if (eeo.workAuth && eeoWorkAuth) eeoWorkAuth.value = eeo.workAuth;
    if (eeo.sponsorship && eeoSponsorship) eeoSponsorship.value = eeo.sponsorship;

    if (items?.noticePeriod && profNotice) profNotice.value = items.noticePeriod;
    if (items?.salaryExpectations && profSalary) profSalary.value = items.salaryExpectations;

    checkHealth();
    scanActiveTab();
  });

  // ----------------------------------------------------
  // Active Tab Scraping & ATS Gap Analysis
  // ----------------------------------------------------
  function handleJobDetails(details) {
    if (!details || (!details.title && !details.description)) {
      if (activeRoleTitle) activeRoleTitle.textContent = "No job posting detected";
      if (activeCompanyName) activeCompanyName.textContent = "Open LinkedIn, Indeed, or Greenhouse";
      if (scoreCircle) scoreCircle.textContent = "—";
      if (scoreSub) scoreSub.textContent = "Navigate to a job posting tab";
      if (jdMissingAlert) jdMissingAlert.style.display = "block";
      return;
    }

    currentJobInfo = details;
    if (activeRoleTitle) activeRoleTitle.textContent = details.title || "Detected Job Posting";
    if (activeCompanyName) activeCompanyName.textContent = details.company || "Hiring Company";

    if (customJdTitle && (!customJdTitle.value || customJdTitle.value === "Detected Job Posting")) customJdTitle.value = details.title || "";
    if (customJdCompany && (!customJdCompany.value || customJdCompany.value === "Hiring Company")) customJdCompany.value = details.company || "";
    if (customJdText && (!customJdText.value || customJdText.value.length < 50) && details.description) {
      customJdText.value = details.description;
    }

    const descLen = (details.description || "").trim().length;
    const titleLower = (details.title || "").toLowerCase();
    const descLower = (details.description || "").toLowerCase();
    const isJdMissing = descLen < 150 || titleLower === "careers" || descLower.includes("job description is missing") || descLower.includes("unspecified job description");

    if (jdMissingAlert) {
      jdMissingAlert.style.display = isJdMissing ? "block" : "none";
    }

    chrome.storage.local.get(["userToken", "resumeData", "candidateProfile"], (items) => {
      const token = items ? items.userToken || "guest" : "guest";
      const candidateProfile = (items && (items.resumeData || items.candidateProfile)) || null;

      fetch(`${API_BASE_URL}/analyze_job`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${token}`
        },
        body: JSON.stringify({
          job_url: details.url,
          job_title: details.title,
          job_description: details.description,
          candidate_profile: candidateProfile,
          send_email: false,
          skip_tailoring: true,
          source_mode: "extension"
        })
      })
        .then(async (res) => {
          if (!res.ok) {
            let errMsg = "Backend error";
            try {
              const errData = await res.json();
              errMsg = errData.detail || errMsg;
            } catch (e) {}
            throw new Error(errMsg);
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
                if (ev.type === "result") {
                  const score = ev.fit_score !== undefined ? ev.fit_score : 75;
                  scoreCircle.textContent = `${score}%`;
                  scoreSub.textContent = score >= 70 ? "Strong match profile" : "Missing key keywords";
                  scoreCircle.style.borderColor = score >= 70 ? "#34d399" : score >= 50 ? "#38bdf8" : "#fb7185";
                  scoreCircle.style.color = score >= 70 ? "#34d399" : score >= 50 ? "#38bdf8" : "#fb7185";

                  const ma = ev.analysis && ev.analysis.match_analysis ? ev.analysis.match_analysis : {};
                  const missing = ma.missing_skills || [];

                  if (ev.company && (!currentJobInfo.company || currentJobInfo.company === "Target Company")) {
                    currentJobInfo.company = ev.company;
                    activeCompanyName.textContent = ev.company;
                  }
                  if (ev.job_title && currentJobInfo.title && currentJobInfo.title.length > 40) {
                    currentJobInfo.title = ev.job_title;
                    activeRoleTitle.textContent = ev.job_title;
                  }

                  if (ma.alignment_report && alignCard && alignSen && alignDom && alignVer) {
                    alignSen.textContent = ma.alignment_report.seniority || "Direct Alignment";
                    alignDom.textContent = ma.alignment_report.domain || "High Alignment";
                    alignVer.textContent = ma.alignment_report.verdict || "Strong Match";
                    const rf = ma.alignment_report.red_flags;
                    if (rf && rf !== "None detected" && alignFlagsBox && alignFlags) {
                      alignFlags.textContent = rf;
                      alignFlagsBox.style.display = "block";
                    } else if (alignFlagsBox) {
                      alignFlagsBox.style.display = "none";
                    }
                    alignCard.style.display = "block";
                  }

                  if (missing.length > 0) {
                    window.selectedUserSkills = window.selectedUserSkills || new Set();
                    missingSkillsContainer.innerHTML = missing.slice(0, 8).map((s) => {
                      const isSelected = window.selectedUserSkills.has(s);
                      return `<span class="skill-chip ${isSelected ? "selected" : ""}" data-skill="${s}">${isSelected ? "✓ " : "+ "}${s}</span>`;
                    }).join("");
                    missingSkillsSection.style.display = "block";

                    window.baseAtsScore = score;
                    missingSkillsContainer.querySelectorAll(".skill-chip").forEach((chip) => {
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
                        const skillWeights = (ev.analysis && ev.analysis.match_analysis && ev.analysis.match_analysis.score_breakdown && ev.analysis.match_analysis.score_breakdown.skill_weights) || {};
                        let totalBoost = 0;
                        window.selectedUserSkills.forEach((s) => {
                          const w = skillWeights[s] || (1 / (missing.length || 5));
                          totalBoost += (0.40 * 85.0 * w);
                        });
                        const addedCount = window.selectedUserSkills.size;
                        const boostedScore = Math.min(99, Math.round((window.baseAtsScore || score) + totalBoost));
                        scoreCircle.textContent = `${boostedScore}%`;
                        scoreSub.textContent = boostedScore >= 70 ? `Strong match profile (${addedCount} boosted)` : "Missing key keywords";
                      });
                    });
                  }
                  break;
                }
              } catch (e) {}
            }
          }
        })
        .catch((err) => {
          const msg = (err && err.message) || "";
          if (msg.toLowerCase().includes("resume") || msg.toLowerCase().includes("upload")) {
            scoreCircle.textContent = "—";
            scoreSub.textContent = "Upload or sync resume to score";
          } else {
            scoreCircle.textContent = "⚠️";
            scoreSub.textContent = "Offline / Server non-responsive";
          }
        });
    });
  }

  function isRestrictedUrl(url) {
    if (!url) return true;
    return (
      url.startsWith("chrome://") ||
      url.startsWith("chrome-extension://") ||
      url.startsWith("edge://") ||
      url.startsWith("about:") ||
      url.startsWith("devtools://") ||
      url.startsWith("view-source:") ||
      url.startsWith("chrome-search://")
    );
  }

  function scanActiveTab() {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs || !tabs[0]) return;
      const activeTab = tabs[0];
      const tabUrl = activeTab.url || "";
      if (isRestrictedUrl(tabUrl)) {
        handleJobDetails(null);
        return;
      }

      chrome.tabs.sendMessage(activeTab.id, { action: "GET_JOB_DETAILS" }, (response) => {
        const err = chrome.runtime.lastError;
        if (!err && response && response.title) {
          handleJobDetails(response);
        } else {
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
              const scriptErr = chrome.runtime.lastError;
              if (!scriptErr && results && results[0] && results[0].result) {
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
  }

  // ----------------------------------------------------
  // Action Handlers
  // ----------------------------------------------------
  function toggleCustomJd(show) {
    if (!customJdBox) return;
    const isVisible = customJdBox.style.display === "block";
    const nextState = typeof show === "boolean" ? show : !isVisible;
    customJdBox.style.display = nextState ? "block" : "none";
    if (nextState) {
      if (currentJobInfo) {
        if (customJdTitle && (!customJdTitle.value || customJdTitle.value === "Detected Job Posting")) customJdTitle.value = currentJobInfo.title || "";
        if (customJdCompany && (!customJdCompany.value || customJdCompany.value === "Hiring Company")) customJdCompany.value = currentJobInfo.company || "";
        if (customJdText && (!customJdText.value || customJdText.value.length < 50)) customJdText.value = currentJobInfo.description || "";
      }
      customJdText?.focus();
    }
  }

  if (linkEditJd) {
    linkEditJd.addEventListener("click", (e) => {
      e.preventDefault();
      toggleCustomJd();
    });
  }

  if (btnToggleCustomJd) {
    btnToggleCustomJd.addEventListener("click", () => toggleCustomJd(true));
  }

  if (btnCloseCustomJd) {
    btnCloseCustomJd.addEventListener("click", () => toggleCustomJd(false));
  }

  if (btnSubmitCustomJd) {
    btnSubmitCustomJd.addEventListener("click", () => {
      const title = (customJdTitle?.value || "").trim() || (currentJobInfo?.title || "Target Role");
      const company = (customJdCompany?.value || "").trim() || (currentJobInfo?.company || "Hiring Company");
      const desc = (customJdText?.value || "").trim();

      if (!desc || desc.length < 20) {
        showToast("⚠️ Please paste the job description text!");
        return;
      }

      const updatedDetails = {
        title,
        company,
        description: desc,
        pageSource: desc,
        url: currentJobInfo?.url || window.location.href
      };

      currentJobInfo = updatedDetails;
      if (activeRoleTitle) activeRoleTitle.textContent = title;
      if (activeCompanyName) activeCompanyName.textContent = company;
      if (jdMissingAlert) jdMissingAlert.style.display = "none";
      toggleCustomJd(false);

      showToast("🎯 Analyzing & re-scoring with pasted JD...");
      handleJobDetails(updatedDetails);
    });
  }

  // Single-Page Auto-Fill Trigger
  if (btnFill) {
    btnFill.addEventListener("click", () => {
      btnFill.textContent = "⚡ Filling Active Form...";
      chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
        if (!tabs || !tabs[0]?.id) {
          btnFill.textContent = "⚡ Fill Active Application";
          return;
        }
        const activeTabId = tabs[0].id;
        const url = tabs[0].url || "";
        if (url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("about:")) {
          showToast("⚠️ Open a job application page first!");
          btnFill.textContent = "⚡ Fill Active Application";
          return;
        }

        chrome.tabs.sendMessage(activeTabId, { action: "TRIGGER_AUTOFILL" }, (response) => {
          const err = chrome.runtime.lastError; // Access to suppress unchecked runtime error
          if (err) {
            // Content script was not loaded on this tab yet, dynamically inject it and trigger autofill
            try {
              chrome.scripting.executeScript({
                target: { tabId: activeTabId },
                files: ["content.js"]
              }, () => {
                const err2 = chrome.runtime.lastError;
                if (!err2) {
                  setTimeout(() => {
                    chrome.tabs.sendMessage(activeTabId, { action: "TRIGGER_AUTOFILL" }, () => {
                      const err3 = chrome.runtime.lastError;
                      setTimeout(() => { btnFill.textContent = "⚡ Fill Active Application"; }, 1400);
                    });
                  }, 200);
                } else {
                  showToast("⚠️ Please reload the job page and retry.");
                  btnFill.textContent = "⚡ Fill Active Application";
                }
              });
            } catch (e) {
              showToast("⚠️ Please reload the job page and retry.");
              btnFill.textContent = "⚡ Fill Active Application";
            }
          } else {
            setTimeout(() => { btnFill.textContent = "⚡ Fill Active Application"; }, 1400);
          }
        });
      });
    });
  }

  // 1-Click Tailor & Download PDF
  if (btnTailorPdf) {
    btnTailorPdf.addEventListener("click", () => {
      if (!currentJobInfo) {
        showToast("⚠️ Open a job page first!");
        return;
      }
      chrome.storage.local.get(["userToken"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        showToast("⏳ Tailoring LaTeX resume & compiling PDF...");
        btnTailorPdf.disabled = true;
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
            send_email: false,
            skip_tailoring: false,
            force_tailoring: true,
            source_mode: "extension",
            user_selected_skills: Array.from(window.selectedUserSkills || [])
          })
        })
          .then(async (res) => {
            if (!res.ok) throw new Error(`Server error (${res.status})`);
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buf = "";
            let openedPdf = false;
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
                    if (!ev.message.includes("Comparing candidate profile")) showToast(ev.message);
                  } else if (ev.type === "result") {
                    if (ev.download_pdf_url && !openedPdf) {
                      openedPdf = true;
                      const pdfUrl = ev.download_pdf_url.startsWith("http") ? ev.download_pdf_url : `${API_BASE_URL}${ev.download_pdf_url}`;
                      chrome.tabs.create({ url: pdfUrl });
                      showToast("📄 ✅ Tailored PDF generated & opened!");
                    } else {
                      showToast(`📄 ✅ Resume tailored! (Fit score: ${ev.fit_score || 85}%)`);
                    }
                  }
                } catch (e) {}
              }
            }
          })
          .catch((err) => showToast("❌ Tailoring failed: " + err.message))
          .finally(() => { btnTailorPdf.disabled = false; });
      });
    });
  }

  // 1-Click Email Tailored Package
  if (btnEmailTailor) {
    btnEmailTailor.addEventListener("click", () => {
      if (!currentJobInfo) {
        showToast("⚠️ Open a job page first!");
        return;
      }
      chrome.storage.local.get(["userToken", "resumeData", "candidateProfile"], (items) => {
        const token = items ? items.userToken || "guest" : "guest";
        const candidateProfile = (items && (items.resumeData || items.candidateProfile)) || null;

        showToast("⏳ Tailoring resume & compiling PDF package...");
        btnEmailTailor.disabled = true;

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
            candidate_profile: candidateProfile,
            send_email: true,
            skip_tailoring: false,
            force_tailoring: true,
            source_mode: "extension",
            user_selected_skills: Array.from(window.selectedUserSkills || [])
          })
        })
          .then(async (res) => {
            if (!res.ok) throw new Error(`Server error (${res.status})`);
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
                  if (ev.type === "result") {
                    showToast("📧 ✅ Tailored package emailed seamlessly to your inbox!");
                  }
                } catch (e) {}
              }
            }
          })
          .catch((err) => showToast("❌ Email dispatch failed: " + err.message))
          .finally(() => { btnEmailTailor.disabled = false; });
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
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
          body: JSON.stringify({
            job_title: currentJobInfo.title,
            company: currentJobInfo.company,
            job_url: currentJobInfo.url
          })
        })
          .then((res) => res.json())
          .then((data) => {
            if (data.cover_letter) {
              activePreviewText = data.cover_letter;
              previewTitle.textContent = "📝 Generated Cover Letter";
              previewContent.textContent = data.cover_letter;
              previewWrapper.style.display = "block";
              showToast("📝 Cover letter generated! Preview below.");
            }
          })
          .catch((err) => showToast("❌ Error: " + err.message));
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
          headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
          body: JSON.stringify({
            job_title: currentJobInfo.title || "Target Role",
            company_name: currentJobInfo.company || "Target Company",
            job_description: currentJobInfo.description || currentJobInfo.title || "Target Role",
            job_url: currentJobInfo.url || ""
          })
        })
          .then((res) => res.json())
          .then((data) => {
            const msg = data.message?.email_body || data.message?.linkedin_message || "Outreach generated!";
            activePreviewText = msg;
            previewTitle.textContent = "✉️ Generated Outreach Message";
            previewContent.textContent = msg;
            previewWrapper.style.display = "block";
            showToast("✉️ Outreach generated! Preview below.");
          })
          .catch((err) => showToast("❌ Error: " + err.message));
      });
    });
  }

  if (btnCopyPreview) {
    btnCopyPreview.addEventListener("click", () => {
      if (previewContent && previewContent.textContent) {
        navigator.clipboard.writeText(previewContent.textContent);
        btnCopyPreview.textContent = "✅ Copied!";
        setTimeout(() => { btnCopyPreview.textContent = "📋 Copy to Clipboard"; }, 2000);
      }
    });
  }

  // ----------------------------------------------------
  // Save & Storage Handlers
  // ----------------------------------------------------
  if (btnSyncBackendNow) {
    btnSyncBackendNow.addEventListener("click", () => {
      chrome.storage.local.get(["userToken"], (items) => {
        const token = (items?.userToken || userTokenInput?.value || "").trim();
        fetchUserInfo(token, true);
      });
    });
  }

  if (btnSaveProfile) {
    btnSaveProfile.addEventListener("click", () => {
      let parsedResumeObj = {};
      try {
        parsedResumeObj = JSON.parse(profSummary.value);
      } catch (e) {
        parsedResumeObj = {};
      }

      const noticePeriod = (profNotice?.value || "").trim() || "Available immediately";
      const salaryExpectations = (profSalary?.value || "").trim() || "Competitive market rate";

      const resumeData = {
        ...parsedResumeObj,
        name: `${profFirstName.value} ${profLastName.value}`.trim() || parsedResumeObj.name || "",
        email: profEmail.value.trim() || parsedResumeObj.email || "",
        phone: profPhone.value.trim() || parsedResumeObj.phone || "",
        location: profLocation.value.trim() || parsedResumeObj.location || "",
        notice_period: noticePeriod,
        salary_expectations: salaryExpectations,
        links: [profLinkedin.value.trim(), profGithub.value.trim(), profPortfolio.value.trim()].filter(Boolean),
        skills: profSkills.value.split(",").map((s) => s.trim()).filter(Boolean),
        summary: parsedResumeObj.summary || profSummary.value.trim()
      };

      const eeoProfile = {
        workAuth: eeoWorkAuth.value,
        sponsorship: eeoSponsorship.value
      };

      chrome.storage.local.set({ resumeData, eeoProfile, noticePeriod, salaryExpectations }, () => {
        if (profSummary) profSummary.value = JSON.stringify(resumeData, null, 2);
        showToast("💾 Saved locally! Syncing to cloud...");

        // Cloud sync to Supabase backend
        chrome.storage.local.get(["userToken"], (items) => {
          const token = (items?.userToken || userTokenInput?.value || "").trim();
          fetch(`${API_BASE_URL}/user/profile`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": `Bearer ${token || "guest"}`
            },
            body: JSON.stringify({
              name: `${profFirstName.value} ${profLastName.value}`.trim(),
              email: profEmail.value.trim(),
              phone: profPhone.value.trim(),
              location: profLocation.value.trim(),
              portfolio: profPortfolio.value.trim(),
              linkedin: profLinkedin.value.trim(),
              github: profGithub.value.trim(),
              notice_period: noticePeriod,
              salary_expectations: salaryExpectations,
              work_auth: eeoWorkAuth.value,
              sponsorship: eeoSponsorship.value,
              skills: profSkills.value.split(",").map((s) => s.trim()).filter(Boolean),
              summary: profSummary.value.trim(),
              raw_resume_data: resumeData
            })
          })
            .then((res) => {
              if (res.ok) {
                showToast("☁️ ✅ Profile & Preferences Synced to Cloud!");
              } else {
                showToast("✅ Profile Saved locally!");
              }
            })
            .catch(() => {
              showToast("✅ Profile Saved locally!");
            });
        });
      });
    });
  }

  if (btnSaveSettings) {
    btnSaveSettings.addEventListener("click", () => {
      const userToken = getAuthToken();
      const backendUrl = (backendUrlInput.value || DEFAULT_API_BASE_URL).trim().replace(/\/+$/, "");
      API_BASE_URL = backendUrl;
      chrome.storage.local.set({ userToken, backendUrl }, () => {
        checkHealth();
        fetchUserInfo(userToken, true);
      });
    });
  }
});
