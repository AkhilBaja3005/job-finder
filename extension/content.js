// content.js - Job Finder ATS Tailor & AutoFill Content Script (v2.6.0)

(function () {
  function isRuntimeValid() {
    try {
      return typeof chrome !== "undefined" && !!chrome.runtime && !!chrome.runtime.id;
    } catch (e) {
      return false;
    }
  }

  if (!isRuntimeValid()) return;

  let isAutoRunning = false;
  let appliedCount = 0;
  let skippedCount = 0;

  function logMsg(msg) {
    console.log('[Job Finder ATS]', msg);
    try {
      if (isRuntimeValid() && chrome.storage && chrome.storage.local) {
        chrome.storage.local.get(['appLogs'], (items) => {
          const logs = items.appLogs || [];
          logs.push(`[${new Date().toLocaleTimeString()}] ${msg}`);
          if (logs.length > 50) logs.shift();
          chrome.storage.local.set({ appLogs: logs });
        });
      }
    } catch (e) {}
  }

  // ── oc-style Semantic DOM Distillation Engine ─────────────────────────
  function distillSemanticNode(node) {
    if (!node) return "";
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent.replace(/\s+/g, " ");
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return "";

    const tag = node.tagName.toLowerCase();
    if (["script", "style", "svg", "noscript", "iframe", "canvas", "header", "footer", "nav"].includes(tag)) {
      return "";
    }
    if (node.getAttribute("aria-hidden") === "true") return "";

    if (/^h[1-6]$/.test(tag)) {
      const level = parseInt(tag[1], 10);
      const text = node.innerText?.trim();
      return text ? `\n\n${"#".repeat(level)} ${text}\n` : "";
    }

    if (tag === "li") {
      const inner = Array.from(node.childNodes).map(distillSemanticNode).join("").trim();
      return inner ? `\n• ${inner}` : "";
    }
    if (tag === "ul" || tag === "ol") {
      return "\n" + Array.from(node.childNodes).map(distillSemanticNode).join("") + "\n";
    }

    if (tag === "p" || tag === "section" || tag === "article") {
      const inner = Array.from(node.childNodes).map(distillSemanticNode).join("").trim();
      return inner ? `\n\n${inner}\n` : "";
    }
    if (tag === "br") return "\n";

    return Array.from(node.childNodes).map(distillSemanticNode).join("");
  }

  function findMainContentElement() {
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

    if (url.includes("linkedin.com")) {
      title = (
        document.querySelector(".job-details-jobs-unified-top-card__job-title") ||
        document.querySelector(".jobs-unified-top-card__job-title") ||
        document.querySelector(".jobs-details__main-content h1") ||
        document.querySelector(".jobs-search__job-details--container h1") ||
        document.querySelector("h1")
      )?.innerText?.trim() || "";

      company = (
        document.querySelector(".job-details-jobs-unified-top-card__company-name a") ||
        document.querySelector(".job-details-jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-unified-top-card__subtitle-primary-grouping a") ||
        document.querySelector(".job-details-jobs-unified-top-card__primary-description a") ||
        document.querySelector(".jobs-search__job-details--container .job-details-jobs-unified-top-card__company-name") ||
        document.querySelector(".jobs-details__main-content a[href*='/company/']") ||
        document.querySelector(".job-details-jobs-unified-top-card a[href*='/company/']") ||
        document.querySelector(".jobs-unified-top-card a[href*='/company/']")
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

    const mainElem = findMainContentElement();
    description = distillSemanticNode(mainElem).replace(/\n{3,}/g, "\n\n").trim();
    if (!description || description.length < 50) {
      description = mainElem ? mainElem.innerText.trim() : (document.body ? document.body.innerText.slice(0, 5000) : "");
    }

    const invalidTitles = ["sign in", "log in", "login", "register", "apply now", "menu", "search", "indeed", "linkedin"];
    if (!title || invalidTitles.includes(title.toLowerCase())) {
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

    if (title) {
      if (title.includes(" - Single Position")) title = title.replace(" - Single Position", "");
      title = title.split(" | ")[0].split(" - Careers")[0].split(" at ")[0].trim();
    }
    if (!company && url) {
      if (url.includes("oraclecloud.com") || url.includes("myworkdayjobs.com") || url.includes("greenhouse.io") || url.includes("lever.co")) {
        const bodyText = document.body ? document.body.innerText : "";
        const brandMatch = bodyText.match(/(Goldman Sachs|Google|Amazon|Microsoft|Meta|Apple|Netflix|Micron|Oracle|JPMorgan|Bloomberg|Stripe|Uber|Airbnb|Coinbase|Palantir)/i);
        if (brandMatch) company = brandMatch[1];
      }
    }
    if (company && typeof company === "string") {
      company = company.trim().charAt(0).toUpperCase() + company.trim().slice(1);
    }

    return { title, company, description, url, pageSource: description };
  }

  // ── Native Form Value Setters (Framework Safe) ─────────────────────────
  function setNativeValue(element, value) {
    if (!element || value === undefined || value === null) return;
    const stringVal = String(value);
    if (!stringVal) return;

    const valueSetter = Object.getOwnPropertyDescriptor(element, 'value')?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;

    try { element.focus(); } catch (e) {}

    if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, stringVal);
    } else if (valueSetter) {
      valueSetter.call(element, stringVal);
    } else {
      element.value = stringVal;
    }

    try {
      element.dispatchEvent(new InputEvent('input', { bubbles: true, cancelable: true, inputType: 'insertText', data: stringVal }));
    } catch (e) {
      element.dispatchEvent(new Event('input', { bubbles: true }));
    }
    element.dispatchEvent(new Event('change', { bubbles: true }));
    element.dispatchEvent(new FocusEvent('blur', { bubbles: true }));
    element.setAttribute('data-jf-filled', 'true');
  }

  function setSelectValue(select, valueOrText) {
    if (!select || !valueOrText) return false;
    const options = Array.from(select.options);
    const lowerTarget = valueOrText.toLowerCase();

    const target = options.find(
      opt => opt.value.toLowerCase() === lowerTarget || 
             opt.text.toLowerCase().includes(lowerTarget) ||
             lowerTarget.includes(opt.text.toLowerCase())
    );

    if (target) {
      select.value = target.value;
      select.dispatchEvent(new Event('change', { bubbles: true }));
      select.dispatchEvent(new Event('blur', { bubbles: true }));
      select.setAttribute('data-jf-filled', 'true');
      return true;
    }
    return false;
  }

  function base64ToFile(base64String, filename, mimeType = "application/pdf") {
    try {
      const base64Data = base64String.includes(',') ? base64String.split(',')[1] : base64String;
      const binaryString = atob(base64Data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      return new File([bytes], filename, { type: mimeType });
    } catch (error) {
      return null;
    }
  }

  async function fillFileInput(fileInput, file) {
    try {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      fileInput.files = dataTransfer.files;
      fileInput.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    } catch (error) {
      return false;
    }
  }

  // ── Dedicated Portal Form Adapters ────────────────────────────────────
  function autofillGreenhouse(profile, eeo) {
    let count = 0;
    const selectors = {
      '#first_name': profile.firstName,
      '#last_name': profile.lastName,
      '#email': profile.email,
      '#phone': profile.phone,
      'input[name*="[first_name]"]': profile.firstName,
      'input[name*="[last_name]"]': profile.lastName,
      'input[name*="[email]"]': profile.email,
      'input[name*="[phone]"]': profile.phone,
      '#job_application_location': profile.location,
      'input[autocomplete="custom-question-linkedin"]': profile.linkedin,
      'input[autocomplete="custom-question-website"]': profile.portfolio || profile.github
    };

    for (const [sel, val] of Object.entries(selectors)) {
      if (!val) continue;
      const el = document.querySelector(sel);
      if (el && !el.value && el.offsetParent !== null) {
        setNativeValue(el, val);
        count++;
      }
    }
    return count;
  }

  function autofillLever(profile, eeo) {
    let count = 0;
    const mappings = [
      { selectors: ['input[name="name"]', 'input[name*="name"]'], val: `${profile.firstName} ${profile.lastName}`.trim() },
      { selectors: ['input[name="email"]', 'input[name*="email"]', 'input[type="email"]'], val: profile.email },
      { selectors: ['input[name="phone"]', 'input[name*="phone"]', 'input[type="tel"]'], val: profile.phone },
      { selectors: ['input[name*="LinkedIn"]', 'input[name*="linkedin"]'], val: profile.linkedin },
      { selectors: ['input[name*="GitHub"]', 'input[name*="github"]'], val: profile.github },
      { selectors: ['input[name*="Portfolio"]', 'input[name*="portfolio"]', 'input[name*="website"]'], val: profile.portfolio || profile.github }
    ];

    mappings.forEach(({ selectors, val }) => {
      if (!val) return;
      for (const sel of selectors) {
        const inp = document.querySelector(sel);
        if (inp && !inp.value && inp.offsetParent !== null) {
          setNativeValue(inp, val);
          count++;
          break;
        }
      }
    });
    return count;
  }

  function autofillWorkday(profile) {
    let count = 0;
    const fieldMap = {
      'legalNameSection_firstName': profile.firstName,
      'legalNameSection_lastName': profile.lastName,
      'addressSection_addressLine1': profile.location,
      'email': profile.email,
      'phone-number': profile.phone
    };

    for (const [automationId, val] of Object.entries(fieldMap)) {
      if (!val) continue;
      const inp = document.querySelector(`[data-automation-id="${automationId}"]`);
      if (inp && !inp.value && inp.offsetParent !== null) {
        setNativeValue(inp, val);
        count++;
      }
    }
    return count;
  }

  // ── Universal & Form Auto-fill Logic ──────────────────────────────────
  async function runAutofill() {
    chrome.storage.local.get(["userToken", "resumeData", "eeoProfile", "backendUrl"], async (storage) => {
      let resume = storage.resumeData || {};
      const token = (storage.userToken || "").trim();
      const baseUrl = (storage.backendUrl || "http://127.0.0.1:8000").replace(/\/+$/, '');

      if (!resume || !resume.name) {
        try {
          const resp = await fetch(`${baseUrl}/user/me`, {
            headers: { "Authorization": `Bearer ${token}`, "Accept": "application/json" }
          });
          if (resp.ok) {
            const userProfile = await resp.json();
            if (userProfile && (userProfile.resume_data || userProfile.data)) {
              resume = userProfile.resume_data || userProfile.data;
              chrome.storage.local.set({ resumeData: resume });
            }
          }
        } catch (err) {}
      }

      const eeo = storage.eeoProfile || { workAuth: "Yes", sponsorship: "No" };
      const fullName = resume.name || "";
      const nameParts = fullName.trim().split(/\s+/);
      const firstName = nameParts[0] || "";
      const lastName = nameParts.slice(1).join(" ") || "";
      const email = resume.email || "";
      const phone = resume.phone || "";
      const location = resume.location || "";
      const summary = resume.summary || "";
      const links = Array.isArray(resume.links) ? resume.links : [];
      const linkedin = links.find(l => l.toLowerCase().includes("linkedin")) || resume.linkedin || "";
      const github = links.find(l => l.toLowerCase().includes("github")) || resume.github || "";
      const portfolio = links.find(l => !l.toLowerCase().includes("linkedin") && !l.toLowerCase().includes("github")) || resume.portfolio || "";

      const profileObj = { firstName, lastName, email, phone, location, linkedin, github, portfolio, summary };

      const url = window.location.href;
      let filledCount = 0;

      if (url.includes('greenhouse.io')) filledCount += autofillGreenhouse(profileObj, eeo);
      else if (url.includes('lever.co')) filledCount += autofillLever(profileObj, eeo);
      else if (url.includes('workday') || url.includes('myworkdayjobs.com')) filledCount += autofillWorkday(profileObj);

      const modal = document.querySelector(
        ".jobs-easy-apply-modal, .artdeco-modal, [data-test-modal], [role='dialog'], .application-container, .ia-BasePage"
      );
      const scope = modal || document;

      // File attachment
      if (resume.pdf_base64) {
        const fileInputs = scope.querySelectorAll("input[type='file']");
        const pdfFile = base64ToFile(resume.pdf_base64, `${firstName || 'Candidate'}_Resume.pdf`);
        if (pdfFile) {
          for (const fi of fileInputs) {
            if (!fi.getAttribute("data-jf-filled")) {
              await fillFileInput(fi, pdfFile);
              fi.setAttribute("data-jf-filled", "true");
              filledCount++;
            }
          }
        }
      }

      // Universal Input Scan
      const inputs = scope.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']), textarea, select"
      );

      for (const inp of inputs) {
        if (!inp.offsetParent || inp.getAttribute("data-jf-filled") || inp.disabled || inp.readOnly) continue;

        const id = (inp.id || "").toLowerCase();
        const nameAttr = (inp.name || "").toLowerCase();
        const placeholder = (inp.placeholder || "").toLowerCase();
        const ariaLabel = (inp.getAttribute("aria-label") || "").toLowerCase();
        const dataAutomationId = (inp.getAttribute("data-automation-id") || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();
        const labelText = (inp.closest("div,li,fieldset,tr,td,.form-group,.fb-form-element")?.innerText || "").slice(0, 150).toLowerCase();
        const key = `${id} ${nameAttr} ${placeholder} ${ariaLabel} ${dataAutomationId} ${labelText} ${type}`;

        let val = null;
        if (/first.?name|given.?name|firstname|fname/.test(key)) val = firstName;
        else if (/last.?name|family.?name|lastname|lname|surname/.test(key)) val = lastName;
        else if (/email|e-mail|emailaddress/.test(key) || type === "email") val = email;
        else if (/phone|mobile|cell|tel|phonenumber/.test(key) || type === "tel") val = phone;
        else if (/linkedin/.test(key)) val = linkedin;
        else if (/github/.test(key)) val = github;
        else if (/portfolio|website/.test(key)) val = portfolio || github;
        else if (/city|location|address/.test(key)) val = location;
        else if (/summary|cover.?letter|about you|additional info/.test(key)) val = summary;
        else if (/authorized|work in the us|work authorization|legally authorized/.test(key)) val = eeo.workAuth || "Yes";
        else if (/sponsor|visa|require.*sponsorship/.test(key)) val = eeo.sponsorship || "No";

        if (!val) continue;

        try {
          if (inp.tagName === "SELECT") {
            setSelectValue(inp, val);
          } else {
            setNativeValue(inp, val);
          }
          inp.style.outline = "2px solid #38bdf8";
          filledCount++;
        } catch (e) {}
      }

      logMsg(`⚡ Auto-filled ${filledCount} field${filledCount !== 1 ? "s" : ""}.`);
      showToast(`⚡ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""}!`);
    });
  }

  function showToast(msg) {
    const existing = document.getElementById("jf-toast");
    if (existing) existing.remove();
    const toast = document.createElement("div");
    toast.id = "jf-toast";
    Object.assign(toast.style, {
      position: "fixed", bottom: "90px", right: "20px",
      background: "rgba(15,23,42,0.95)", color: "#38bdf8",
      border: "1px solid rgba(56,189,248,0.4)", borderRadius: "10px",
      padding: "10px 18px", fontSize: "13px", fontWeight: "700",
      zIndex: "2147483647", boxShadow: "0 8px 30px rgba(0,0,0,0.4)",
      fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    });
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; }, 2500);
    setTimeout(() => toast.remove(), 3000);
  }

  // ── Message Listener ──────────────────────────────────────────────────
  try {
    if (isRuntimeValid() && chrome.runtime.onMessage) {
      chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        try {
          if (!isRuntimeValid()) return false;
          if (request.action === "GET_JOB_DETAILS") {
            const details = extractJobDetails();
            sendResponse(details);
          } else if (request.action === "TRIGGER_AUTOFILL") {
            runAutofill();
            sendResponse({ status: "ok" });
          } else if (request.action === "TOGGLE_BATCH_AUTO") {
            isAutoRunning = request.state;
            logMsg(isAutoRunning ? "▶️ Batch Auto-Apply STARTED" : "⏸️ Batch Auto-Apply STOPPED");
            sendResponse({ status: "ok", isAutoRunning });
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
