/**
 * Content script - Intelligent Canvas page detector and data extractor
 *
 * Supports:
 * - Assignment submission pages
 * - Quiz intro pages
 * - Quiz question pages (multiple choice, text entry, matching)
 */

// Listen for messages from popup
chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (request.action === 'getAssignmentData') {
    const data = extractCanvasPageData();
    sendResponse(data);
  }
});

/**
 * Main entry point - detect page type and extract appropriate data
 */
function extractCanvasPageData() {
  const pageType = detectPageType();

  switch (pageType) {
    case 'assignment_submission':
      return extractAssignmentData();
    case 'quiz_intro':
      return extractQuizIntroData();
    case 'quiz_question':
      return extractQuizQuestionData();
    case 'unknown':
    default:
      return null;
  }
}

/**
 * Detect which type of Canvas page we're on
 */
function detectPageType() {
  const pathname = window.location.pathname;

  // Assignment submission page: /courses/{id}/assignments/{id}
  if (pathname.match(/\/courses\/\d+\/assignments\/\d+/)) {
    return 'assignment_submission';
  }

  // Quiz intro page: /courses/{id}/quizzes/{id}
  // Check for "Take the Quiz" or "Start the quiz" button
  if (pathname.match(/\/courses\/\d+\/quizzes\/\d+/)) {
    const takeQuizBtn = document.querySelector(
      'a[href*="/take"],' +
      'button:contains("Take"),' +
      '.btn:contains("Take the Quiz"),' +
      '[data-testid="start-quiz-button"]'
    );

    // Also check for quiz intro content (title + instructions + questions count)
    const hasQuizIntroContent = !!document.querySelector(
      '.quiz-header, [data-testid="quiz-header"], .quiz-info'
    );

    if (takeQuizBtn || hasQuizIntroContent ||
        !document.querySelector('.question-text, [data-testid="question"], .question-main')) {
      return 'quiz_intro';
    }

    return 'quiz_question';
  }

  // Quiz question page: Within quiz attempt
  if (pathname.match(/\/courses\/\d+\/quizzes\/\d+\/take/)) {
    return 'quiz_question';
  }

  return 'unknown';
}

/**
 * Extract assignment submission page data
 */
function extractAssignmentData() {
  const title = extractAssignmentTitle();
  const description = extractAssignmentDescription();
  const courseInfo = extractCourseInfo();
  const dueDate = extractDueDate();
  const attachments = extractAttachments();

  if (!title) {
    return null; // Not a valid assignment page
  }

  return {
    pageType: 'assignment_submission',
    title,
    description,
    dueDate,
    attachments,
    courseName: courseInfo.name,
    courseId: courseInfo.id,
    assignmentId: extractAssignmentId()
  };
}

function extractAssignmentTitle() {
  // Try different selectors for Canvas assignment title
  const selectors = [
    'h1[class*="title"]',
    '.assignment-title',
    'h1.page_title',
    '[data-testid="assignment-title"] h1',
    '.student_assignment_title',
    'h2.title'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim();
    }
  }

  return null;
}

function extractAssignmentDescription() {
  // Try different selectors for assignment content/description
  const selectors = [
    '.description',
    '[data-testid="assignment-description"]',
    '.assignment-description',
    '.submission_essay_content',
    '.user_content',
    '.assignment-content'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim().substring(0, 3000);
    }
  }

  // Fallback: get main content
  const main = document.querySelector('main, [role="main"], .container');
  if (main) {
    return main.textContent.trim().substring(0, 3000);
  }

  return '';
}

function extractDueDate() {
  const selectors = [
    '[data-testid="due-date"]',
    '.due-date',
    '.assignment-due-date'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim();
    }
  }

  return null;
}

function extractAttachments() {
  const attachments = [];
  const linkSelectors = 'a[href*="/files"], a[href*="/download"], .attachment a';

  document.querySelectorAll(linkSelectors).forEach(link => {
    const text = link.textContent.trim();
    if (text && text.length < 200) {
      attachments.push(text);
    }
  });

  return attachments.slice(0, 5); // Limit to 5
}

function extractAssignmentId() {
  const match = window.location.pathname.match(/\/assignments\/(\d+)/);
  return match ? parseInt(match[1]) : null;
}

/**
 * Extract quiz intro page data
 */
function extractQuizIntroData() {
  const title = extractQuizTitle();
  const questionCount = extractQuestionCount();
  const instructions = extractQuizInstructions();
  const courseInfo = extractCourseInfo();

  if (!title) {
    return null; // Not a valid quiz intro
  }

  return {
    pageType: 'quiz_intro',
    title,
    questionCount,
    instructions,
    courseName: courseInfo.name,
    courseId: courseInfo.id,
    quizId: extractQuizId(),
    needsStart: true,
    status: 'Please click "Take the Quiz" to start'
  };
}

