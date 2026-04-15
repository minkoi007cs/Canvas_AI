# Canvas AI Helper - Testing Guide

## Installation for Testing

1. **Load Extension in Chrome**
   - Open `chrome://extensions/`
   - Enable "Developer mode" (top right)
   - Click "Load unpacked"
   - Select the `extension/` folder

2. **Get Auth Token**
   - Visit your web app (local: `http://localhost:8080` or deployed)
   - Log in with Google
   - Go to `/settings` page
   - Copy your extension auth token

3. **Configure Extension**
   - Right-click extension icon → Options
   - Paste your auth token
   - Click "Save Token"
   - You should see: "✓ Token saved successfully!"

## Page Detection Testing

The extension now detects 3 types of Canvas pages:

### 1. Assignment Submission Pages
**URL Pattern**: `/courses/{id}/assignments/{id}`

**Expected Behavior**:
- Icon appears in toolbar
- Click icon → popup shows "Assignment Detected"
- Spinner appears → "Analyzing assignment..."
- After a few seconds → Draft appears with "Copy to Clipboard" button

**Debug**: Open DevTools (F12) → Console tab → type:
```javascript
window.extractAssignmentData()
// Should return: {pageType: 'assignment_submission', title: '...', ...}
```

---

### 2. Quiz Intro Pages
**URL Pattern**: `/courses/{id}/quizzes/{id}` (before starting)

**Expected Behavior**:
- Icon appears in toolbar
- Click icon → popup shows "Quiz Found"
- Message: "Please click 'Take the Quiz' to start answering questions"
- No draft generation yet (you must start the quiz first)

**Debug**: Open DevTools (F12) → Console:
```javascript
window.detectPageType()
// Should return: 'quiz_intro'

window.extractQuizIntroData()
// Should return: {pageType: 'quiz_intro', title: '...', questionCount: N, ...}
```

---

### 3. Quiz Question Pages
**URL Pattern**: `/courses/{id}/quizzes/{id}/take` (while answering)

**Expected Behavior**:
- Icon appears in toolbar
- Click icon → popup shows "Quiz Question Detected"
- Spinner appears → "Analyzing question..."
- After a few seconds → Answer suggestion appears
- Can copy and paste into answer field

**Debug**: Open DevTools:
```javascript
window.detectPageType()
// Should return: 'quiz_question'

window.extractQuizQuestionData()
// Should return: {
//   pageType: 'quiz_question',
//   text: 'Question text...',
//   type: 'multiple_choice' | 'text_entry' | 'matching' | 'dropdown',
//   options: [{text: '...', value: '...'}, ...],
//   ...
// }
```

---

## Question Type Detection

The extension detects these question types:

| Type | Detection | Handling |
|------|-----------|----------|
| **multiple_choice** | Radio buttons (`<input type="radio">`) | Works great ✓ |
| **text_entry** | Text input or textarea | Works great ✓ |
| **dropdown** | Select elements (`<select>`) | Works great ✓ |
| **matching** | Special matching question UI | Detects but draft only, no auto-fill yet |
| **checkbox** | Multiple checkboxes | Detects as multiple_select |

---

## Debugging Checklist

If popup is blank or shows wrong state:

1. **Check token**
   - Open extension options → Should show your token
   - If blank: Paste token again

2. **Check page type**
   - Press F12 → Console → `window.detectPageType()`
   - If `'unknown'`: URL doesn't match Canvas pattern

3. **Check data extraction**
   - For assignment: `window.extractAssignmentData()`
   - For quiz intro: `window.extractQuizIntroData()`
   - For quiz question: `window.extractQuizQuestionData()`

4. **Check API communication**
   - Open DevTools → Network tab
   - Click extension icon
   - Look for POST request to `/api/assignment/complete`
   - Check response: Should be `{draft: "...", draft_id: ...}`

5. **Check popup state**
   - If showing wrong state, check `window.currentPageType`
   - Should be: `'assignment_submission'`, `'quiz_intro'`, or `'quiz_question'`

---

## Common Issues

### Popup shows "Not on a Supported Page"
- **Cause**: URL doesn't match Canvas pattern
- **Fix**: Make sure you're on:
  - `/courses/123/assignments/456` (assignment)
  - `/courses/123/quizzes/456` (quiz intro/question)

### Popup shows "Quiz Found" but doesn't generate draft
- **Cause**: You're on quiz intro page (needs to start quiz first)
- **Fix**: Click "Take the Quiz" button, then try extension again

### Popup blank / nothing happens
- **Cause**: Extension not configured or API error
- **Fix**: 
  1. Check DevTools Console for errors
  2. Run `window.detectPageType()` to verify page detection
  3. Run `window.extractCanvasPageData()` to verify data extraction

### "Failed to generate draft" error
- **Cause**: API error or invalid token
- **Fix**:
  1. Check DevTools → Network → look for 401/403 response
  2. Re-paste token in extension options
  3. Try again

---

## Testing Scenarios

### Scenario 1: Assignment Submission
1. Navigate to any assignment page
2. Click extension icon
3. **Expected**: Shows draft in 2-3 seconds
4. **Verify**: Can copy draft to clipboard

### Scenario 2: Quiz Intro
1. Navigate to quiz page (before clicking "Take the Quiz")
2. Click extension icon
3. **Expected**: Shows "Quiz Found" message
4. **Verify**: Doesn't try to generate draft yet

### Scenario 3: Quiz Question (Multiple Choice)
1. Start a quiz (click "Take the Quiz")
2. On any multiple choice question
3. Click extension icon
4. **Expected**: Shows answer suggestion
5. **Verify**: Answer is one of the multiple choice options

### Scenario 4: Quiz Question (Text Entry)
1. Start a quiz
2. On text entry question
3. Click extension icon
4. **Expected**: Shows text answer suggestion
5. **Verify**: Can copy and paste into text field

---

## Performance

- **Page detection**: <10ms
- **Data extraction**: <50ms
- **API call**: 2-5 seconds (depends on API/Claude response)
- **Total popup load**: <100ms before API call

---

## Future Testing (Auto-Fill)

Once detection and extraction is solid, we can add:

1. **Auto-fill radio buttons** (multiple choice)
   - Find matching option by text
   - Click radio button automatically

2. **Auto-fill dropdowns**
   - Match answer text to option
   - Set dropdown value

3. **Auto-fill text fields**
   - Insert generated text into textarea
   - Highlight for review before submit

These are Phase 6+ improvements after core extension works.

---

## Contact & Debugging

If extension still not working:

1. **Share DevTools output**:
   - Open DevTools → Console
   - Type: `window.extractCanvasPageData()`
   - Copy result

2. **Check error messages**:
   - DevTools → Console → look for red errors
   - DevTools → Network → look for failed requests

3. **Browser compatibility**:
   - Currently tested on: Chrome 90+
   - Firefox support coming in v1.1
