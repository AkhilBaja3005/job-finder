// content.js - Job Finder ATS Tailor & Multimodal AI AutoFill Content Script (v3.4.0)

(function () {
  function isRuntimeValid() {
    try {
      return typeof chrome !== "undefined" && !!chrome.runtime && !!chrome.runtime.id;
    } catch (e) {
      return false;
    }
  }

  if (!isRuntimeValid()) return;

  function logMsg(msg) {
    console.log("[Job Finder ATS AI]", msg);
    try {
      if (isRuntimeValid() && chrome.storage && chrome.storage.local) {
        chrome.storage.local.get(["appLogs"], (items) => {
          const logs = items.appLogs || [];
          logs.push(`[${new Date().toLocaleTimeString()}] ${msg}`);
          if (logs.length > 50) logs.shift();
          chrome.storage.local.set({ appLogs: logs });
        });
      }
    } catch (e) {}
  }

  // ── Semantic DOM Distillation Engine ──────────────────────────────────
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
    candidates.forEach((el) => {
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
    } else if (url.includes("ashbyhq.com")) {
      title = (
        document.querySelector("h1, [class*='jobPostingTitle'], [class*='JobTitle']")
      )?.innerText?.trim() || "";
      const pathParts = window.location.pathname.split("/").filter(Boolean);
      const slug = pathParts[0] || "";
      const metaSite = document.querySelector("meta[property='og:site_name'], meta[name='author']")?.content;
      company = (
        document.querySelector("[class*='companyName'], [class*='CompanyName'], [data-testid='company-name']")?.innerText?.trim() ||
        (metaSite && !metaSite.toLowerCase().includes("ashby") ? metaSite : "") ||
        slug.replace(/[-_]/g, ' ')
      );
      const ashbyDesc = document.querySelector("[class*='jobPostingDescription'], [class*='JobPostingDescription'], [class*='description__'], [data-testid='job-description'], .ashby-job-posting-description");
      if (ashbyDesc && ashbyDesc.innerText.trim().length > 100) {
        description = distillSemanticNode(ashbyDesc);
      }
    } else if (url.includes("greenhouse.io") || url.includes("gh_jid=")) {
      title = document.querySelector("h1.app-title, .job-title, h1")?.innerText?.trim() || "";
      const slug = window.location.pathname.split("/").filter(Boolean)[0] || "";
      company = document.querySelector(".company-name, #header .company-name, .logo a")?.innerText?.trim() || document.querySelector("meta[property='og:site_name']")?.content || slug.replace(/[-_]/g, ' ');
      const ghDesc = document.querySelector("#content, #job_description, .job-description");
      if (ghDesc && ghDesc.innerText.trim().length > 100) description = distillSemanticNode(ghDesc);
    } else if (url.includes("lever.co")) {
      title = document.querySelector(".posting-headline h2, h2, h1")?.innerText?.trim() || "";
      const slug = window.location.pathname.split("/").filter(Boolean)[0] || "";
      company = document.querySelector(".main-header-logo, .company-name")?.innerText?.trim() || slug.replace(/[-_]/g, ' ');
      const levDesc = document.querySelector(".posting-page-content, .section-wrapper, .content");
      if (levDesc && levDesc.innerText.trim().length > 100) description = distillSemanticNode(levDesc);
    } else if (url.includes("workday") || url.includes("myworkdayjobs.com")) {
      title = document.querySelector("[data-automation-id='jobPostingHeader'], h2, h1")?.innerText?.trim() || "";
      company = document.querySelector("[data-automation-id='companyName'], .company-name, meta[property='og:site_name']")?.content || window.location.hostname.split(".")[0].replace(/[-_]/g, ' ');
      const wdDesc = document.querySelector("[data-automation-id='jobPostingDescription']");
      if (wdDesc && wdDesc.innerText.trim().length > 100) description = distillSemanticNode(wdDesc);
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

    if (!description || description.length < 50) {
      const mainElem = findMainContentElement();
      description = distillSemanticNode(mainElem).replace(/\n{3,}/g, "\n\n").trim();
      if (!description || description.length < 50) {
        description = mainElem ? mainElem.innerText.trim() : (document.body ? document.body.innerText.slice(0, 5000) : "");
      }
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
    
    // Clean company name
    if (company && typeof company === "string") {
      company = company.replace(/^https?:\/\//i, "").replace(/^www\./i, "").replace(/\.(ashbyhq|greenhouse|lever|myworkdayjobs|workday|smartrecruiters)\.com/i, "").trim();
      if (["jobs.ashbyhq", "ashby", "greenhouse", "lever", "workday", "smartrecruiters", "indeed", "linkedin"].includes(company.toLowerCase())) {
        const pathParts = window.location.pathname.split("/").filter(Boolean);
        company = pathParts[0] ? pathParts[0].replace(/[-_]/g, ' ') : "";
      }
      if (company) {
        company = company.split(" ").map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");
      }
    }

    if (!company && url) {
      const bodyText = document.body ? document.body.innerText : "";
      const brandMatch = bodyText.match(/(Trainline|Granola|Goldman Sachs|Google|Amazon|Microsoft|Meta|Apple|Netflix|Micron|Oracle|JPMorgan|Bloomberg|Stripe|Uber|Airbnb|Coinbase|Palantir)/i);
      if (brandMatch) company = brandMatch[1];
    }

    return { title, company, description, url, pageSource: description };
  }

  // ── Native Form Value Setters (Framework Safe: React 18/19, Vue, Svelte) ───
  function setNativeValue(element, value) {
    if (!element || value === undefined || value === null) return;
    let cleanVal = String(value).trim();
    if (!cleanVal || cleanVal.toLowerCase() === "undefined" || cleanVal.toLowerCase() === "null" || cleanVal === "NaN" || cleanVal.toLowerCase() === "nan") return;

    if (element.getAttribute("contenteditable") === "true") {
      try {
        element.focus();
        element.innerText = cleanVal;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
        element.setAttribute("data-jf-filled", "true");
      } catch (e) {}
      return;
    }

    const type = (element.type || "").toLowerCase();
    if (type === "number" || type === "range") {
      const numMatch = cleanVal.match(/-?\d+(\.\d+)?/);
      if (!numMatch) return;
      cleanVal = numMatch[0];
    } else if (type === "date" || type === "month" || type === "time") {
      if (!cleanVal.match(/^\d{4}-\d{2}/) && !cleanVal.match(/^\d{2}:\d{2}/)) return;
    }

    const valueSetter = Object.getOwnPropertyDescriptor(element, "value")?.set;
    const prototype = Object.getPrototypeOf(element);
    const prototypeValueSetter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;

    try { element.focus(); } catch (e) {}

    if (prototypeValueSetter && valueSetter !== prototypeValueSetter) {
      prototypeValueSetter.call(element, cleanVal);
    } else if (valueSetter) {
      valueSetter.call(element, cleanVal);
    } else {
      element.value = cleanVal;
    }

    try {
      element.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "insertText", data: cleanVal }));
    } catch (e) {
      element.dispatchEvent(new Event("input", { bubbles: true }));
    }
    element.dispatchEvent(new Event("change", { bubbles: true }));
    element.dispatchEvent(new FocusEvent("blur", { bubbles: true }));
    element.setAttribute("data-jf-filled", "true");
  }

  function setSelectValue(select, valueOrText) {
    if (!select || !valueOrText) return false;
    const options = Array.from(select.options);
    const lowerTarget = String(valueOrText).toLowerCase();

    const target = options.find(
      (opt) =>
        opt.value.toLowerCase() === lowerTarget ||
        opt.text.toLowerCase().includes(lowerTarget) ||
        lowerTarget.includes(opt.text.toLowerCase())
    );

    if (target) {
      select.value = target.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      select.dispatchEvent(new Event("blur", { bubbles: true }));
      select.setAttribute("data-jf-filled", "true");
      return true;
    }
    return false;
  }

  function base64ToFile(base64String, filename, mimeType = "application/pdf") {
    try {
      const base64Data = base64String.includes(",") ? base64String.split(",")[1] : base64String;
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
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch (error) {
      return false;
    }
  }

  // ── Extract Exact Question Prompt Text for Any Form Element ────────────
  // ── Extract Exact Question Prompt Text for Any Form Element ────────────
  function getQuestionTextForElement(el) {
    if (!el) return "";

    // 1. Direct label reference via 'for' attribute
    if (el.id) {
      const explicitLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (explicitLabel) {
        const txt = explicitLabel.innerText?.trim();
        if (txt && txt.length > 1) return txt;
      }
    }

    // 2. Direct aria-labelledby reference (Ashby, React ARIA, Workday)
    const labelledById = el.getAttribute("aria-labelledby");
    if (labelledById) {
      const lbl = document.getElementById(labelledById);
      if (lbl) {
        const txt = lbl.innerText?.trim();
        if (txt && txt.length > 1) return txt;
      }
    }

    // 3. Direct parent label
    const immediateLabel = el.closest("label");
    if (immediateLabel) {
      const clone = immediateLabel.cloneNode(true);
      clone.querySelectorAll("input, textarea, select, button, script, style").forEach((c) => c.remove());
      const txt = clone.textContent?.trim();
      if (txt && txt.length > 1) return txt;
    }

    // 4. Closest tightly-scoped form block (Ashby, Greenhouse, Lever, Workday)
    const tightBlock = el.closest(
      '[class*="field"], [class*="formField"], [class*="formSection"], [class*="question"], [class*="Container"], [class*="form-group"], [data-testid*="field"], [data-testid*="form"], fieldset, tr, li'
    );
    if (tightBlock) {
      const heading = tightBlock.querySelector(
        'label, [class*="label"], [class*="title"], [class*="prompt"], [class*="heading"], [data-testid*="label"], legend, h3, h4, h5, h6'
      );
      if (heading && heading !== el) {
        const clone = heading.cloneNode(true);
        clone.querySelectorAll("input, textarea, select, button, script, style").forEach((c) => c.remove());
        const txt = clone.textContent?.trim();
        if (txt && txt.length > 1) return txt;
      }
    }

    // 5. Walk ancestors up to 5 levels to find any preceding label or heading
    let ancestor = el.parentElement;
    for (let i = 0; i < 5 && ancestor && ancestor !== document.body; i++) {
      const foundLabel = ancestor.querySelector('label, [class*="label"], [class*="title"], [class*="prompt"], [class*="heading"], legend, h3, h4, h5');
      if (foundLabel && foundLabel !== el && !foundLabel.contains(el)) {
        const clone = foundLabel.cloneNode(true);
        clone.querySelectorAll("input, textarea, select, button, script, style").forEach((c) => c.remove());
        const txt = clone.textContent?.trim();
        if (txt && txt.length > 1) return txt;
      }
      ancestor = ancestor.parentElement;
    }

    // 6. Preceding sibling element
    const prev = el.previousElementSibling;
    if (prev && ["LABEL", "H3", "H4", "H5", "P", "SPAN", "DIV"].includes(prev.tagName)) {
      const txt = prev.innerText?.trim();
      if (txt && txt.length > 1 && txt.length < 200) return txt;
    }

    // 7. aria-label attribute
    const ariaLabel = el.getAttribute("aria-label")?.trim();
    if (ariaLabel && ariaLabel.length > 1) return ariaLabel;

    // 8. Filtered placeholder fallback (ignore generic input prompts)
    const ph = (el.getAttribute("placeholder") || "").trim();
    const isGenericPrompt = /^(start\s*typing|type\s*here|enter\s*text|search|select|choose|optional|e\.g\.|write|answer|n\/a|\.\.\.)/i.test(ph);
    if (ph && !isGenericPrompt && ph.length > 1) return ph;

    return "";
  }

  // ── Click Yes / No Option on Button Cards or Radio Elements ───────────
  function clickChoiceInContainer(container, targetChoice) {
    if (!container || !targetChoice) return false;
    const lowerChoice = targetChoice.toLowerCase();

    // Check if the container already has any checked radio or active choice selected by the user
    const alreadyCheckedRadio = container.querySelector("input[type='radio']:checked");
    if (alreadyCheckedRadio) return false;

    const alreadyActiveChoice = container.querySelector("[aria-checked='true'], [aria-selected='true'], [class*='selected'], [class*='active']:not(body):not(html)");
    if (alreadyActiveChoice) return false;

    // 1. Radio Inputs
    const radios = container.querySelectorAll("input[type='radio']");
    for (const radio of radios) {
      const label = radio.closest("label")?.innerText?.toLowerCase() || radio.value.toLowerCase();
      if (label.includes(lowerChoice) || (lowerChoice === "yes" && label.includes("authorized")) || (lowerChoice === "no" && label.includes("no"))) {
        if (!radio.checked) {
          radio.click();
          radio.dispatchEvent(new Event("change", { bubbles: true }));
          radio.setAttribute("data-jf-filled", "true");
          return true;
        }
      }
    }

    // 2. Button Cards / Div Options (Ashby, Greenhouse cards)
    const buttons = Array.from(container.querySelectorAll("button, [role='radio'], [role='button'], [class*='option'], [class*='choice'], label, div"));
    for (const btn of buttons) {
      const txt = (btn.innerText || "").trim().toLowerCase();
      if (txt === lowerChoice || txt === `${lowerChoice}\n` || (lowerChoice === "yes" && txt.startsWith("yes")) || (lowerChoice === "no" && txt.startsWith("no"))) {
        if (!btn.classList.contains("active") && !btn.getAttribute("aria-checked")) {
          btn.click();
          btn.setAttribute("data-jf-filled", "true");
          return true;
        }
      }
    }
    return false;
  }

  // ── AI Answer Generator (Calls Backend /answer_question LLM Agent) ──────
  async function generateAIAnswer(question, profile, jobInfo, baseUrl, token) {
    const qLower = (question || "").toLowerCase();

    const customNotice = (profile && (profile.notice_period || profile.noticePeriod)) || "";
    const customSalary = (profile && (profile.salary_expectations || profile.salary)) || "";
    const customLocation = (profile && (profile.location || profile.personal?.location)) || "";
    const customPortfolio = (profile && (profile.portfolio || profile.personal?.portfolio)) || "";
    const customLinkedin = (profile && (profile.linkedin || profile.personal?.linkedin)) || "";
    const customGithub = (profile && (profile.github || profile.personal?.github)) || "";

    // Deterministic short-answers using user profile preference
    if (qLower.includes("notice") || qLower.includes("how soon") || qLower.includes("start date")) {
      return customNotice || "Available immediately";
    }
    if (qLower.includes("hear about") || qLower.includes("referred") || qLower.includes("source") || qLower.includes("where did you find")) {
      return "LinkedIn";
    }
    if (qLower.includes("salary") || qLower.includes("compensation") || qLower.includes("expectation")) {
      return customSalary || "Competitive market rate / Open to discuss based on role scope.";
    }
    if (qLower.includes("located") || qLower.includes("location") || qLower.includes("where are you") || qLower.includes("where do you live") || qLower.includes("current address") || qLower.includes("city") || qLower.includes("country")) {
      return customLocation || "London, United Kingdom / Open to relocation";
    }
    if (qLower.includes("portfolio") || qLower.includes("website") || qLower.includes("personal site")) {
      return customPortfolio || "";
    }
    if (qLower.includes("linkedin")) {
      return customLinkedin || "https://linkedin.com/in/akhilbaja";
    }
    if (qLower.includes("github")) {
      return customGithub || "https://github.com/AkhilBaja3005";
    }
    if (qLower.includes("authorized") || qLower.includes("authorization") || qLower.includes("eligible to work") || qLower.includes("legal right")) {
      return "Yes";
    }
    if (qLower.includes("require sponsor") || (qLower.includes("sponsorship") && !qLower.includes("will you require"))) {
      return "No";
    }
    if (qLower.includes("relocate") || qLower.includes("hybrid") || qLower.includes("on-site") || qLower.includes("office") || qLower.includes("commute")) {
      return "Yes, comfortable working on-site / hybrid and open to relocation as required.";
    }
    if (qLower.includes("background check") || qLower.includes("drug test") || qLower.includes("18 years") || qLower.includes("age of 18")) {
      return "Yes";
    }
    if (qLower.includes("worked here") || qLower.includes("former employee") || qLower.includes("previously employed") || qLower.includes("non-compete")) {
      return "No";
    }

    console.log(`%c[Job Finder AI] ❓ Extracted Question: "${question}"`, "color: #38bdf8; font-weight: bold;");

    try {
      const res = await fetch(`${baseUrl}/answer_question`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
          "Authorization": `Bearer ${token || "guest"}`
        },
        body: JSON.stringify({
          question: question || "Brief summary of experience",
          company_name: jobInfo.company || "Target Company",
          job_title: jobInfo.title || "AI Engineer",
          candidate_profile: profile
        })
      });
      if (res.ok) {
        const data = await res.json();
        if (data.answer) {
          console.log(`%c[Job Finder AI] 💡 Generated Answer: "${data.answer}"`, "color: #34d399; font-weight: bold;");
          return data.answer;
        }
      }
    } catch (e) {
      console.warn("[Job Finder AI] Backend answer_question request error:", e);
    }

    // Smart Fallback Heuristic
    let fallbackAns = "";
    if (qLower.includes("one line") || qLower.includes("one-line") || qLower.includes("condensed")) {
      fallbackAns = "AI Systems Engineer with 3+ years experience building production-grade GenAI pipelines and scalable LLM applications.";
    } else if (qLower.includes("why")) {
      const company = jobInfo.company || "Granola";
      fallbackAns = `I want to join ${company} because of your focus on transforming meeting workflows with intuitive, high-velocity AI. With my experience in production LLM pipelines and low-latency retrieval systems, I am excited to contribute directly to advancing your product capabilities.`;
    } else {
      fallbackAns = `Excited to bring my technical experience in AI engineering and scalable systems to ${jobInfo.company || "the team"}.`;
    }
    console.log(`%c[Job Finder AI] 💡 Fallback Answer: "${fallbackAns}"`, "color: #facc15; font-weight: bold;");
    return fallbackAns;
  }

  // ── Smart Career Page Detector ────────────────────────────────────────
  function isJobOrCareerPage() {
    const href = window.location.href.toLowerCase();
    const hostname = window.location.hostname.toLowerCase();

    // 1. Known ATS & Hiring Portals
    const atsDomains = [
      "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workday.com",
      "smartrecruiters.com", "icims.com", "taleo.net", "bamboohr.com", "jobvite.com",
      "ziprecruiter.com", "indeed.com", "wellfound.com", "angel.co", "workable.com",
      "rippling.com", "phenom.com", "eightfold.ai", "jazzhr.com", "recruitee.com",
      "breezy.hr", "applytojob.com", "pinpointhq.com", "homerun.co", "teamtailor.com",
      "withwaymo.com", "waymo.com", "otta.com", "glassdoor.com", "monster.com"
    ];
    if (atsDomains.some((d) => hostname.includes(d))) return true;

    // 2. Career subdomains & specific URL paths
    if (hostname.startsWith("careers.") || hostname.startsWith("jobs.") || hostname.includes("careers") || hostname.includes("jobs")) return true;
    if (
      href.includes("/jobs/") || href.includes("/job/") ||
      href.includes("/careers/") || href.includes("/career/") ||
      href.includes("/openings/") || href.includes("/positions/") ||
      href.includes("/apply") || href.includes("/application") ||
      href.includes("gh_jid=") || href.includes("jobid=") ||
      href.includes("/join-us") || href.includes("/work-with-us")
    ) return true;

    if (hostname.includes("linkedin.com") && (href.includes("/jobs/") || href.includes("/job-apply/"))) return true;

    // 3. Application Form DOM Presence
    const hasJobAppDom = document.querySelector(
      "[class*='easy-apply'], [class*='apply-form'], [class*='application-form'], [data-automation-id*='job'], [data-ph-at-id*='job'], #job-details, #jobDescriptionText, [class*='jobDescription'], form[action*='apply'], form[action*='job']"
    );
    if (hasJobAppDom) return true;

    // 4. Presence of Resume upload inputs
    const hasResumeUpload = document.querySelector(
      "input[type='file'][accept*='pdf'], input[type='file'][name*='resume'], input[type='file'][id*='resume'], input[type='file'][aria-label*='resume']"
    );
    if (hasResumeUpload) return true;

    return false;
  }

  // ── Inject Inline "✨ AI Answer" Buttons Beside Question Boxes ────────
  function injectInlineAIButtons() {
    if (!isJobOrCareerPage()) return;

    const candidateInputs = document.querySelectorAll(
      "textarea, input[type='text'], input:not([type]), [contenteditable='true']"
    );

    candidateInputs.forEach((el) => {
      if (el.getAttribute("data-jf-ai-btn-injected") === "true" || !el.offsetParent) return;
      const type = (el.type || "").toLowerCase();
      if (["hidden", "submit", "button", "file", "checkbox", "radio", "password"].includes(type)) return;

      const questionText = getQuestionTextForElement(el);
      const isShortProfile = /^(name|first\s*name|last\s*name|email|phone|contact\s*number|linkedin|github|resume)$/i.test(questionText.trim());
      if (isShortProfile && el.tagName !== "TEXTAREA") return;

      el.setAttribute("data-jf-ai-btn-injected", "true");

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "jf-inline-ai-btn";
      btn.innerHTML = "✨ AI Answer";
      btn.title = "Generate tailored answer with AI";
      Object.assign(btn.style, {
        position: "absolute",
        right: "8px",
        top: el.tagName === "TEXTAREA" ? "8px" : "50%",
        transform: el.tagName === "TEXTAREA" ? "none" : "translateY(-50%)",
        background: "linear-gradient(135deg, #2563eb, #06b6d4)",
        color: "#ffffff",
        border: "none",
        borderRadius: "6px",
        padding: "3px 8px",
        fontSize: "11px",
        fontWeight: "600",
        cursor: "pointer",
        zIndex: "100",
        boxShadow: "0 2px 6px rgba(0,0,0,0.25)",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        lineHeight: "1.4",
        transition: "all 0.15s ease",
        opacity: "0.85"
      });

      btn.addEventListener("mouseenter", () => {
        btn.style.opacity = "1";
        btn.style.transform = (el.tagName === "TEXTAREA" ? "none" : "translateY(-50%)") + " scale(1.04)";
      });
      btn.addEventListener("mouseleave", () => {
        btn.style.opacity = "0.85";
        btn.style.transform = el.tagName === "TEXTAREA" ? "none" : "translateY(-50%)";
      });

      btn.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();

        if (!isRuntimeValid()) {
          showToast("⚠️ Extension was updated. Please refresh page (Cmd+R).");
          return;
        }

        btn.innerHTML = "⏳ Generating...";
        btn.disabled = true;

        try {
          chrome.storage.local.get(["userToken", "resumeData", "backendUrl", "noticePeriod", "salaryExpectations"], async (storage) => {
            if (chrome.runtime.lastError || !storage) {
              btn.innerHTML = "⚠️ Refresh Page";
              btn.disabled = false;
              return;
            }
            let resume = storage.resumeData || {};
            const token = (storage.userToken || "").trim();
            const baseUrl = (storage.backendUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
            const jobInfo = extractJobDetails();
            const qText = getQuestionTextForElement(el) || "Screening Question";

            const answer = await generateAIAnswer(qText, resume, jobInfo, baseUrl, token);
            if (answer) {
              setNativeValue(el, answer);
              el.style.outline = "2px solid #10b981";
              el.style.background = "rgba(16, 185, 129, 0.05)";
              btn.innerHTML = "✅ Filled";
              showToast("✨ AI Answer Generated!");
            } else {
              btn.innerHTML = "⚠️ Retry";
            }
            setTimeout(() => {
              btn.innerHTML = "✨ AI Answer";
              btn.disabled = false;
            }, 2000);
          });
        } catch (err) {
          btn.innerHTML = "⚠️ Refresh Page";
          btn.disabled = false;
          showToast("⚠️ Extension reloaded. Please refresh the page.");
        }
      });

      const parent = el.parentElement;
      if (parent) {
        const computedPos = window.getComputedStyle(parent).position;
        if (computedPos === "static") {
          parent.style.position = "relative";
        }
        parent.appendChild(btn);
      }
    });
  }

  // ── Comprehensive AutoFill Master Function ────────────────────────────
  async function runAutofill() {
    if (!isRuntimeValid()) {
      showToast("⚠️ Extension was updated. Please refresh the page (Cmd+R).");
      return;
    }
    showToast("⏳ Auto-filling application & generating AI answers...");

    try {
      chrome.storage.local.get(["userToken", "resumeData", "eeoProfile", "backendUrl", "noticePeriod", "salaryExpectations"], async (storage) => {
        if (chrome.runtime.lastError || !storage) {
          showToast("⚠️ Extension was reloaded. Please refresh the page.");
          return;
        }
      let resume = storage.resumeData || {};
      const token = (storage.userToken || "").trim();
      const baseUrl = (storage.backendUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
      const customNotice = storage.noticePeriod || resume.notice_period || resume.noticePeriod || "Available immediately";
      const customSalary = storage.salaryExpectations || resume.salary_expectations || resume.salary || "Competitive market rate";

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

      if (!resume || !resume.name) {
        try {
          const sessResp = await fetch(`${baseUrl}/get_session_resume`, {
            headers: { "Authorization": `Bearer ${token}`, "Accept": "application/json" }
          });
          if (sessResp.ok) {
            const sessData = await sessResp.json();
            if (sessData && sessData.data && sessData.data.name) {
              resume = sessData.data;
              chrome.storage.local.set({ resumeData: resume });
            }
          }
        } catch (err) {}
      }

      const eeo = storage.eeoProfile || { workAuth: "Yes", sponsorship: "No" };
      const fullName = (resume.name || "Akhil Baja").trim();
      const nameParts = fullName.split(/\s+/);
      const firstName = nameParts[0] || "Akhil";
      const lastName = nameParts.slice(1).join(" ") || "Baja";
      const email = resume.email || "akhilbaja.work@gmail.com";
      const phone = resume.phone || "+91 9948083135";
      const location = resume.location || "London, UK or Remote";
      const links = Array.isArray(resume.links) ? resume.links : [];
      const linkedin = links.find((l) => l.toLowerCase().includes("linkedin")) || resume.linkedin || "https://linkedin.com/in/akhilkumarbaja";
      const github = links.find((l) => l.toLowerCase().includes("github")) || resume.github || "https://github.com/AkhilBaja3005";
      const portfolio = links.find((l) => !l.toLowerCase().includes("linkedin") && !l.toLowerCase().includes("github")) || resume.portfolio || github;

      const jobInfo = extractJobDetails();
      let filledCount = 0;
      let aiQuestionsAnswered = 0;

      const modal = document.querySelector(
        ".jobs-easy-apply-modal, .artdeco-modal, [data-test-modal], [role='dialog'], .application-container, .ia-BasePage, form, main"
      );
      const scope = modal || document;

      // ── 1. File Upload (Resume PDF) ──────────────────────────────────
      if (resume.pdf_base64) {
        const fileInputs = scope.querySelectorAll("input[type='file']");
        const pdfFile = base64ToFile(resume.pdf_base64, `${firstName || "Candidate"}_Resume.pdf`);
        if (pdfFile) {
          for (const fi of fileInputs) {
            if (fi.files && fi.files.length > 0) continue;
            if (!fi.getAttribute("data-jf-filled")) {
              await fillFileInput(fi, pdfFile);
              fi.setAttribute("data-jf-filled", "true");
              filledCount++;
            }
          }
        }
      }

      // ── 2. Clickable Yes / No Option Cards & Radios (Ashby, Workday, etc.) ──
      const questionBlocks = scope.querySelectorAll('[class*="field"], [class*="formField"], [class*="question"], [class*="Container"], fieldset');
      questionBlocks.forEach((block) => {
        const blockText = (block.innerText || "").toLowerCase();
        if (blockText.includes("office") || blockText.includes("old street") || blockText.includes("in person") || blockText.includes("5 days") || blockText.includes("relocate")) {
          if (clickChoiceInContainer(block, "yes")) filledCount++;
        } else if (blockText.includes("sponsorship") || blockText.includes("visa")) {
          if (clickChoiceInContainer(block, eeo.sponsorship || "no")) filledCount++;
        } else if (blockText.includes("authorized") || blockText.includes("legally")) {
          if (clickChoiceInContainer(block, eeo.workAuth || "yes")) filledCount++;
        }
      });

      // ── 3. Standard & Screening Inputs, Textareas, and Dropdowns ─────
      const formElements = scope.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file']), textarea, select, [contenteditable='true']"
      );

      for (const el of formElements) {
        if (!el.offsetParent || el.getAttribute("data-jf-filled") || el.disabled || el.readOnly) continue;

        // Strict Check: NEVER overwrite already filled / pre-filled fields
        if (el.tagName === "SELECT") {
          if (el.value && el.value.trim() !== "" && el.selectedIndex > 0) {
            const selectedText = el.options[el.selectedIndex]?.text?.toLowerCase() || "";
            if (!selectedText.includes("select") && !selectedText.includes("choose") && !selectedText.includes("please")) {
              continue;
            }
          }
        } else if (el.getAttribute("contenteditable") === "true") {
          if (el.innerText && el.innerText.trim().length > 0) {
            continue;
          }
        } else if (el.type === "checkbox" || el.type === "radio") {
          if (el.checked) {
            continue;
          }
        } else {
          if (el.value && el.value.trim().length > 0) {
            continue;
          }
        }

        const id = (el.id || "").toLowerCase();
        const nameAttr = (el.name || "").toLowerCase();
        const placeholder = (el.getAttribute("placeholder") || "").toLowerCase();
        const ariaLabel = (el.getAttribute("aria-label") || "").toLowerCase();
        const type = (el.type || "").toLowerCase();
        const qText = getQuestionTextForElement(el);
        const qLower = qText.toLowerCase();
        const key = `${id} ${nameAttr} ${placeholder} ${ariaLabel} ${qLower} ${type}`.toLowerCase();

        let val = null;
        let isProfileField = false;

        // Strict Profile Field Checks
        if (/\b(first.?name|given.?name|firstname|fname)\b/i.test(key)) {
          val = firstName;
          isProfileField = true;
        } else if (/\b(last.?name|family.?name|lastname|lname|surname)\b/i.test(key)) {
          val = lastName;
          isProfileField = true;
        } else if (qLower === "name" || /\b(full.?name|your.?name|candidate.?name|legal.?name|\bname\b)\b/i.test(key) && !/company|file|domain|user|login|user_name|sur|hear/i.test(key)) {
          val = fullName;
          isProfileField = true;
        }
        // Email
        else if (/email|e-mail|emailaddress/i.test(key) || type === "email") {
          val = email;
          isProfileField = true;
        }
        // Phone
        else if (/phone|mobile|cell|tel|phonenumber|contact\s*number/i.test(key) || type === "tel") {
          val = phone;
          isProfileField = true;
        }
        // LinkedIn
        else if (/linkedin/i.test(key)) {
          val = linkedin;
          isProfileField = true;
        }
        // GitHub
        else if (/github/i.test(key)) {
          val = github;
          isProfileField = true;
        }
        // Portfolio / Personal website / Links
        else if (/portfolio|personal\s*website|website|blog|personal_site/i.test(key)) {
          val = portfolio || github || linkedin;
          isProfileField = true;
        }
        // Location / City / Address / Country / Postal
        else if (/\b(city|location|address|current_city|current_location|residence)\b/i.test(key) && !/company|work_location/i.test(key)) {
          val = location;
          isProfileField = true;
        }
        // Current / Most Recent Employer & Job Title
        else if (/current\s*(company|employer)|recent\s*company/i.test(key)) {
          val = (resume.experience && resume.experience[0]?.company) || "Qualcomm";
          isProfileField = true;
        } else if (/current\s*(title|position|role)|recent\s*title/i.test(key)) {
          val = (resume.experience && (resume.experience[0]?.role || resume.experience[0]?.title)) || "Software Engineer";
          isProfileField = true;
        }
        // Education (University, Degree, Major, GPA)
        else if (/school|university|college|institution|education_institution/i.test(key)) {
          val = (resume.education && (resume.education[0]?.institution || resume.education[0]?.school)) || "Imperial College London";
          isProfileField = true;
        } else if (/degree|degree_level|education_level/i.test(key)) {
          val = (resume.education && resume.education[0]?.degree) || "Master's Degree";
          isProfileField = true;
        } else if (/major|discipline|field_of_study|department/i.test(key)) {
          val = (resume.education && (resume.education[0]?.field_of_study || resume.education[0]?.fieldOfStudy)) || "Artificial Intelligence";
          isProfileField = true;
        } else if (/gpa|cpi|grade/i.test(key) && type !== "select-one") {
          val = "8.04";
          isProfileField = true;
        } else if (/grad(uation)?\s*(year|date)|completion\s*year/i.test(key)) {
          val = "2027";
          isProfileField = true;
        }
        // Years of Experience (Generic or Tech-Specific)
        else if (/years\s*(of)?\s*experience|total\s*experience|years\s*exp/i.test(key)) {
          val = "3";
          isProfileField = true;
        }
        // Notice Period
        else if (/notice\s*period|notice|how\s*soon|start\s*date/i.test(key) && !/hear|source|how\s*did/i.test(key)) {
          val = customNotice;
          isProfileField = true;
        }
        // Salary expectations
        else if (/salary|compensation|expected\s*pay|pay\s*expectation/i.test(key)) {
          val = customSalary;
          isProfileField = true;
        }
        // EEO & Legal Work Authorization
        else if (/authorized|work in the us|work in the uk|work authorization|legally authorized/i.test(key)) {
          val = eeo.workAuth || "Yes";
          isProfileField = true;
        } else if (/sponsor|visa|require.*sponsorship/i.test(key)) {
          val = eeo.sponsorship || "No";
          isProfileField = true;
        } else if (/gender/i.test(key)) {
          val = eeo.gender || "Male";
          isProfileField = true;
        } else if (/race|ethnicity/i.test(key)) {
          val = eeo.race || "Asian";
          isProfileField = true;
        } else if (/veteran/i.test(key)) {
          val = eeo.veteran || "I am not a protected veteran";
          isProfileField = true;
        } else if (/disability/i.test(key)) {
          val = eeo.disability || "No, I do not have a disability";
          isProfileField = true;
        } else if (/pronoun/i.test(key)) {
          val = "He/Him";
          isProfileField = true;
        } else if (/18\s*years|age\s*of\s*18|legal\s*age|background\s*check|drug\s*test|relocate/i.test(key)) {
          val = "Yes";
          isProfileField = true;
        } else if (/former\s*employee|worked\s*here\s*before|previously\s*employed|non-compete/i.test(key)) {
          val = "No";
          isProfileField = true;
        }

        // ── 4. AI Screening Question Generator for Open Textareas & Inputs ─
        if (!isProfileField && !val) {
          if (qText && qText.length > 3 && (el.tagName === "TEXTAREA" || el.getAttribute("contenteditable") === "true" || type === "text" || !type)) {
            logMsg(`🤖 Generating AI answer for question: "${qText.slice(0, 60)}..."`);
            val = await generateAIAnswer(qText, resume, jobInfo, baseUrl, token);
            aiQuestionsAnswered++;
          }
        }

        if (!val || val === "undefined" || val === "null" || String(val).trim() === "") continue;

        try {
          if (el.tagName === "SELECT") {
            setSelectValue(el, val);
          } else {
            setNativeValue(el, val);
          }
          el.style.outline = "2px solid #10b981";
          el.style.background = "rgba(16, 185, 129, 0.05)";
          filledCount++;
        } catch (e) {}
      }

      // Inject / refresh inline AI buttons
      injectInlineAIButtons();

      logMsg(`⚡ Auto-filled ${filledCount} field${filledCount !== 1 ? "s" : ""} (${aiQuestionsAnswered} AI answers generated).`);
      showToast(`✨ Auto-filled ${filledCount} fields (${aiQuestionsAnswered} AI answers generated)!`);
    });
    } catch (err) {
      showToast("⚠️ Extension was updated. Please refresh the page.");
    }
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

  // ── Auto-Inject Buttons on Mutation / Page Load (Only on Career Sites) ──
  if (isJobOrCareerPage()) {
    setTimeout(injectInlineAIButtons, 800);
    setInterval(injectInlineAIButtons, 2500);
  }

  // ── Message Listener ──────────────────────────────────────────────────
  try {
    if (isRuntimeValid() && chrome.runtime.onMessage) {
      chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        try {
          if (!isRuntimeValid()) return false;
          if (request.action === "GET_JOB_DETAILS") {
            const details = extractJobDetails();
            if (window === window.top || (details.title && details.description && details.description.length > 200)) {
              sendResponse(details);
            }
          } else if (request.action === "TRIGGER_AUTOFILL") {
            runAutofill();
            sendResponse({ status: "ok" });
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
