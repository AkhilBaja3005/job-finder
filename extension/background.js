// background.js - Job Finder AutoFill Extension Service Worker

const BACKEND_URL = "http://127.0.0.1:8000";

// Listen for messages from content scripts or popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "GET_BACKEND_HEALTH") {
    fetch(`${BACKEND_URL}/healthz`)
      .then((res) => res.json())
      .then((data) => sendResponse({ success: true, data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // Keep channel open for async response
  }

  if (request.action === "PARSE_PAGE_QUESTION") {
    // Send field context & question to local backend for AI answer resolution
    chrome.storage.local.get(["userToken", "resumeData", "customApiKey"], (items) => {
      fetch(`${BACKEND_URL}/user/solve_field`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${items.userToken || "guest"}`
        },
        body: JSON.stringify({
          question: request.question,
          context: request.context,
          resume_data: items.resumeData || {},
          api_key: items.customApiKey || null
        })
      })
        .then((res) => res.json())
        .then((data) => sendResponse({ success: true, answer: data.answer }))
        .catch((err) => sendResponse({ success: false, error: err.message }));
    });
    return true;
  }
});
