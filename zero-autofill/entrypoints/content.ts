import { defineContentScript } from 'wxt/sandbox';
import { getProfile, getSettings, db, CandidateProfile } from '../modules/storage/db';
import { autofillGreenhouse } from '../modules/adapters/greenhouse';
import { autofillLever } from '../modules/adapters/lever';
import { autofillWorkday } from '../modules/adapters/workday';
import { autofillAshby } from '../modules/adapters/ashby';
import { autofillLinkedIn, checkLinkedInDailyLimit, discardLinkedInModal } from '../modules/adapters/linkedin';
import { autofillUniversal } from '../modules/adapters/universal';
import { batchSolvePageQuestions } from '../modules/ai/page-analyzer';
import { generateFieldAnswer } from '../modules/ai/client';
import { fillNativeInput } from '../modules/adapters/base-adapter';

export default defineContentScript({
  matches: ['<all_urls>'],
  main() {
    console.log('[Job Finder ATS Tailor Content Script Active]');

    // Inject Floating Action Trigger
    injectFloatingWidget();

    let isAutoRunning = false;

    function logMsg(msg: string) {
      console.log('[Job Finder ATS]', msg);
      try {
        chrome.storage.local.get(['appLogs'], (items) => {
          const logs = items.appLogs || [];
          logs.push(`[${new Date().toLocaleTimeString()}] ${msg}`);
          if (logs.length > 60) logs.shift();
          chrome.storage.local.set({ appLogs: logs });
        });
      } catch (e) {}
    }

    // Listen for manual trigger commands from Sidepanel or Popup
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === 'RUN_AUTOFILL' || request.action === 'TRIGGER_AUTOFILL') {
        runAutofillSequence().then((count) => {
          sendResponse({ success: true, count });
        });
        return true;
      }

      if (request.action === 'TOGGLE_BATCH_AUTO') {
        isAutoRunning = !!request.state;
        logMsg(isAutoRunning ? '▶️ Batch Auto-Apply Loop STARTED' : '⏸️ Batch Auto-Apply Loop STOPPED');
        if (isAutoRunning) {
          runBatchAutoApplyLoop(() => isAutoRunning, logMsg);
        }
        sendResponse({ success: true, isAutoRunning });
        return true;
      }

      if (request.action === 'SOLVE_WITH_AI') {
        getProfile().then(async (profile) => {
          if (!profile) {
            sendResponse({ success: false, count: 0, error: 'Profile not configured' });
            return;
          }
          const fullPageImage = await captureFullPageScreenshot();
          batchSolvePageQuestions(profile, fullPageImage).then(({ solvedCount, fieldDetails }) => {
            sendResponse({ success: true, count: solvedCount, details: fieldDetails });
          });
        });
        return true;
      }

      if (request.action === 'GET_PAGE_DETAILS') {
        sendResponse({
          title: document.title,
          url: window.location.href,
          text: document.body.innerText.substring(0, 4000)
        });
        return true;
      }
    });

    // Auto-detect form submit to log application to IndexedDB
    window.addEventListener(
      'submit',
      async (e) => {
        const form = e.target as HTMLFormElement;
        if (form) {
          const titleParts = document.title.split('-')[0] || document.title;
          const host = window.location.hostname.replace('www.', '').split('.')[0];
          const company = host.charAt(0).toUpperCase() + host.slice(1);

          await db.applications.add({
            company: company,
            position: titleParts.trim() || 'Software Engineer',
            jobUrl: window.location.href,
            status: 'Applied',
            appliedDate: new Date().toISOString().split('T')[0],
            jobDescriptionText: document.body.innerText.substring(0, 2000)
          });
          logMsg(`Logged application submission for ${company}`);
        }
      },
      true
    );
  }
});

