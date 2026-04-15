/**
 * Background service worker - Handles extension lifecycle and storage
 */

// Listen for extension install/update
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // Open settings page on first install
    chrome.runtime.openOptionsPage();
  }
});

// Listen for messages from content scripts or popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'checkAuth') {
    chrome.storage.local.get(['authToken'], (result) => {
      sendResponse({ hasToken: !!result.authToken });
    });
    return true; // Keep channel open for async response
  }

  if (request.action === 'saveToken') {
    chrome.storage.local.set({ authToken: request.token }, () => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (request.action === 'clearToken') {
    chrome.storage.local.remove('authToken', () => {
      sendResponse({ success: true });
    });
    return true;
  }
});

// Keep service worker alive (Manifest V3 requirement)
// Service workers go idle after 5 minutes, but we'll let it
// as this extension doesn't need constant background activity
