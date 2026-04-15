/**
 * Settings page script - Handles token management
 */

// Load saved token on page load
document.addEventListener('DOMContentLoaded', () => {
  loadToken();
});

/**
 * Load token from storage and display it
 */
function loadToken() {
  chrome.storage.local.get(['authToken'], (result) => {
    if (result.authToken) {
      document.getElementById('auth-token').value = result.authToken;
    }
  });
}

/**
 * Save token to storage
 */
document.getElementById('save-btn').addEventListener('click', () => {
  const token = document.getElementById('auth-token').value.trim();

  if (!token) {
    showStatus('Please enter your auth token', 'error');
    return;
  }

  // Basic validation: token should be reasonably long (at least 20 chars)
  if (token.length < 20) {
    showStatus('Token appears to be invalid. Please check and try again.', 'error');
    return;
  }

  chrome.storage.local.set({ authToken: token }, () => {
    showStatus('✓ Token saved successfully! You can now use the extension.', 'success');
  });
});

/**
 * Clear token from storage
 */
document.getElementById('clear-btn').addEventListener('click', () => {
  if (confirm('Are you sure? You\'ll need to enter your token again to use the extension.')) {
    chrome.storage.local.remove('authToken', () => {
      document.getElementById('auth-token').value = '';
      showStatus('✓ Token cleared', 'success');
    });
  }
});

/**
 * Show status message
 */
function showStatus(message, type = 'success') {
  const status = document.getElementById('status-message');
  status.textContent = message;
  status.className = `status show ${type}`;

  // Auto-hide success messages after 5 seconds
  if (type === 'success') {
    setTimeout(() => {
      status.classList.remove('show');
    }, 5000);
  }
}
