import { defineContentScript } from 'wxt/sandbox';
import { getProfile, getSettings, db } from '../modules/storage/db';
import { autofillGreenhouse } from '../modules/adapters/greenhouse';
import { autofillLever } from '../modules/adapters/lever';
import { autofillWorkday } from '../modules/adapters/workday';
import { autofillAshby } from '../modules/adapters/ashby';
import { autofillUniversal } from '../modules/adapters/universal';
import { batchSolvePageQuestions } from '../modules/ai/page-analyzer';
import { generateFieldAnswer } from '../modules/ai/client';
import { fillNativeInput } from '../modules/adapters/base-adapter';

export default defineContentScript({
  matches: ['<all_urls>'],
  main() {
    console.log('[Zero-Autofill Content Script Active]');

    // Inject Floating Action Trigger
    injectFloatingWidget();

    // Listen for manual trigger commands from Sidepanel
    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
      if (request.action === 'RUN_AUTOFILL') {
        runAutofillSequence().then((count) => {
          sendResponse({ success: true, count });
        });
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
    window.addEventListener('submit', async (e) => {
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
        console.log('[Zero-Autofill] Logged application submission automatically to IndexedDB.');
      }
    }, true);
  }
});

async function runAutofillSequence(): Promise<number> {
  const profile = await getProfile();
  if (!profile) {
    alert('Please fill out your Candidate Profile in the Zero-Autofill Sidepanel first!');
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
  }
  
  // Secondary pass: run universal autofill to catch any remaining inputs
  filled += autofillUniversal(profile);

  // Inject inline AI Answer buttons on unfilled custom textareas
  injectInlineAIButtons(profile);

  return filled;
}

function injectFloatingWidget() {
  if (document.getElementById('zero-autofill-widget')) return;

  const btn = document.createElement('button');
  btn.id = 'zero-autofill-widget';
  btn.innerHTML = 'Zero-Autofill';
  btn.style.cssText = `
    position: fixed;
    bottom: 24px;
    right: 24px;
    z-index: 999999;
    background: linear-gradient(135deg, #0ea5e9, #6366f1);
    color: white;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 18px;
    border-radius: 9999px;
    border: 1px solid rgba(255, 255, 255, 0.3);
    box-shadow: 0 10px 25px rgba(14, 165, 233, 0.4);
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
  `;

  btn.addEventListener('mouseenter', () => {
    btn.style.transform = 'scale(1.05)';
  });
  btn.addEventListener('mouseleave', () => {
    btn.style.transform = 'scale(1)';
  });

  btn.addEventListener('click', async () => {
    btn.innerHTML = 'Filling...';
    const count = await runAutofillSequence();
    btn.innerHTML = `Filled ${count} fields`;
    setTimeout(() => {
      btn.innerHTML = 'Zero-Autofill';
    }, 3000);
  });

  document.body.appendChild(btn);
}

function injectInlineAIButtons(profile: any) {
  const textareas = document.querySelectorAll('textarea');
  textareas.forEach((ta) => {
    if (ta.nextElementSibling?.classList.contains('zero-ai-btn')) return;

    const label = ta.closest('label')?.textContent || ta.previousElementSibling?.textContent || 'Screening question';
    const aiBtn = document.createElement('button');
    aiBtn.className = 'zero-ai-btn';
    aiBtn.innerHTML = 'AI Answer';
    aiBtn.style.cssText = `
      display: inline-block;
      margin-top: 6px;
      background: rgba(99, 102, 241, 0.15);
      color: #6366f1;
      border: 1px solid rgba(99, 102, 241, 0.3);
      font-size: 11px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 6px;
      cursor: pointer;
    `;

    aiBtn.addEventListener('click', async (e) => {
      e.preventDefault();
      aiBtn.innerHTML = 'Generating...';
      const settings = await getSettings();
      const answer = await generateFieldAnswer(label, profile, settings);
      fillNativeInput(ta, answer);
      aiBtn.innerHTML = 'Answered';
    });

    ta.parentNode?.insertBefore(aiBtn, ta.nextSibling);
  });
}

/**
 * Capture full-page screenshot by stitching viewport slices onto an offscreen canvas
 */
async function captureFullPageScreenshot(): Promise<string | undefined> {
  try {
    const originalScrollTop = window.scrollY;
    const totalHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;

    // Fast path: if page fits in single viewport
    if (totalHeight <= viewportHeight + 50) {
      const res: any = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: 'CAPTURE_TAB_SCREENSHOT' }, resolve);
      });
      return res?.success ? res.dataUrl : undefined;
    }

    // Full page stitch: create canvas
    const canvas = document.createElement('canvas');
    const targetWidth = Math.min(viewportWidth, 1280);
    const scaleFactor = targetWidth / viewportWidth;
    canvas.width = targetWidth;
    canvas.height = Math.min(totalHeight * scaleFactor, 4000); // cap max height for performance

    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;

    let currentScroll = 0;
    while (currentScroll < totalHeight && currentScroll < 3600) {
      window.scrollTo(0, currentScroll);
      await new Promise((r) => setTimeout(r, 120)); // wait for rendering

      const res: any = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: 'CAPTURE_TAB_SCREENSHOT' }, resolve);
      });

      if (res?.success && res.dataUrl) {
        await new Promise((resolve) => {
          const img = new Image();
          img.onload = () => {
            const drawY = currentScroll * scaleFactor;
            ctx.drawImage(img, 0, drawY, targetWidth, viewportHeight * scaleFactor);
            resolve(true);
          };
          img.src = res.dataUrl;
        });
      }
      currentScroll += viewportHeight - 100;
    }

    // Restore candidate's scroll position
    window.scrollTo(0, originalScrollTop);

    return canvas.toDataURL('image/jpeg', 0.85);
  } catch (err) {
    console.warn('[Zero-Autofill] Full page capture fallback to single screenshot:', err);
    const res: any = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ action: 'CAPTURE_TAB_SCREENSHOT' }, resolve);
    });
    return res?.success ? res.dataUrl : undefined;
  }
}