async function runAutofillSequence(): Promise<number> {
  const profile = await getProfile();
  if (!profile) {
    alert('Please configure your Candidate Profile in the Job Finder ATS sidepanel first!');
    return 0;
  }

  const url = window.location.href;
  let filled = 0;

  if (url.includes('greenhouse.io')) {
    filled += autofillGreenhouse(profile);
  } else if (url.includes('lever.co')) {
    filled += autofillLever(profile);
  } else if (url.includes('workday') || url.includes('myworkdayjobs')) {
    filled += autofillWorkday(profile);
  } else if (url.includes('ashbyhq.com')) {
    filled += autofillAshby(profile);
  } else if (url.includes('linkedin.com')) {
    filled += await autofillLinkedIn(profile);
  }

  // Secondary pass: run universal autofill to catch any remaining inputs
  filled += autofillUniversal(profile);

  // Inject inline AI Answer buttons on unfilled custom textareas
  injectInlineAIButtons(profile);

  return filled;
}

function injectInlineAIButtons(profile: CandidateProfile) {
  const textareas = document.querySelectorAll<HTMLTextAreaElement>('textarea');
  textareas.forEach((ta) => {
    if (ta.getAttribute('data-zero-ai-injected') === 'true' || ta.value.trim().length > 0) return;
    if (ta.offsetParent === null) return;

    ta.setAttribute('data-zero-ai-injected', 'true');

    const wrapper = document.createElement('div');
    wrapper.style.position = 'relative';
    wrapper.style.display = 'inline-block';
    wrapper.style.width = '100%';

    const aiBtn = document.createElement('button');
    aiBtn.type = 'button';
    aiBtn.innerText = '✨ AI Answer';
    aiBtn.title = 'Auto-generate tailored answer from your profile with AI';
    Object.assign(aiBtn.style, {
      position: 'absolute',
      right: '10px',
      top: '10px',
      background: 'linear-gradient(135deg, #6366f1, #0284c7)',
      color: '#fff',
      border: 'none',
      borderRadius: '6px',
      padding: '4px 8px',
      fontSize: '11px',
      fontWeight: '600',
      cursor: 'pointer',
      zIndex: '10',
      boxShadow: '0 2px 5px rgba(0,0,0,0.2)'
    });

    aiBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      aiBtn.innerText = '⚡ Generating...';
      aiBtn.disabled = true;

      const label = ta.closest('label')?.textContent ||
                    document.querySelector(`label[for="${ta.id}"]`)?.textContent ||
                    ta.placeholder ||
                    'Application Question';

      const answer = await generateFieldAnswer(label, document.body.innerText.substring(0, 1000), profile);
      fillNativeInput(ta, answer);

      aiBtn.innerText = '✅ Filled';
      setTimeout(() => {
        aiBtn.innerText = '✨ AI Answer';
        aiBtn.disabled = false;
      }, 2500);
    });

    if (ta.parentNode) {
      ta.parentNode.insertBefore(wrapper, ta);
      wrapper.appendChild(ta);
      wrapper.appendChild(aiBtn);
    }
  });
}

function injectFloatingWidget() {
  if (document.getElementById('jf-autofill-fab')) return;

  const fab = document.createElement('button');
  fab.id = 'jf-autofill-fab';
  fab.title = 'Job Finder ATS AutoFill Active Page';
  Object.assign(fab.style, {
    position: 'fixed',
    bottom: '24px',
    right: '24px',
    width: '46px',
    height: '46px',
    borderRadius: '50%',
    backgroundColor: '#0284c7',
    color: '#ffffff',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 15px rgba(2, 132, 199, 0.4)',
    border: '2px solid rgba(255,255,255,0.2)',
    cursor: 'pointer',
    zIndex: '2147483647',
    fontSize: '20px',
    transition: 'transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1)'
  });
  fab.innerHTML = '⚡';

  fab.onmouseenter = () => { fab.style.transform = 'scale(1.12)'; };
  fab.onmouseleave = () => { fab.style.transform = 'scale(1)'; };

  fab.onclick = async () => {
    fab.style.transform = 'scale(0.9)';
    const filledCount = await runAutofillSequence();
    fab.style.transform = 'scale(1)';

    const toast = document.createElement('div');
    toast.innerText = filledCount > 0 ? `⚡ Auto-filled ${filledCount} field${filledCount > 1 ? 's' : ''}!` : `✨ Page checked!`;
    Object.assign(toast.style, {
      position: 'fixed',
      bottom: '80px',
      right: '24px',
      backgroundColor: '#0f172a',
      color: '#38bdf8',
      border: '1px solid #0284c7',
      padding: '8px 14px',
      borderRadius: '8px',
      fontSize: '12px',
      fontWeight: '600',
      zIndex: '2147483647',
      boxShadow: '0 4px 15px rgba(0,0,0,0.3)',
      fontFamily: 'sans-serif'
    });
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2500);
  };

  document.body.appendChild(fab);
}

