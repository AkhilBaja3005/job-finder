// content.js - Job Finder ATS Tailor Content Script (v2.5.0 Failsafe)

(function () {
  // Allow content script execution on web application origins for 1-Click Extension Auto-Sync

  function isRuntimeValid() {
    try {
      return typeof chrome !== "undefined" && !!chrome.runtime && !!chrome.runtime.id;
    } catch (e) {
      return false;
    }
  }

  if (!isRuntimeValid()) return;

  function extractJobDetails() {
    const url = window.location.href;
    let title = "";
    let company = "";
    let description = "";

    if (url.includes("linkedin.com")) {
      title = (
        document.querySelector(".job-details-jobs-unified-top-card__job-title") ||
        document.querySelector(".jobs-unified-top-card__job-title") ||
        document.querySelector(".jobs-search__job-details--container h1") ||
        document.querySelector("h1")
      )?.innerText?.trim() || "";

      company = (
        document.querySelector(".job-details-jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-unified-top-card__subtitle-primary-grouping a") ||
        document.querySelector(".job-details-jobs-unified-top-card__primary-description a") ||
        document.querySelector(".jobs-search__job-details--container .job-details-jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-unified-top-card__primary-description") ||
        document.querySelector("a[href*='/company/']")
      )?.innerText?.trim() || "";

      description = (
        document.querySelector("#job-details") ||
        document.querySelector(".jobs-description__content") ||
        document.querySelector(".jobs-box__html-content") ||
        document.querySelector(".jobs-description")
      )?.innerText?.trim() || "";
    } else if (url.includes("indeed.com")) {
      title = document.querySelector(".jobsearch-JobInfoHeader-title, h1.jobsearch-JobInfoHeader-title")?.innerText?.trim() || "";
      company = document.querySelector("[data-company-name='true'], .jobsearch-InlineCompanyRating-companyHeader")?.innerText?.trim() || "";
      description = document.querySelector("#jobDescriptionText")?.innerText?.trim() || "";
    } else if (url.includes("workday") || url.includes("myworkdayjobs.com")) {
      title = document.querySelector("[data-automation-id='jobPostingHeader'], h2")?.innerText?.trim() || "";
      description = document.querySelector("[data-automation-id='jobPostingDescription']")?.innerText?.trim() || "";
    } else {
      // Oracle Cloud HCM / Enterprise ATS specific selectors
      const oracleTitle = document.querySelector(".job-details-title, h1, [data-ph-at-id='job-title']")?.innerText?.trim();
      const oracleCompany = (
        document.querySelector(".org-name, .company-name, [data-ph-at-id='company-name']") ||
        document.querySelector("meta[property='og:site_name']")
      )?.content || document.querySelector(".org-name, .company-name")?.innerText?.trim();

      title = oracleTitle || document.title;
      company = oracleCompany || "";

      description = (
        document.querySelector(".job-description, #job-description, [data-ph-at-id='job-description'], .job-details-description") ||
        document.querySelector("main")
      )?.innerText || document.body.innerText.slice(0, 4000);
    }

    // Intelligent Job Title Cleaning
    if (title) {
      // If page title is "Senior Engineer - Single Position | Micron", extract "Senior Engineer"
      if (title.includes(" - Single Position")) {
        title = title.replace(" - Single Position", "");
      }
      title = title.split(" | ")[0].split(" - Careers")[0].trim();
    }
    if (!company && url) {
      if (url.includes("oraclecloud.com") || url.includes("myworkdayjobs.com")) {
        // Look for company branding inside DOM body text (e.g. Goldman Sachs)
        const bodyText = document.body.innerText;
        const brandMatch = bodyText.match(/(Goldman Sachs|Google|Amazon|Microsoft|Meta|Apple|Netflix|Micron|Oracle|JPMorgan)/i);
        if (brandMatch) {
          company = brandMatch[1];
        }
      }
    }
    if (company && typeof company === "string") {
      company = company.trim().charAt(0).toUpperCase() + company.trim().slice(1);
    }

    const pageSource = document.body ? document.body.innerText.slice(0, 15000) : description;
    return { title, company, description, url, pageSource };
  }

  try {
    if (isRuntimeValid() && chrome.runtime.onMessage) {
      chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        try {
          if (!isRuntimeValid()) return false;
          if (request.action === "GET_JOB_DETAILS") {
            const details = extractJobDetails();
            sendResponse(details);
          }
        } catch (e) {}
        return true;
      });
    }
  } catch (e) {}

  // Relay 1-Click Sync Key from web application window to extension storage
  window.addEventListener("message", (event) => {
    try {
      if (event.data && event.data.type === "SYNC_JOB_FINDER_KEY" && event.data.syncKey) {
        if (isRuntimeValid() && chrome.storage && chrome.storage.local) {
          chrome.storage.local.set({ userToken: event.data.syncKey }, () => {
            if (chrome.runtime.lastError) return;
            window.postMessage({ type: "SYNC_JOB_FINDER_KEY_SUCCESS", syncKey: event.data.syncKey }, "*");
          });
        }
      }
    } catch (e) {}
  });
})();
