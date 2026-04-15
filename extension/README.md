# Canvas AI Helper - Browser Extension

AI-powered assignment draft generation directly from your Canvas assignments.

## Features

- 🎓 **Works on Canvas Pages**: Click the extension icon on any Canvas assignment
- 🤖 **AI-Powered**: Uses Claude AI to generate thoughtful assignment drafts
- 📋 **No Setup Required**: Works with your existing Canvas session
- 🔒 **Secure**: No passwords or credentials stored
- 💾 **Draft History**: All generated drafts are saved to your account
- ⚡ **Fast**: Get draft in seconds

## Installation

### For Development (Chrome)

1. Clone this repository
2. Open Chrome and go to `chrome://extensions/`
3. Enable "Developer mode" (top right)
4. Click "Load unpacked"
5. Select the `extension` folder
6. The extension should now appear in your Chrome toolbar

### For Firefox (Future)

This extension is built with Manifest V3, which is Chrome-primary. Firefox support can be added in v1.1.

## Setup

1. Navigate to [canvas-ai.herokuapp.com](https://canvas-ai.herokuapp.com)
2. Sign in with your Google account
3. Go to **Settings** → **Extension Setup**
4. Copy your auth token
5. Open the extension settings (right-click extension icon → Options)
6. Paste your token and click "Save Token"
7. You're ready to use!

## Usage

1. Open any Canvas assignment page
2. Click the **Canvas AI Helper** extension icon
3. The extension reads the assignment details
4. Click "Generate Draft" (or it auto-generates)
5. Review the AI draft in the popup
6. Click "Copy to Clipboard"
7. Paste into your Canvas submission form
8. Review and submit!

## Files

```
extension/
├── manifest.json          # Extension configuration
├── popup.html             # Popup UI
├── settings.html          # Settings page
├── js/
│   ├── popup.js          # Popup logic
│   ├── content.js        # Canvas page reader
│   ├── background.js     # Service worker
│   └── settings.js       # Settings logic
├── css/
│   ├── popup.css         # Popup styles
│   └── settings.css      # Settings styles
└── icons/                # Extension icons (add your own)
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

## How It Works

1. **Content Script** (`content.js`) runs on Canvas pages and extracts:
   - Assignment title
   - Assignment description/instructions
   - Course information
   - Any linked materials

2. **Popup** (`popup.js`) sends this data to the backend API:
   - Validates auth token
   - Sends assignment details to `/api/assignment/complete`
   - Receives AI-generated draft

3. **Backend** processes the request:
   - Validates extension auth token
   - Calls Claude AI with context
   - Returns draft to popup
   - Saves to draft history

4. **User** reviews and copies draft to Canvas manually

## Security

- ✅ No Canvas credentials stored
- ✅ Auth token stored locally in Chrome storage
- ✅ All API calls over HTTPS
- ✅ No data sent to third parties
- ✅ User controls token via settings page

## Troubleshooting

### Token Not Working
- Verify token is copied correctly from canvas-ai.herokuapp.com/settings
- Check that extension settings show "Token saved successfully"
- Generate a new token if needed

### Extension Not Detecting Assignment
- Ensure you're on a Canvas assignment page
- Try refreshing the page
- Check browser console (F12) for errors

### Draft Generation Fails
- Check internet connection
- Verify auth token is valid
- Try generating again (sometimes there are temporary API issues)
- Check canvas-ai.herokuapp.com status

## Future Features (v1.1+)

- [ ] Auto-fill Canvas submission form
- [ ] Quiz solving support
- [ ] Multiple Canvas instances
- [ ] Draft comparison
- [ ] Custom AI instructions
- [ ] Firefox support
- [ ] Chrome Web Store listing

## Development

To modify the extension:

1. Edit files in the `extension/` folder
2. Go to `chrome://extensions/`
3. Click reload on the Canvas AI Helper card
4. Test on a Canvas page

### Testing

- Open a Canvas assignment page
- Click the extension icon
- Check popup.js console for debug messages
- Check content.js via page inspect (right-click → Inspect → Console)

## API Reference

The extension communicates with:

- `POST /api/assignment/complete` - Generate draft
- `GET /api/completions` - View draft history
- `DELETE /api/completions/{id}` - Delete draft

All authenticated with the token from settings.

## Support

- Issues? Visit [canvas-ai.herokuapp.com](https://canvas-ai.herokuapp.com)
- Check FAQ in Settings page
- Report bugs via GitHub

## License

MIT - See LICENSE file

---

Made with ❤️ for Kent State students
