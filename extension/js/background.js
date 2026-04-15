/**
 * Background service worker - Minimal setup needed for session-based auth
 */

// Listen for extension install/update
chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === 'install') {
    // Show welcome message
    console.log('Canvas AI Helper installed! No setup needed - just use it on Canvas pages.');
  }
});

// That's it! No token management needed with session-based auth.
