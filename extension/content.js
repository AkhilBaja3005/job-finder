// content.js - Job Finder AutoFill Content Script (v1.1.0)

(function () {
  console.log("[JobFinder AutoFill] Content script injected.");

  let isAutoRunning = false;
  let appliedCount = 0;
  let skippedCount = 0;

  // Log message helper to record execution steps
  function logMsg(msg) {
    console.log('[JobFinder AutoFill]', msg);
    try {
      chrome.runtime.sendMessage({ type: 'LOG_EVENT', message: msg });
    } catch (e) {}
  }

  // React-safe native value setter for form inputs
  function setNativeValue(el, value) {
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    const nativeTextAreaValueSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value");
    if (el.tagName === "TEXTAREA" && nativeTextAreaValueSetter) {
      nativeTextAreaValueSetter.set.call(el, value);
    } else if (nativeInputValueSetter) {
      nativeInputValueSetter.set.call(el, value);
    } else {
      el.value = value;
    }
    el.dispatchEvent(new Event("input",  { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent("keydown",  { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent("keyup",    { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent("keypress", { bubbles: true }));
  }

  // Select option value setter
  function setSelectValue(el, value) {
    if (!value) return;
    const lv = value.toLowerCase();
    let matched = null;
    for (const opt of el.options) {
      if (opt.value.toLowerCase() === lv || opt.text.toLowerCase() === lv ||
          opt.value.toLowerCase().includes(lv) || opt.text.toLowerCase().includes(lv)) {
        matched = opt.value;
        break;
      }
    }
    if (matched !== null) {
      el.value = matched;
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  // Convert base64 resume string to native JS File object for automated upload
  function base64ToFile(base64String, filename, mimeType) {
    try {
      const base64Data = base64String.includes(',') ? base64String.split(',')[1] : base64String;
      const binaryString = atob(base64Data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      return new File([bytes], filename, { type: mimeType });
    } catch (error) {
      logMsg(`❌ Error converting base64 to file: ${error.message}`);
      return null;
    }
  }

  // Attach resume file into file inputs using DataTransfer API
  async function fillFileInput(fileInput, file) {
    try {
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      fileInput.files = dataTransfer.files;
      fileInput.dispatchEvent(new Event('change', { bubbles: true }));
      logMsg(`✅ Auto-attached resume: ${file.name}`);
      return true;
    } catch (error) {
      logMsg(`❌ Error attaching file: ${error.message}`);
      return false;
    }
  }

  // Detect LinkedIn Daily Limit Notice
  function checkDailyLimit() {
    const limitPatterns = [
      "You've reached today's Easy Apply limit",
      "reached today's Easy Apply limit",
      "Great effort applying today",
      "continue applying tomorrow",
      "exceeded the daily application limit"
    ];
    const bodyText = document.body.innerText || '';
    for (const pattern of limitPatterns) {
      if (bodyText.toLowerCase().includes(pattern.toLowerCase())) {
        logMsg("🚫 LINKEDIN DAILY LIMIT REACHED!");
        alert("🚫 LinkedIn Daily Easy Apply limit reached (~50-100/day). Pausing batch loop.");
        return true;
      }
    }
    return false;
  }

  // Discard application modal if stuck or error occurs
  async function discardApplication() {
    logMsg("🔍 Cleaning up/discarding modal...");
    const closeButtons = document.querySelectorAll('button[aria-label*="Dismiss"], button[aria-label*="Close"], button.artdeco-modal__dismiss');
    for (let btn of closeButtons) {
      if (btn.offsetParent) {
        btn.click();
        await new Promise(r => setTimeout(r, 600));
        const discardConfirm = Array.from(document.querySelectorAll('button')).find(b =>
          b.offsetParent && ['discard', 'cancel', 'annuler'].some(t => b.textContent.trim().toLowerCase().includes(t))
        );
        if (discardConfirm) {
          discardConfirm.click();
          await new Promise(r => setTimeout(r, 800));
        }
        return true;
      }
    }
    return false;
  }

  // Single-page auto fill trigger logic
  async function autoFillJobForm() {
    chrome.storage.local.get(["userToken", "resumeData", "eeoProfile"], async (storage) => {
      let resume = storage.resumeData || {};
      const token = storage.userToken || "guest";

      if (!resume || !resume.name) {
        try {
          const resp = await fetch("http://127.0.0.1:8000/user/me", {
            headers: { "Authorization": `Bearer ${token}` }
          });
          if (resp.ok) {
            const userProfile = await resp.json();
            if (userProfile && userProfile.resume_data) {
              resume = userProfile.resume_data;
              chrome.storage.local.set({ resumeData: resume });
            }
          }
        } catch (err) {
          logMsg(`Backend resume fetch notice: ${err.message}`);
        }
      }

      const eeo = storage.eeoProfile || {};
      const fullName  = resume.name  || "";
      const nameParts = fullName.trim().split(/\s+/);
      const firstName = nameParts[0] || "";
      const lastName  = nameParts.slice(1).join(" ") || "";
      const email     = resume.email || "";
      const phone     = resume.phone || "";
      const summary   = resume.summary || "";
      const linkedin  = (resume.links || []).find(l => l.includes("linkedin.com")) || "";
      const github    = (resume.links || []).find(l => l.includes("github.com"))   || "";

      const modal = document.querySelector(
        ".jobs-easy-apply-modal, .artdeco-modal, [data-test-modal], " +
        "[role='dialog'], .application-container, .ia-BasePage"
      );
      const scope = modal || document;

      // Handle file attachments if base64 pdf is stored
      if (resume.pdf_base64) {
        const fileInputs = scope.querySelectorAll("input[type='file']");
        const pdfFile = base64ToFile(resume.pdf_base64, `${firstName || 'Resume'}_CV.pdf`, "application/pdf");
        if (pdfFile) {
          for (const fi of fileInputs) {
            if (!fi.getAttribute("data-jf-filled")) {
              await fillFileInput(fi, pdfFile);
              fi.setAttribute("data-jf-filled", "true");
            }
          }
        }
      }

      const inputs = scope.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='file'])," +
        "textarea, select"
      );

      let filledCount = 0;
      for (const inp of inputs) {
        if (!inp.offsetParent || inp.getAttribute("data-jf-filled") || inp.disabled || inp.readOnly) continue;

        const id          = (inp.id || "").toLowerCase();
        const nameAttr    = (inp.name || "").toLowerCase();
        const placeholder = (inp.placeholder || "").toLowerCase();
        const ariaLabel   = (inp.getAttribute("aria-label") || "").toLowerCase();
        const type        = (inp.type || "").toLowerCase();
        const labelText   = (inp.closest("div,li,fieldset")?.innerText || "").slice(0, 120).toLowerCase();
        const key         = `${id} ${nameAttr} ${placeholder} ${ariaLabel} ${labelText} ${type}`;

        let val = null;

        if (/first.?name|given.?name|firstname|fname/.test(key)) val = firstName;
        else if (/last.?name|family.?name|lastname|lname|surname/.test(key)) val = lastName;
        else if (/email|e-mail/.test(key) || type === "email") val = email;
        else if (/phone|mobile|cell|tel/.test(key) || type === "tel") val = phone;
        else if (/linkedin/.test(key)) val = linkedin;
        else if (/github/.test(key)) val = github;
        else if (/summary|cover.?letter|about you/.test(key)) val = summary;
        else if (/authorized|work in the us|work authorization/.test(key)) val = eeo.workAuth || "No";
        else if (/sponsor|visa/.test(key)) val = eeo.sponsorship || "No";

        if (!val) continue;

        try {
          if (inp.tagName === "SELECT") {
            setSelectValue(inp, val);
          } else {
            inp.focus();
            setNativeValue(inp, val);
          }
          inp.setAttribute("data-jf-filled", "true");
          inp.style.outline = "2px solid #38bdf8";
          filledCount++;
        } catch (e) {}
      }

      logMsg(`⚡ Filled ${filledCount} fields.`);
      showToast(`⚡ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""}!`);
    });
  }

  // Toast feedback element
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
      fontFamily: "system-ui, sans-serif"
    });
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; }, 2500);
    setTimeout(() => toast.remove(), 3000);
  }

  // Floating Auto-Fill badge button
  function createFloatingBadge() {
    if (document.getElementById("jf-autofill-badge")) return;
    const badge = document.createElement("div");
    badge.id = "jf-autofill-badge";
    Object.assign(badge.style, {
      position: "fixed", bottom: "20px", right: "20px",
      background: "rgba(15,23,42,0.9)", color: "#38bdf8",
      border: "1px solid rgba(56,189,248,0.3)", borderRadius: "12px",
      padding: "8px 14px", fontSize: "13px", fontWeight: "700",
      zIndex: "2147483646", cursor: "pointer", fontFamily: "system-ui, sans-serif",
      userSelect: "none"
    });
    badge.innerHTML = `<span>⚡</span><span>Auto-Fill</span>`;
    badge.addEventListener("click", autoFillJobForm);
    document.body.appendChild(badge);
  }

  // Message listener from popup/background
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "TRIGGER_AUTOFILL") {
      autoFillJobForm();
      sendResponse({ status: "started" });
    }
    if (request.action === "TOGGLE_BATCH_AUTO") {
      isAutoRunning = request.state;
      logMsg(isAutoRunning ? "▶️ Batch Auto-Apply STARTED" : "⏸️ Batch Auto-Apply STOPPED");
      if (isAutoRunning) runBatchAutoApplyLoop();
    }
    return true;
  });

  // Batch Auto Apply Loop for LinkedIn
  async function runBatchAutoApplyLoop() {
    if (!window.location.href.includes("linkedin.com")) {
      logMsg("⚠️ Batch loop only active on LinkedIn jobs pages.");
      return;
    }
    logMsg("🚀 Starting LinkedIn Easy Apply Batch Loop...");

    chrome.storage.local.get(["appliedCount", "skippedCount", "blacklistKeywords"], async (items) => {
      appliedCount = items.appliedCount || 0;
      skippedCount = items.skippedCount || 0;
      const blacklist = (items.blacklistKeywords || "").split(',').map(s => s.trim().toLowerCase()).filter(Boolean);

      while (isAutoRunning) {
        if (checkDailyLimit()) {
          isAutoRunning = false;
          chrome.storage.local.set({ isAutoRunning: false });
          break;
        }

        const jobCards = document.querySelectorAll('li[data-occludable-job-id], .jobs-search-results__list-item');
        if (jobCards.length === 0) {
          logMsg("No job listings found on page. Waiting 4s...");
          await new Promise(r => setTimeout(r, 4000));
          continue;
        }

        logMsg(`Found ${jobCards.length} job cards on current page.`);

        for (let i = 0; i < jobCards.length; i++) {
          if (!isAutoRunning) break;
          const card = jobCards[i];
          const title = (card.querySelector('.job-card-list__title, .artdeco-entity-lockup__title')?.innerText || "").toLowerCase();

          if (blacklist.some(word => title.includes(word))) {
            logMsg(`Skipping blacklisted job: "${title.slice(0, 30)}..."`);
            skippedCount++;
            chrome.storage.local.set({ skippedCount });
            continue;
          }

          const link = card.querySelector('a');
          if (link) {
            link.click();
            await new Promise(r => setTimeout(r, 1200));
          }

          const easyApplyBtn = document.querySelector('button.jobs-apply-button[aria-label*="Easy"]');
          if (!easyApplyBtn) {
            logMsg("Not Easy Apply, skipping...");
            skippedCount++;
            chrome.storage.local.set({ skippedCount });
            continue;
          }

          easyApplyBtn.click();
          await new Promise(r => setTimeout(r, 1500));

          await autoFillJobForm();
          await new Promise(r => setTimeout(r, 1500));

          // Step through form buttons
          let submitBtn = document.querySelector('button[aria-label*="Submit application"]');
          if (submitBtn) {
            submitBtn.click();
            logMsg("✅ Application submitted successfully!");
            appliedCount++;
            chrome.storage.local.set({ appliedCount });
            await new Promise(r => setTimeout(r, 2000));
          } else {
            await discardApplication();
            skippedCount++;
            chrome.storage.local.set({ skippedCount });
          }
        }

        logMsg("Finished processing current visible list.");
        break;
      }
    });
  }

  // Init badge
  if (document.readyState === "complete" || document.readyState === "interactive") {
    createFloatingBadge();
  } else {
    window.addEventListener("DOMContentLoaded", createFloatingBadge);
  }
})();
