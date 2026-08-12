// content.js - Job Finder AutoFill Content Script

(function () {
  console.log("[JobFinder AutoFill] Extension script injected.");

  // ── React-safe value setter ──────────────────────────────────────────────
  // LinkedIn, Workday, and Greenhouse all use React synthetic events.
  // Simply setting .value = x won't trigger React's onChange.
  // We must use the native input value descriptor to force React to notice.
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

  // ── Select-option filler (handles dropdowns) ────────────────────────────
  function setSelectValue(el, value) {
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

  // ── Field matching ───────────────────────────────────────────────────────
  function matchKey(el) {
    const id          = (el.id          || "").toLowerCase();
    const name        = (el.name        || "").toLowerCase();
    const placeholder = (el.placeholder || "").toLowerCase();
    const ariaLabel   = (el.getAttribute("aria-label") || "").toLowerCase();
    const type        = (el.type        || "").toLowerCase();

    // Grab nearest visible label
    let labelText = "";
    if (el.id) {
      const lbl = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lbl) labelText = lbl.innerText.toLowerCase();
    }
    if (!labelText) {
      const parent = el.closest("div,li,fieldset");
      if (parent) labelText = parent.innerText.slice(0, 120).toLowerCase();
    }

    return `${id} ${name} ${placeholder} ${ariaLabel} ${labelText} ${type}`;
  }

  // ── Core auto-fill logic ─────────────────────────────────────────────────
  async function autoFillJobForm() {
    chrome.storage.local.get(["userToken", "resumeData", "eeoProfile"], async (storage) => {
      let resume = storage.resumeData || {};
      const token = storage.userToken || "guest";

      // Fetch live profile from backend if no local resume
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
          console.log("[JobFinder AutoFill] Backend fetch notice:", err.message);
        }
      }

      const eeo = storage.eeoProfile || {};

      // ── Parse profile values ──────────────────────────────────────────
      const fullName  = resume.name  || "";
      const nameParts = fullName.trim().split(/\s+/);
      const firstName = nameParts[0] || "";
      const lastName  = nameParts.slice(1).join(" ") || "";
      const email     = resume.email || "";
      const phone     = resume.phone || "";
      const summary   = resume.summary || "";
      const linkedin  = (resume.links || []).find(l => l.includes("linkedin.com")) || "";
      const github    = (resume.links || []).find(l => l.includes("github.com"))   || "";

      const workAuth    = eeo.workAuth    || "No";
      const sponsorship = eeo.sponsorship || "No";
      const gender      = eeo.gender      || "";
      const disability  = eeo.disability  || "";

      // ── Determine scope: LinkedIn Easy Apply modal or full page ───────
      const modal = document.querySelector(
        ".jobs-easy-apply-modal, .artdeco-modal, [data-test-modal], " +
        "[role='dialog'], .application-container, .ia-BasePage"
      );
      const scope = modal || document;

      const inputs = scope.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button'])," +
        "textarea, select"
      );

      let filledCount = 0;

      for (const inp of inputs) {
        // Skip hidden, already filled, or disabled fields
        if (!inp.offsetParent) continue;
        if (inp.getAttribute("data-jf-filled")) continue;
        if (inp.disabled || inp.readOnly) continue;

        const key = matchKey(inp);

        let val = null;

        // ── Name matching ───────────────────────────────────────────────
        if (/first.?name|given.?name|firstname|fname/.test(key)) {
          val = firstName;
        } else if (/last.?name|family.?name|lastname|lname|surname/.test(key)) {
          val = lastName;
        } else if (/\bname\b/.test(key) && !/company|school|institution|degree/.test(key) && !firstName && !lastName) {
          val = fullName;
        } else if (/\bname\b/.test(key) && !/company|school|institution|degree/.test(key) && inp.tagName !== "SELECT") {
          // full name field if only one name input
          if (!/first|last|given|family/.test(key)) val = fullName;
        }

        // ── Contact ─────────────────────────────────────────────────────
        else if (/email|e-mail/.test(key) || inp.type === "email") { val = email; }
        else if (/phone|mobile|cell|tel/.test(key)  || inp.type === "tel")   { val = phone; }
        else if (/linkedin/.test(key))  { val = linkedin; }
        else if (/github/.test(key))    { val = github; }

        // ── Cover letter / Summary ───────────────────────────────────────
        else if (/summary|cover.?letter|about you|additional info|message|introduce/.test(key)) {
          val = summary;
        }

        // ── EEO dropdowns ────────────────────────────────────────────────
        else if (/authorized|legally authorized|work in the us|us work|work authorization|right to work/.test(key)) {
          val = workAuth;
        } else if (/sponsor|visa|require.*(sponsor|visa)/.test(key)) {
          val = sponsorship;
        } else if (/\bgender\b|sex\b/.test(key)) {
          val = gender;
        } else if (/disability|disabled/.test(key)) {
          val = disability;
        }

        if (!val) continue;

        // ── Fill the field ───────────────────────────────────────────────
        try {
          if (inp.tagName === "SELECT") {
            setSelectValue(inp, val);
          } else {
            inp.focus();
            setNativeValue(inp, val);
          }
          inp.setAttribute("data-jf-filled", "true");
          inp.style.outline = "2px solid #38bdf8";
          inp.style.outlineOffset = "1px";
          filledCount++;
        } catch (e) {
          console.log("[JobFinder AutoFill] Field fill error:", e);
        }
      }

      // ── Also handle LinkedIn-specific radio/checkbox EEO fields ────────
      // LinkedIn renders Yes/No EEO as <button role="radio"> pairs
      if (modal) {
        fillLinkedInRadioButtons(modal, { workAuth, sponsorship, gender, disability });
      }

      console.log(`[JobFinder AutoFill] Filled ${filledCount} fields on ${window.location.hostname}.`);
      showToast(`⚡ Filled ${filledCount} field${filledCount !== 1 ? "s" : ""}!`);
    });
  }

  // ── LinkedIn radio button / aria button EEO handler ─────────────────────
  function fillLinkedInRadioButtons(scope, { workAuth, sponsorship, gender, disability }) {
    const groups = scope.querySelectorAll("[data-test-form-element], .fb-form-element, fieldset, [role='radiogroup']");
    groups.forEach(group => {
      const labelEl = group.querySelector("label, legend, [data-test-form-element-label], h3");
      if (!labelEl) return;
      const label = labelEl.innerText.toLowerCase();

      let targetAnswer = null;
      if (/authorized|legally authorized|right to work/.test(label)) targetAnswer = workAuth;
      else if (/sponsor|visa/.test(label)) targetAnswer = sponsorship;
      else if (/gender|sex/.test(label)) targetAnswer = gender;
      else if (/disability/.test(label)) targetAnswer = disability;

      if (!targetAnswer) return;

      // Try <select> first
      const sel = group.querySelector("select");
      if (sel) { setSelectValue(sel, targetAnswer); return; }

      // Try radio inputs
      const radios = group.querySelectorAll("input[type='radio']");
      for (const radio of radios) {
        if (radio.getAttribute("data-jf-filled")) continue;
        const rl = (radio.value + " " + (radio.nextElementSibling?.innerText || "")).toLowerCase();
        if (rl.includes(targetAnswer.toLowerCase()) || targetAnswer.toLowerCase().includes(rl.trim())) {
          radio.checked = true;
          radio.dispatchEvent(new Event("change", { bubbles: true }));
          radio.setAttribute("data-jf-filled", "true");
          break;
        }
      }

      // Try aria role=radio buttons (LinkedIn style)
      const ariaRadios = group.querySelectorAll("[role='radio']");
      for (const btn of ariaRadios) {
        if (btn.getAttribute("data-jf-filled")) continue;
        const bl = btn.innerText.toLowerCase();
        if (bl.includes(targetAnswer.toLowerCase()) || targetAnswer.toLowerCase().includes(bl.trim())) {
          btn.click();
          btn.setAttribute("data-jf-filled", "true");
          break;
        }
      }
    });
  }

  // ── Toast notification ───────────────────────────────────────────────────
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
      fontFamily: "system-ui, sans-serif", backdropFilter: "blur(12px)",
      transition: "opacity 0.4s ease"
    });
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = "0"; }, 2500);
    setTimeout(() => toast.remove(), 3000);
  }

  // ── Floating badge ───────────────────────────────────────────────────────
  function createFloatingBadge() {
    if (document.getElementById("jf-autofill-badge")) return;

    const badge = document.createElement("div");
    badge.id = "jf-autofill-badge";
    Object.assign(badge.style, {
      position: "fixed", bottom: "20px", right: "20px",
      background: "rgba(15,23,42,0.9)", color: "#38bdf8",
      border: "1px solid rgba(56,189,248,0.3)", borderRadius: "12px",
      padding: "8px 14px", fontSize: "13px", fontWeight: "700",
      zIndex: "2147483646", boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
      display: "flex", alignItems: "center", gap: "8px",
      cursor: "pointer", fontFamily: "system-ui, sans-serif",
      backdropFilter: "blur(12px)", userSelect: "none",
      transition: "transform 0.15s ease, box-shadow 0.15s ease"
    });
    badge.innerHTML = `<span>⚡</span><span>Auto-Fill</span>`;
    badge.title = "Click to auto-fill this job application";

    badge.addEventListener("mouseenter", () => {
      badge.style.transform = "translateY(-2px)";
      badge.style.boxShadow = "0 12px 32px rgba(56,189,248,0.2)";
    });
    badge.addEventListener("mouseleave", () => {
      badge.style.transform = "";
      badge.style.boxShadow = "0 8px 24px rgba(0,0,0,0.4)";
    });
    badge.addEventListener("click", autoFillJobForm);
    document.body.appendChild(badge);
  }

  // ── Message listener from popup ──────────────────────────────────────────
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "TRIGGER_AUTOFILL") {
      autoFillJobForm();
      sendResponse({ status: "started" });
    }
    return true;
  });

  // ── Sync login token from website if on localhost ────────────────────────
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    const token = localStorage.getItem("auth_token");
    if (token) {
      chrome.storage.local.set({ userToken: token }, () => {
        console.log("[JobFinder AutoFill] Synced auth token to extension.");
      });
    }
  }

  // ── Init badge ───────────────────────────────────────────────────────────
  if (document.readyState === "complete" || document.readyState === "interactive") {
    createFloatingBadge();
  } else {
    window.addEventListener("DOMContentLoaded", createFloatingBadge);
  }

  // ── LinkedIn: re-inject badge when Easy Apply modal opens ───────────────
  const observer = new MutationObserver(() => {
    createFloatingBadge();
  });
  observer.observe(document.body, { childList: true, subtree: false });

})();