async function captureFullPageScreenshot(): Promise<string | undefined> {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ action: 'CAPTURE_TAB_SCREENSHOT' }, (response) => {
      resolve(response?.dataUrl);
    });
  });
}

// LinkedIn Batch Auto-Apply Loop
async function runBatchAutoApplyLoop(shouldContinue: () => boolean, log: (msg: string) => void) {
  if (!window.location.href.includes('linkedin.com')) {
    log('⚠️ Batch loop only active on LinkedIn jobs pages.');
    return;
  }
  log('🚀 Starting LinkedIn Easy Apply Batch Loop...');

  chrome.storage.local.get(['appliedCount', 'skippedCount', 'blacklistKeywords'], async (items) => {
    let appliedCount = items.appliedCount || 0;
    let skippedCount = items.skippedCount || 0;
    const blacklist = (items.blacklistKeywords || '')
      .split(',')
      .map((s: string) => s.trim().toLowerCase())
      .filter(Boolean);

    while (shouldContinue()) {
      if (checkLinkedInDailyLimit()) {
        log('🚫 LinkedIn Daily Application limit reached. Stopping loop.');
        alert('🚫 LinkedIn Daily Easy Apply limit reached. Pausing batch loop.');
        chrome.storage.local.set({ isAutoRunning: false });
        break;
      }

      const jobCards = document.querySelectorAll('li[data-occludable-job-id], .jobs-search-results__list-item');
      if (jobCards.length === 0) {
        log('No job cards found on current view. Waiting 4s...');
        await new Promise((r) => setTimeout(r, 4000));
        continue;
      }

      log(`Found ${jobCards.length} job cards on current page.`);

      for (let i = 0; i < jobCards.length; i++) {
        if (!shouldContinue()) break;
        const card = jobCards[i];
        const title = (
          card.querySelector('.job-card-list__title, .artdeco-entity-lockup__title')?.textContent || ''
        ).toLowerCase();

        if (blacklist.some((word: string) => title.includes(word))) {
          log(`Skipping blacklisted job: "${title.slice(0, 30)}..."`);
          skippedCount++;
          chrome.storage.local.set({ skippedCount });
          continue;
        }

        const link = card.querySelector<HTMLAnchorElement>('a');
        if (link) {
          link.click();
          await new Promise((r) => setTimeout(r, 1200));
        }

        const easyApplyBtn = document.querySelector<HTMLButtonElement>('button.jobs-apply-button[aria-label*="Easy"]');
        if (!easyApplyBtn) {
          skippedCount++;
          chrome.storage.local.set({ skippedCount });
          continue;
        }

        easyApplyBtn.click();
        await new Promise((r) => setTimeout(r, 1500));

        await runAutofillSequence();
        await new Promise((r) => setTimeout(r, 1500));

        // Submit or Discard
        const submitBtn = document.querySelector<HTMLButtonElement>('button[aria-label*="Submit application"]');
        if (submitBtn) {
          submitBtn.click();
          log('✅ Application submitted successfully!');
          appliedCount++;
          chrome.storage.local.set({ appliedCount });
          await new Promise((r) => setTimeout(r, 2000));
        } else {
          await discardLinkedInModal();
          skippedCount++;
          chrome.storage.local.set({ skippedCount });
        }
      }

      log('Finished processing current visible list.');
      break;
    }
  });
}
