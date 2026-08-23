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

  // ── oc-style Semantic DOM Distillation Engine ─────────────────────────
  function distillSemanticNode(node) {
    if (!node) return "";
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent.replace(/\s+/g, " ");
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.tagName.toLowerCase();
    // Strip non-content / boilerplate tags
    if (["script", "style", "svg", "noscript", "iframe", "canvas", "header", "footer", "nav"].includes(tag)) {
      return "";
    }
    if (node.getAttribute("aria-hidden") === "true") return "";

    // Headings
    if (/^h[1-6]$/.test(tag)) {
      const level = parseInt(tag[1], 10);
      const text = node.innerText?.trim();
      return text ? `\n\n${"#".repeat(level)} ${text}\n` : "";
    }

    // List items
    if (tag === "li") {
      const inner = Array.from(node.childNodes).map(distillSemanticNode).join("").trim();
      return inner ? `\n• ${inner}` : "";
    }
    if (tag === "ul" || tag === "ol") {
      return "\n" + Array.from(node.childNodes).map(distillSemanticNode).join("") + "\n";
    }

    // Paragraphs and divisions
    if (tag === "p" || tag === "section" || tag === "article") {
      const inner = Array.from(node.childNodes).map(distillSemanticNode).join("").trim();
      return inner ? `\n\n${inner}\n` : "";
    }
    if (tag === "br") return "\n";

    return Array.from(node.childNodes).map(distillSemanticNode).join("");
  }

  function findMainContentElement() {
    // 1. Try explicit ATS semantic containers
    const explicitContainers = [
      "#job-details",
      ".jobs-description__content",
      ".jobs-box__html-content",
      "#jobDescriptionText",
      "[data-automation-id='jobPostingDescription']",
      "[data-ph-at-id='job-description']",
      ".job-description",
      ".job-details-description",
      "article.job-description",
      "[role='main']",
      "main",
      "article"
    ];
    for (const selector of explicitContainers) {
      const elem = document.querySelector(selector);
      if (elem && elem.innerText && elem.innerText.trim().length > 150) {
        return elem;
      }
    }
    // 2. Fallback: Score elements by text density
    let bestElem = document.body;
    let maxScore = 0;
    const candidates = document.querySelectorAll("div, section, article");
    candidates.forEach(el => {
      const text = el.innerText || "";
      const len = text.length;
      if (len > 300 && len < 25000) {
        const pCount = el.querySelectorAll("p, li").length;
        const score = len * (1 + pCount * 0.1);
        if (score > maxScore) {
          maxScore = score;
          bestElem = el;
        }
      }
    });
    return bestElem;
  }

  function extractJobDetails() {
    const url = window.location.href;
    let title = "";
    let company = "";
    let description = "";

    // Fast-path known ATS selectors
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
    } else if (url.includes("indeed.com")) {
      title = (
        document.querySelector(".jobsearch-JobInfoHeader-title") ||
        document.querySelector("h1.jobsearch-JobInfoHeader-title") ||
        document.querySelector("[data-testid='jobsearch-JobInfoHeader-title']") ||
        document.querySelector("h2.jobsearch-JobInfoHeader-title")
      )?.innerText?.trim() || "";
      company = (
        document.querySelector("[data-company-name='true']") ||
        document.querySelector("[data-testid='inlineHeader-companyName']") ||
        document.querySelector(".jobsearch-InlineCompanyRating-companyHeader")
      )?.innerText?.trim() || "";
    } else if (url.includes("workday") || url.includes("myworkdayjobs.com")) {
      title = document.querySelector("[data-automation-id='jobPostingHeader'], h2, h1")?.innerText?.trim() || "";
    } else {
      title = (
        document.querySelector(".job-details-title, [data-ph-at-id='job-title']") ||
        document.querySelector("h1")
      )?.innerText?.trim() || "";
      company = (
        document.querySelector(".org-name, .company-name, [data-ph-at-id='company-name']") ||
        document.querySelector("meta[property='og:site_name']")
      )?.content || document.querySelector(".org-name, .company-name")?.innerText?.trim() || "";
    }

    // Run oc-style Semantic Distillation to extract clean markdown JD
    const mainElem = findMainContentElement();
    description = distillSemanticNode(mainElem).replace(/\n{3,}/g, "\n\n").trim();
    if (!description || description.length < 50) {
      // oc fallback: grab visible text directly from candidate body
      description = mainElem ? mainElem.innerText.trim() : (document.body ? document.body.innerText.slice(0, 5000) : "");
    }

    // Filter out invalid "Sign In" / "Log In" / generic button text falsely captured as title
    const invalidTitles = ["sign in", "log in", "login", "register", "apply now", "menu", "search", "indeed", "linkedin"];
    if (!title || invalidTitles.includes(title.toLowerCase())) {
      // Try extracting title from document.title or first markdown heading
      const docTitle = document.title || "";
      const cleanedDocTitle = docTitle.split(" - ")[0].split(" | ")[0].split(" at ")[0].trim();
      if (cleanedDocTitle && !invalidTitles.includes(cleanedDocTitle.toLowerCase())) {
        title = cleanedDocTitle;
      } else {
        const hMatch = description.match(/^#\s+(.+)$/m);
        if (hMatch && !invalidTitles.includes(hMatch[1].trim().toLowerCase())) {
          title = hMatch[1].trim();
        }
      }
    }

    // Intelligent Job Title & Company Cleaning
    if (title) {
      if (title.includes(" - Single Position")) {
        title = title.replace(" - Single Position", "");
      }
      title = title.split(" | ")[0].split(" - Careers")[0].split(" at ")[0].trim();
    }
    if (!company && url) {
      if (url.includes("oraclecloud.com") || url.includes("myworkdayjobs.com") || url.includes("greenhouse.io") || url.includes("lever.co")) {
        const bodyText = document.body ? document.body.innerText : "";
        const brandMatch = bodyText.match(/(Goldman Sachs|Google|Amazon|Microsoft|Meta|Apple|Netflix|Micron|Oracle|JPMorgan|Bloomberg|Stripe|Uber|Airbnb|Coinbase|Palantir)/i);
        if (brandMatch) {
          company = brandMatch[1];
        }
      }
    }
    if (company && typeof company === "string") {
      company = company.trim().charAt(0).toUpperCase() + company.trim().slice(1);
    }

    const pageSource = description;
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
