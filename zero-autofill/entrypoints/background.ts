import { defineBackground } from 'wxt/sandbox';

export default defineBackground(() => {
  console.log('[Job Finder ATS Tailor Background Service Worker Active]');

  // Open side panel when extension icon is clicked
  chrome.action.onClicked.addListener(async (tab) => {
    if (tab.id) {
      try {
        await chrome.sidePanel.open({ tabId: tab.id });
      } catch (e) {
        console.warn('Could not open sidePanel:', e);
      }
    }
  });

  // Automatically enable sidePanel on all tabs
  try {
    (chrome.sidePanel as any)?.setPanelBehavior?.({ openPanelOnActionClick: true });
  } catch (e) {}

  // Listen for messages from Content Script or Sidepanel UI
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'GET_TAB_INFO') {
      sendResponse({ tabId: sender.tab?.id, url: sender.tab?.url });
      return true;
    }

    if (message.action === 'GET_BACKEND_HEALTH') {
      chrome.storage.local.get(['backendBaseUrl'], (items) => {
        const baseUrl = items.backendBaseUrl || 'http://127.0.0.1:8000';
        fetch(`${baseUrl}/healthz`)
          .then((res) => {
            const ct = res.headers.get('content-type') || '';
            if (ct.includes('application/json')) return res.json();
            return { status: 'healthy', note: 'reachable' };
          })
          .then((data) => sendResponse({ success: true, data }))
          .catch((err) => sendResponse({ success: false, error: err.message }));
      });
      return true;
    }

    if (message.action === 'CAPTURE_TAB_SCREENSHOT') {
      const windowId = sender.tab?.windowId;
      chrome.tabs.captureVisibleTab(windowId || chrome.windows.WINDOW_ID_CURRENT, { format: 'jpeg', quality: 80 }, (dataUrl) => {
        if (chrome.runtime.lastError) {
          console.warn('[Background] Screenshot error:', chrome.runtime.lastError.message);
          sendResponse({ success: false, error: chrome.runtime.lastError.message });
        } else {
          sendResponse({ success: true, dataUrl });
        }
      });
      return true;
    }

    return true;
  });
});
