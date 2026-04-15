/**
 * Popup script - Handles the UI and interaction in the extension popup
 */

const API_BASE = 'https://canvas-ai.herokuapp.com';
let currentDraft = null;

// State management
async function initialize() {
  const token = await getStoredToken();

  if (!token) {
    showState('not-authenticated');
    return;
  }

  // Check if we can get assignment data from current page
  const assignmentData = await getAssignmentData();

  if (!assignmentData) {
    showState('no-assignment');
    return;
  }

  // Proceed to generate draft
  generateDraft(token, assignmentData);
}

// Get auth token from storage
async function getStoredToken() {
  const data = await chrome.storage.local.get(['authToken']);
  return data.authToken || null;
}

// Get assignment data from page via content script
async function getAssignmentData() {
  try {
    // Send message to content script to get assignment data
    const response = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!response || response.length === 0) {
      return null;
    }

    const tabId = response[0].id;
    const message = await chrome.tabs.sendMessage(tabId, { action: 'getAssignmentData' }).catch(() => null);

    return message || null;
  } catch (e) {
    console.error('Error getting assignment data:', e);
    return null;
  }
}

// Generate AI draft
async function generateDraft(token, assignmentData) {
  showState('loading');

  try {
    const response = await fetch(`${API_BASE}/api/assignment/complete`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        auth_token: token,
        assignment_title: assignmentData.title || 'Untitled',
        assignment_description: assignmentData.description || '',
        context: assignmentData.context || '',
        course_name: assignmentData.courseName || 'Unknown Course',
        course_id: assignmentData.courseId,
        assignment_id: assignmentData.assignmentId
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.error || `API error: ${response.status}`);
    }

    const data = await response.json();
    currentDraft = {
      title: assignmentData.title,
      description: assignmentData.description,
      content: data.draft,
      draftId: data.draft_id
    };

    showState('success');
    displayDraft(currentDraft);
  } catch (error) {
    console.error('Error generating draft:', error);
    showState('error');
    document.getElementById('error-message').textContent =
      error.message || 'Failed to generate draft. Please try again.';
  }
}

// Display draft in popup
function displayDraft(draft) {
  document.getElementById('assignment-title').textContent = draft.title || 'Assignment';
  document.getElementById('draft-content').textContent =
    draft.content.substring(0, 300) + (draft.content.length > 300 ? '...' : '');
}

// Copy draft to clipboard
function copyToClipboard(text) {
  navigator.clipboard.writeText(text).then(() => {
    showNotification('Copied to clipboard!');
  }).catch((err) => {
    showNotification('Failed to copy', 'error');
    console.error('Clipboard error:', err);
  });
}

// Show notification
function showNotification(message, type = 'success') {
  // You could implement a toast notification here
  console.log(`[${type}] ${message}`);
}

// State management
function showState(stateName) {
  document.querySelectorAll('.state').forEach(el => {
    el.classList.add('hidden');
  });
  const state = document.getElementById(stateName);
  if (state) {
    state.classList.remove('hidden');
  }
}

// Modal functions
function openModal(title, content) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').textContent = content;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
}

// Event listeners
document.getElementById('setup-btn')?.addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById('close-btn')?.addEventListener('click', () => {
  window.close();
});

document.getElementById('copy-btn')?.addEventListener('click', () => {
  if (currentDraft) {
    copyToClipboard(currentDraft.content);
  }
});

document.getElementById('view-full-btn')?.addEventListener('click', () => {
  if (currentDraft) {
    openModal(currentDraft.title, currentDraft.content);
  }
});

document.getElementById('modal-close-btn')?.addEventListener('click', closeModal);

document.getElementById('modal-copy-btn')?.addEventListener('click', () => {
  if (currentDraft) {
    copyToClipboard(currentDraft.content);
  }
});

document.getElementById('retry-btn')?.addEventListener('click', () => {
  initialize();
});

// Click outside modal to close
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
  if (e.target === document.getElementById('modal-overlay')) {
    closeModal();
  }
});

// Initialize on load
document.addEventListener('DOMContentLoaded', initialize);
