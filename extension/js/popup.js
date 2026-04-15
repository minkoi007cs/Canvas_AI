/**
 * Popup script - Uses browser session (cookies) for authentication
 * No token setup needed!
 */

const API_BASE = 'https://canvas-ai.herokuapp.com';
let currentDraft = null;
let currentPageType = null;

// State management
async function initialize() {
  // Check if we're on a supported Canvas page
  const pageData = await getPageData();

  if (!pageData) {
    showState('no-assignment');
    return;
  }

  // Show page type specific state
  currentPageType = pageData.pageType;

  switch (pageData.pageType) {
    case 'assignment_submission':
      showState('assignment-detected');
      generateDraft(pageData);
      break;

    case 'quiz_intro':
      showState('quiz-intro-detected');
      displayQuizIntroInfo(pageData);
      break;

    case 'quiz_question':
      showState('quiz-question-detected');
      generateDraft(pageData);
      break;

    default:
      showState('no-assignment');
  }
}

// Get page data from content script
async function getPageData() {
  try {
    const response = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!response || response.length === 0) {
      return null;
    }

    const tabId = response[0].id;
    const message = await chrome.tabs.sendMessage(tabId, { action: 'getAssignmentData' }).catch(() => null);

    return message || null;
  } catch (e) {
    console.error('Error getting page data:', e);
    return null;
  }
}

// Display quiz intro info
function displayQuizIntroInfo(pageData) {
  const titleEl = document.querySelector('#quiz-title');
  const infoEl = document.querySelector('#quiz-info');

  if (titleEl) {
    titleEl.textContent = pageData.title || 'Quiz';
  }

  if (infoEl) {
    let info = '';
    if (pageData.questionCount) {
      info += `${pageData.questionCount} questions`;
    }
    if (pageData.instructions) {
      info += `\n${pageData.instructions.substring(0, 100)}...`;
    }
    infoEl.textContent = info || 'Please start the quiz to answer questions';
  }
}

// Generate AI draft using session authentication
async function generateDraft(pageData) {
  showState('loading');

  try {
    const response = await fetch(`${API_BASE}/api/assignment/complete`, {
      method: 'POST',
      credentials: 'include', // Include cookies for session auth
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        assignment_title: pageData.title || 'Untitled',
        assignment_description: getDescriptionForPageType(pageData),
        context: pageData.context || '',
        course_name: pageData.courseName || 'Unknown Course',
        course_id: pageData.courseId,
        assignment_id: pageData.assignmentId || pageData.quizId
      })
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      if (response.status === 401) {
        throw new Error('Please log in to the web app first');
      }
      throw new Error(error.error || `API error: ${response.status}`);
    }

    const data = await response.json();
    currentDraft = {
      title: pageData.title,
      description: getDescriptionForPageType(pageData),
      content: data.draft,
      draftId: data.draft_id,
      pageType: pageData.pageType
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

// Get description based on page type
function getDescriptionForPageType(pageData) {
  switch (pageData.pageType) {
    case 'assignment_submission':
      return pageData.description || '';

    case 'quiz_question':
      return `Question: ${pageData.text || ''}\n${pageData.options ? 'Options: ' + pageData.options.map(o => o.text).join(', ') : ''}`;

    case 'quiz_intro':
      return pageData.instructions || '';

    default:
      return '';
  }
}

// Display draft in popup
function displayDraft(draft) {
  const titleEl = document.getElementById('assignment-title');
  const contentEl = document.getElementById('draft-content');

  if (titleEl) {
    titleEl.textContent = draft.title || 'Draft';
  }

  if (contentEl) {
    const preview = draft.content.substring(0, 300);
    contentEl.textContent = preview + (draft.content.length > 300 ? '...' : '');
  }
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
