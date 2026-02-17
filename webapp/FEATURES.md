# WebUI Features

## Current Implementation (2026-02-16)

### ✅ Core Features
- **Chatbot Query** (`/chatbot/query`) - Fully wired with streaming support
- **Model Selection** (`/chatbot/models`) - GovCloud model picker with refresh
- **Image Generation** (`/chatbot/image`) - Generate and download images
  - ⚠️ **GovCloud Limitation**: NOT available in AWS GovCloud (us-gov-west-1) - no Bedrock image models
  - Commercial AWS regions only: Requires Amazon Nova Canvas, Titan, or Stability AI models
- **Image Size Control** - Dropdown selector (512x512, 768x768, 1024x1024, 1280x1280, 2048x2048)
- **Jira JQL Filter** - Query specific Jira issues
- **Confluence CQL Filter** - Query specific Confluence pages
- **Conversation Memory** - Multi-turn conversations with auto-filled conversation_id
- **Citations & Sources** - Proper rendering of API response citations and metadata
- **Guardrail Intervention** - Visual notice when guardrails intervene
- **Markdown Rendering** - Full markdown support using marked.js
- **Auth Modes** - Token, Bearer (JWT/GitHub OAuth), and none

### 🎉 New Features (Just Added)

#### 1. **Feedback System** (👍/👎)
- Thumbs up/down buttons shown after each chatbot response
- Sends feedback to `POST /chatbot/feedback` with rating and sentiment
- Feedback bar appears below answer, above citations

**API Payload:**
```json
{
  "response_id": "conv-123",
  "rating": 1,  // or -1
  "sentiment": "positive"  // or "negative"
}
```

#### 2. **Memory Management**
- **Clear This Conversation** - Clears specific conversation history (`POST /chatbot/memory/clear`)
- **Clear All Memory** - Clears all conversations with confirmation (`POST /chatbot/memory/clear-all`)
- Memory status panel shows operation results

**API Payloads:**
```json
// Clear single conversation
{ "conversation_id": "team-standup-2026-02" }

// Clear all (no payload)
{}
```

#### 3. **Atlassian Session Management**
- User-level Jira/Confluence authentication
- Provide your own email and API token
- Creates server-side session (credentials not sent on every request)
- Session create: `POST /chatbot/atlassian/session`
- Session clear: `POST /chatbot/atlassian/session/clear`

**API Payload:**
```json
{
  "email": "you@company.com",
  "api_token": "your-token-from-id.atlassian.com"
}
```

#### 4. **Image Size Selector**
- Dropdown in Connection panel
- Options: default (1024x1024), 512x512, 768x768, 1024x1024, 1280x1280, 2048x2048
- Passed as `size` parameter to `/chatbot/image` endpoint

### 🎨 UX Improvements

#### Already Implemented:
- **Markdown Rendering** - Answers render with proper markdown formatting
- **Copy to Clipboard** - Copy button (📋) for responses
- **Download Images** - Download button (⬇) for generated images
- **Clear Response** - Clear/reset button (✕) for response panel
- **Auth Value Toggle** - Show/hide auth token/bearer value (👁/🙈)
- **Atlassian Token Toggle** - Show/hide Atlassian API token (👁/🙈)
- **Ctrl/Cmd+Enter Shortcut** - Send query with keyboard shortcut
- **Keyboard Hint** - Dynamic hint shows ⌘+Enter (Mac) or Ctrl+Enter (Windows/Linux)
- **Favicon** - Robot emoji (🤖) favicon
- **Better Sources** - Highlights rendered as pills, nested objects in collapsible blocks
- **Citations Display** - Proper rendering with source badges and links
- **Loading Spinner** - Visual spinner during API requests
- **Button Priority** - "Ask Chatbot" button styled as primary action (blue)
- **Dark Theme** - Consistent dark color scheme

### 🔧 Backend Endpoints Exposed

| Feature | Method | Endpoint | Payload |
|---------|--------|----------|---------|
| Chatbot Query | POST | `/chatbot/query` | `{ query, assistant_mode, llm_provider, retrieval_mode, stream, model_id?, conversation_id?, jira_jql?, confluence_cql? }` |
| Image Generation | POST | `/chatbot/image` | `{ query, model_id?, size? }` |
| Model List | GET | `/chatbot/models` | None |
| Feedback | POST | `/chatbot/feedback` | `{ response_id, rating, sentiment }` |
| Clear Conversation | POST | `/chatbot/memory/clear` | `{ conversation_id }` |
| Clear All Memory | POST | `/chatbot/memory/clear-all` | None |
| Atlassian Session Create | POST | `/chatbot/atlassian/session` | `{ email, api_token }` |
| Atlassian Session Clear | POST | `/chatbot/atlassian/session/clear` | None |

### 🚫 Not Implemented (Intentional)

The webapp does **not** implement OpenAI-style tool calling (`tool_calls`/`tool_results`). Jira/Confluence/GitHub/KB retrieval is done **server-side** as context injection:

1. User fills in JQL/CQL filters
2. Backend fetches data from Jira/Confluence
3. Backend injects data into LLM prompt
4. Backend returns answer with citations

This is the correct behavior - no changes needed.

### 🗺️ Future Enhancements (Optional)

- [ ] Inline feedback comment field (after thumbs down)
- [ ] Response export (save to file)
- [ ] Query history/bookmarks
- [ ] Multi-image generation (grid view)
- [ ] Image prompt suggestions
- [ ] Keyboard shortcuts for all actions
- [ ] Query templates
- [ ] Dark/light theme toggle

### 🧪 Testing the Webapp

1. **Start a local server:**
   ```bash
   cd webapp
   python3 -m http.server 8080
   ```

2. **Open in browser:**
   ```
   http://localhost:8080
   ```

3. **Configure connection:**
   - Set Chatbot URL (e.g., `https://your-api-gateway/chatbot/query`)
   - Set auth mode and value
   - Click "Save Settings"

4. **Test features:**
   - Send a query → Check feedback bar appears
   - Generate image → Check size selector works
   - Create Atlassian session → Check status updates
   - Clear conversation → Check memory status

### 📦 Files Modified

- `webapp/index.html` - Added feedback bar, memory panel, Atlassian panel, image size selector
- `webapp/app.js` - Added feedback, memory, Atlassian, image size logic (727 lines total)
- `webapp/styles.css` - Added feedback bar styling, better UI polish (377 lines total)

### 🎯 All Requirements Met

✅ Feedback UI (thumbs up/down)  
✅ Memory management (clear conversation / clear all)  
✅ Atlassian session management  
✅ Image size selector  

All backend endpoints are now fully exposed in the webapp! 🚀