function extractQuizTitle() {
  const selectors = [
    'h1',
    '[data-testid="quiz-title"]',
    '.quiz-title',
    '.page-title'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim() && el.textContent.includes('Quiz')) {
      return el.textContent.trim();
    }
  }

  return null;
}

function extractQuestionCount() {
  // Look for text like "5 questions" or "Questions: 5"
  const text = document.body.innerText;
  const match = text.match(/(\d+)\s+questions?/i);
  return match ? parseInt(match[1]) : null;
}

function extractQuizInstructions() {
  const selectors = [
    '.quiz-instructions',
    '[data-testid="quiz-instructions"]',
    '.quiz-info-body',
    '[role="region"]'
  ];

  for (const selector of selectors) {
    const el = document.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim().substring(0, 1000);
    }
  }

  return '';
}

function extractQuizId() {
  const match = window.location.pathname.match(/\/quizzes\/(\d+)/);
  return match ? parseInt(match[1]) : null;
}

/**
 * Extract quiz question page data
 */
function extractQuizQuestionData() {
  const currentQuestion = extractCurrentQuestion();
  const courseInfo = extractCourseInfo();

  if (!currentQuestion) {
    return null; // No valid question found
  }

  return {
    pageType: 'quiz_question',
    ...currentQuestion,
    courseName: courseInfo.name,
    courseId: courseInfo.id,
    quizId: extractQuizId()
  };
}

function extractCurrentQuestion() {
  // Try to find the current question
  const questionContainer = document.querySelector(
    '.question, [data-testid="question"], .question-main, [data-testid="question-wrapper"]'
  );

  if (!questionContainer) {
    return null;
  }

  const text = extractQuestionText(questionContainer);
  const questionType = detectQuestionType(questionContainer);
  const options = extractOptions(questionContainer);

  if (!text) {
    return null;
  }

  return {
    text,
    type: questionType,
    options,
    status: `Quiz question detected (${questionType})`
  };
}

function extractQuestionText(container) {
  const selectors = [
    '.question-text',
    '[data-testid="question-text"]',
    '.question-title',
    '.question_text'
  ];

  for (const selector of selectors) {
    const el = container.querySelector(selector);
    if (el && el.textContent.trim()) {
      return el.textContent.trim();
    }
  }

  // Fallback: get first substantial text
  const text = container.textContent.trim();
  return text.substring(0, 500) || null;
}

function detectQuestionType(container) {
  // Check for multiple choice
  if (container.querySelector('input[type="radio"]')) {
    return 'multiple_choice';
  }

  // Check for checkboxes (multiple select)
  if (container.querySelector('input[type="checkbox"]')) {
    return 'multiple_select';
  }

  // Check for text input/textarea
  if (container.querySelector('input[type="text"], textarea, [contenteditable="true"]')) {
    return 'text_entry';
  }

  // Check for matching/drag-and-drop
  if (container.querySelector('[data-testid="matching"], .matching-question')) {
    return 'matching';
  }

  // Check for select dropdowns
  if (container.querySelector('select')) {
    return 'dropdown';
  }

  return 'unknown';
}

function extractOptions(container) {
  const options = [];

  // Multiple choice or checkboxes
  const inputs = container.querySelectorAll('input[type="radio"], input[type="checkbox"]');
  if (inputs.length > 0) {
    inputs.forEach(input => {
      const label = input.closest('label');
      if (label) {
        const text = label.textContent.trim();
        options.push({
          value: input.value,
          text,
          checked: input.checked
        });
      }
    });
  }

  // Dropdown options
  const selects = container.querySelectorAll('select');
  if (selects.length > 0) {
    selects.forEach(select => {
      Array.from(select.options).forEach(opt => {
        if (opt.value) {
          options.push({
            value: opt.value,
            text: opt.text,
            selected: opt.selected
          });
        }
      });
    });
  }

  return options;
}

function extractCourseInfo() {
  let name = 'Unknown Course';
  let id = null;

  // Extract from URL
  const courseMatch = window.location.pathname.match(/\/courses\/(\d+)/);
  if (courseMatch) {
    id = parseInt(courseMatch[1]);
  }

  // Try breadcrumbs
  const breadcrumb = document.querySelector(
    '[role="navigation"] a[href*="/courses/"],' +
    '.breadcrumb a[href*="/courses/"]'
  );
  if (breadcrumb) {
    name = breadcrumb.textContent.trim();
  }

  return { name, id };
}

// Export for debugging
window.extractCanvasPageData = extractCanvasPageData;
window.detectPageType = detectPageType;
window.extractAssignmentData = extractAssignmentData;
window.extractQuizIntroData = extractQuizIntroData;
window.extractQuizQuestionData = extractQuizQuestionData;
