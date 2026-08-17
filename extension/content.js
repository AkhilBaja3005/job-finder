// content.js - Job Finder ATS Tailor Content Script (v2.3.0)

(function () {
  if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1") {
    return;
  }

  // Extract page job details safely from active tab DOM
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
        document.querySelector(".job-details-jobs-unified-top-card__primary-description") ||
        document.querySelector(".jobs-unified-top-card__subtitle-primary-grouping")
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
      title = document.title;
      description = document.body.innerText.slice(0, 4000);
    }

    return { title, company, description, url };
  }

  // Listen for message requests from extension popup
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "GET_JOB_DETAILS") {
      const details = extractJobDetails();
      sendResponse(details);
    }
    return true;
  });
})();
