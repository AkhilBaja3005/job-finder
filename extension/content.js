// content.js - Job Finder AutoFill Content Script

(function () {
  console.log("[JobFinder AutoFill] Extension script injected.");

  // Create floating quick fill badge in bottom right corner
  function createFloatingBadge() {
    if (document.getElementById("jf-autofill-badge")) return;

    const badge = document.createElement("div");
    badge.id = "jf-autofill-badge";
    badge.className = "jf-floating-badge";
    badge.innerHTML = `
      <span class="jf-icon">⚡</span>
      <span>Job Finder AI</span>
      <button class="jf-btn-fill" id="jf-trigger-fill">Auto-Fill Form</button>
    `;

    document.body.appendChild(badge);

    document.getElementById("jf-trigger-fill").addEventListener("click", (e) => {
      e.stopPropagation();
      autoFillJobForm();
    });
  }

  // Scan and auto-fill visible job form inputs
  async function autoFillJobForm() {
    const inputs = document.querySelectorAll(
      "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select"
    );

    let filledCount = 0;

    // Get user resume details & EEO preferences from storage
    chrome.storage.local.get(["userToken", "resumeData", "eeoProfile"], async (storage) => {
      let resume = storage.resumeData || {};
      const token = storage.userToken || "guest";

      // If local resume data is missing, fetch user profile dynamically from backend API
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
          console.log("[JobFinder AutoFill] Backend resume fetch notice:", err.message);
        }
      }

      const eeo = storage.eeoProfile || {};
      const name = resume.name || "";
      const firstName = name.split(" ")[0] || "";
      const lastName = name.split(" ").slice(1).join(" ") || "";
      const email = resume.email || "";
      const phone = resume.phone || "";
      const summary = resume.summary || "";
      const linkedin = (resume.links || []).find((l) => l.includes("linkedin.com")) || "";
      const github = (resume.links || []).find((l) => l.includes("github.com")) || "";

      for (const inp of inputs) {
        if (inp.offsetParent === null || inp.getAttribute("data-jf-filled")) continue;

        const id = (inp.id || "").toLowerCase();
        const nameAttr = (inp.name || "").toLowerCase();
        const placeholder = (inp.placeholder || "").toLowerCase();
        const type = (inp.type || "").toLowerCase();

        // Get label text
        let labelText = "";
        if (inp.id) {
          const lbl = document.querySelector(`label[for='${inp.id}']`);
          if (lbl) labelText = lbl.innerText.toLowerCase();
        }
        if (!labelText && inp.closest("div")) {
          labelText = inp.closest("div").innerText.toLowerCase();
        }

        const key = `${id} ${nameAttr} ${placeholder} ${labelText}`;

        let valToFill = null;

        if (key.includes("first name") || key.includes("given name") || key.includes("firstname")) {
          valToFill = firstName;
        } else if (key.includes("last name") || key.includes("family name") || key.includes("lastname")) {
          valToFill = lastName;
        } else if (key.includes("email") || type === "email") {
          valToFill = email;
        } else if (key.includes("phone") || key.includes("mobile") || type === "tel") {
          valToFill = phone;
        } else if (key.includes("linkedin")) {
          valToFill = linkedin;
        } else if (key.includes("github")) {
          valToFill = github;
        } else if (key.includes("summary") || key.includes("cover letter") || key.includes("about you")) {
          valToFill = summary;
        } else if (key.includes("authorized") || key.includes("work in the us") || key.includes("work authorization")) {
          valToFill = eeo.workAuth || "No";
        } else if (key.includes("sponsorship") || key.includes("require visa")) {
          valToFill = eeo.sponsorship || "No";
        } else if (key.includes("gender")) {
          valToFill = eeo.gender || "Male";
        } else if (key.includes("disability")) {
          valToFill = eeo.disability || "No";
        }

        if (valToFill && (inp.tagName === "INPUT" || inp.tagName === "TEXTAREA" || inp.tagName === "SELECT")) {
          inp.value = valToFill;
          inp.dispatchEvent(new Event("input", { bubbles: true }));
          inp.dispatchEvent(new Event("change", { bubbles: true }));
          inp.classList.add("jf-autofill-highlight");
          inp.setAttribute("data-jf-filled", "true");
          filledCount++;
        }
      }

      console.log(`[JobFinder AutoFill] Successfully filled ${filledCount} basic & EEO fields.`);
    });
  }

  // Listen for message from popup button
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "TRIGGER_AUTOFILL") {
      autoFillJobForm();
      sendResponse({ status: "started" });
    }
  });

  // Automatically sync login auth_token from website into extension storage
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    const token = localStorage.getItem("auth_token");
    if (token) {
      chrome.storage.local.set({ userToken: token }, () => {
        console.log("[JobFinder AutoFill] Synced user login session token to extension!");
      });
    }
  }

  // Initialize floating badge on page load
  if (document.readyState === "complete" || document.readyState === "interactive") {
    createFloatingBadge();
  } else {
    window.addEventListener("DOMContentLoaded", createFloatingBadge);
  }
})();
