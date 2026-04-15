/**
 * Content script - Runs on Canvas pages and extracts assignment information
 */

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'getAssignmentData') {
    const data = extractAssignmentData();
    sendResponse(data);
  }
});

/**
 * Extract assignment data from current Canvas page
 * Returns null if this is not an assignment page
 */
function extractAssignmentData() {
  // Check if we're on an assignment detail page
  const assignmentTitle = extractTitle();
  const assignmentDescription = extractDescription();
  const courseInfo = extractCourseInfo();

  // If no title found, we're probably not on an assignment page
  if (!assignmentTitle) {
    return null;
  }

  return {
    title: assignmentTitle,
    description: assignmentDescription,
    context: extractContext(),
    courseName: courseInfo.name,
    courseId: courseInfo.id,
    assignmentId: extractAssignmentId()
  };
}

/**
 * Extract assignment title from page
 */
function extractTitle() {
  // Try different selectors for Canvas pages
  let title = null;

  // Canvas assignment page selectors
  const selectors = [
    'h1[class*="title"]',
    '.assignment-title',
    'h1.page_title',
    'h1',
    '.student_assignment_title',
    'h2.title'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      title = el.textContent.trim();
      break;
    }
  }

  return title;
}

/**
 * Extract assignment description/instructions
 */
function extractDescription() {
  let description = '';

  // Try different selectors for assignment content
  const selectors = [
    '.description',
    '[data-testid="assignment-description"]',
    '.assignment-description',
    '.submission_essay_content',
    '.user_content'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      description = el.textContent.trim();
      break;
    }
  }

  // Fallback: get all text from main content area
  if (!description) {
    const main = document.querySelector('main, [role="main"], .container');
    if (main) {
      description = main.textContent.trim();
      // Limit to reasonable length
      description = description.substring(0, 2000);
    }
  }

  return description;
}

/**
 * Extract context (course materials, reading materials if available)
 */
function extractContext() {
  let context = '';

  // Try to find links to course materials
  const materialSelectors = [
    'a[href*="files"]',
    'a[href*="modules"]',
    '.attachment a',
    '.file-download'
  ];

  const materials = [];
  for (const selector of materialSelectors) {
    const elements = document.querySelectorAll(selector);
    elements.forEach(el => {
      const text = el.textContent.trim();
      if (text && text.length < 200) {
        materials.push(text);
      }
    });
  }

  if (materials.length > 0) {
    context = 'Related materials: ' + materials.slice(0, 5).join(', ');
  }

  return context;
}

/**
 * Extract course information
 */
function extractCourseInfo() {
  let name = 'Unknown Course';
  let id = null;

  // Try to extract from URL
  const courseMatch = window.location.pathname.match(/\/courses\/(\d+)/);
  if (courseMatch) {
    id = parseInt(courseMatch[1]);
  }

  // Try to extract course name from breadcrumbs or header
  const breadcrumb = document.querySelector('[role="navigation"] a[href*="/courses/"]');
  if (breadcrumb) {
    name = breadcrumb.textContent.trim();
  } else {
    // Fallback: look for course code or name in page
    const headerText = document.querySelector('h1, .page-title');
    if (headerText) {
      const text = headerText.textContent;
      const codeMatch = text.match(/([A-Z]{2,4}\s*\d{3})/);
      if (codeMatch) {
        name = codeMatch[1];
      }
    }
  }

  return { name, id };
}

/**
 * Extract assignment ID from URL or page data
 */
function extractAssignmentId() {
  // Try URL pattern: /assignments/123
  const match = window.location.pathname.match(/\/assignments\/(\d+)/);
  if (match) {
    return parseInt(match[1]);
  }

  // Try data attributes
  const assignmentEl = document.querySelector('[data-assignment-id]');
  if (assignmentEl) {
    return parseInt(assignmentEl.getAttribute('data-assignment-id'));
  }

  return null;
}

// Expose function for testing
window.extractAssignmentData = extractAssignmentData;
