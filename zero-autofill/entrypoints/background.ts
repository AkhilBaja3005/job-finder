import { defineBackground } from 'wxt/sandbox';

export default defineBackground(() => {
  console.log('[Zero-Autofill Background Service Worker Active]');

  // Open side panel when extension icon is clicked
  chrome.action.onClicked.addListener(async (tab) => {
    if (tab.id) {
      await chrome.sidePanel.open({ tabId: tab.id });
    }
  });

  // Listen for messages from Content Script or Sidepanel UI
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'GET_TAB_INFO') {
      sendResponse({ tabId: sender.tab?.id, url: sender.tab?.url });
      return true;
    }

    if (message.action === 'CAPTURE_TAB_SCREENSHOT') {
      const windowId = sender.tab?.windowId;
      chrome.tabs.captureVisibleTab(windowId || chrome.windows.WINDOW_ID_CURRENT, { format: 'jpeg', quality: 80 }, (dataUrl) => {
        if (chrome.runtime.lastError) {
          console.warn('[Zero-Autofill Background] Screenshot error:', chrome.runtime.lastError.message);
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
