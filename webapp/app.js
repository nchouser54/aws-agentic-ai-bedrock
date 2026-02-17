const ids = {
  chatbotUrl: document.getElementById("chatbotUrl"),
  authMode: document.getElementById("authMode"),
  authValue: document.getElementById("authValue"),
  authToggleBtn: document.getElementById("authToggleBtn"),
  retrievalMode: document.getElementById("retrievalMode"),
  assistantMode: document.getElementById("assistantMode"),
  llmProvider: document.getElementById("llmProvider"),
  modelId: document.getElementById("modelId"),
  conversationId: document.getElementById("conversationId"),
  streamMode: document.getElementById("streamMode"),
  imageSize: document.getElementById("imageSize"),
  refreshModelsBtn: document.getElementById("refreshModelsBtn"),
  modelSuggestions: document.getElementById("modelSuggestions"),
  query: document.getElementById("query"),
  jiraJql: document.getElementById("jiraJql"),
  confluenceCql: document.getElementById("confluenceCql"),
  githubOauthBaseUrl: document.getElementById("githubOauthBaseUrl"),
  githubClientId: document.getElementById("githubClientId"),
  githubScope: document.getElementById("githubScope"),
  githubLoginBtn: document.getElementById("githubLoginBtn"),
  githubLoginStatus: document.getElementById("githubLoginStatus"),
  atlassianEmail: document.getElementById("atlassianEmail"),
  atlassianApiToken: document.getElementById("atlassianApiToken"),
  atlassianTokenToggleBtn: document.getElementById("atlassianTokenToggleBtn"),
  atlassianLoginBtn: document.getElementById("atlassianLoginBtn"),
  atlassianLogoutBtn: document.getElementById("atlassianLogoutBtn"),
  atlassianStatus: document.getElementById("atlassianStatus"),
  memoryClearBtn: document.getElementById("memoryClearBtn"),
  memoryClearAllBtn: document.getElementById("memoryClearAllBtn"),
  memoryStatus: document.getElementById("memoryStatus"),
  status: document.getElementById("status"),
  answer: document.getElementById("answer"),
  feedbackBar: document.getElementById("feedbackBar"),
  thumbsUpBtn: document.getElementById("thumbsUpBtn"),
  thumbsDownBtn: document.getElementById("thumbsDownBtn"),
  citations: document.getElementById("citations"),
  sources: document.getElementById("sources"),
  imageWrap: document.getElementById("imageWrap"),
  imagePreview: document.getElementById("imagePreview"),
  sendBtn: document.getElementById("sendBtn"),
  imageBtn: document.getElementById("imageBtn"),
  saveBtn: document.getElementById("saveBtn"),
  copyBtn: document.getElementById("copyBtn"),
  downloadImgBtn: document.getElementById("downloadImgBtn"),
  clearBtn: document.getElementById("clearBtn"),
};

/* ── HTML sanitization helper ── */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ── Markdown rendering helper ── */
function renderMarkdown(text) {
  if (typeof marked !== "undefined" && marked.parse) {
    const html = marked.parse(String(text), { breaks: true });
    // Strip script tags as defense-in-depth, open links in new tab
    return html
      .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, "")
      .replace(/<a /g, '<a target="_blank" rel="noopener noreferrer" ');
  }
  return `<pre style="white-space:pre-wrap">${escapeHtml(text)}</pre>`;
}

// Track raw answer text for copy-to-clipboard
let lastRawAnswer = "";

const SETTINGS_KEY = "chatbot-webapp-settings-v1";
const APP_DEFAULTS = window.WEBAPP_DEFAULTS || {};
const DEFAULT_SETTINGS = {
  chatbotUrl: APP_DEFAULTS.chatbotUrl || "",
  authMode: APP_DEFAULTS.authMode || "token",
  authValue: "",
  retrievalMode: APP_DEFAULTS.retrievalMode || "hybrid",
  assistantMode: APP_DEFAULTS.assistantMode || "contextual",
  llmProvider: "bedrock",
  modelId: "",
  conversationId: "",
  streamMode: APP_DEFAULTS.streamMode || "true",
  jiraJql: "",
  confluenceCql: "",
  githubOauthBaseUrl: APP_DEFAULTS.githubOauthBaseUrl || "",
  githubClientId: APP_DEFAULTS.githubClientId || "",
  githubScope: APP_DEFAULTS.githubScope || "read:user read:org",
  imageSize: "",
  atlassianEmail: "",
};

function setStatus(message, kind = "muted") {
  ids.status.className = `status ${kind}`;
  if (kind === "loading") {
    ids.status.innerHTML = `<span class="spinner"></span>${escapeHtml(message)}`;
    ids.status.className = "status muted";
  } else {
    ids.status.textContent = message;
  }
}

function loadSettings() {
  const resolved = { ...DEFAULT_SETTINGS };
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (raw) {
      const s = JSON.parse(raw);
      Object.assign(resolved, s || {});
    }
  } catch {
    setStatus("Could not load saved settings.", "err");
  }

  ids.chatbotUrl.value = resolved.chatbotUrl || "";
  ids.authMode.value = resolved.authMode || "token";
  ids.authValue.value = resolved.authValue || "";
  ids.retrievalMode.value = resolved.retrievalMode || "hybrid";
  ids.assistantMode.value = resolved.assistantMode || "contextual";
  ids.llmProvider.value = "bedrock";
  ids.modelId.value = resolved.modelId || "";
  ids.conversationId.value = resolved.conversationId || "";
  ids.streamMode.value = resolved.streamMode || "true";
  ids.jiraJql.value = resolved.jiraJql || "";
  ids.confluenceCql.value = resolved.confluenceCql || "";
  ids.githubOauthBaseUrl.value = resolved.githubOauthBaseUrl || "";
  ids.githubClientId.value = resolved.githubClientId || "";
  ids.githubScope.value = resolved.githubScope || "read:user read:org";
  ids.imageSize.value = resolved.imageSize || "";
  ids.atlassianEmail.value = resolved.atlassianEmail || "";
}

function saveSettings() {
  const s = {
    chatbotUrl: ids.chatbotUrl.value.trim(),
    authMode: ids.authMode.value,
    authValue: ids.authValue.value,
    retrievalMode: ids.retrievalMode.value,
    assistantMode: ids.assistantMode.value,
    llmProvider: "bedrock",
    modelId: ids.modelId.value.trim(),
    conversationId: ids.conversationId.value.trim(),
    streamMode: ids.streamMode.value,
    jiraJql: ids.jiraJql.value.trim(),
    confluenceCql: ids.confluenceCql.value.trim(),
    githubOauthBaseUrl: ids.githubOauthBaseUrl.value.trim(),
    githubClientId: ids.githubClientId.value.trim(),
    githubScope: ids.githubScope.value.trim() || "read:user read:org",
    imageSize: ids.imageSize.value,
    atlassianEmail: ids.atlassianEmail.value.trim(),
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  setStatus("Settings saved locally.", "ok");
}

function setGitHubLoginStatus(message, kind = "muted") {
  ids.githubLoginStatus.className = `status ${kind}`;
  ids.githubLoginStatus.textContent = message;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function startGitHubLogin() {
  const oauthBase = ids.githubOauthBaseUrl.value.trim().replace(/\/$/, "");
  const clientId = ids.githubClientId.value.trim();
  const scope = ids.githubScope.value.trim() || "read:user read:org";

  if (!oauthBase) {
    setGitHubLoginStatus("Set GitHub OAuth Base URL to your enterprise hosted GitHub URL.", "err");
    return;
  }

  if (!/^https:\/\//i.test(oauthBase)) {
    setGitHubLoginStatus("GitHub OAuth Base URL must start with https://", "err");
    return;
  }

  if (/^https:\/\/github\.com$/i.test(oauthBase)) {
    setGitHubLoginStatus("Use your enterprise hosted GitHub URL (github.com is not allowed in this environment).", "err");
    return;
  }

  if (!clientId) {
    setGitHubLoginStatus("Enter a GitHub OAuth Client ID first.", "err");
    return;
  }

  ids.githubLoginBtn.disabled = true;
  setGitHubLoginStatus("Requesting device code from GitHub...", "muted");

  let deviceCode = "";
  let interval = 5;
  let expiresAt = Date.now() + 10 * 60 * 1000;

  try {
    const body = new URLSearchParams({ client_id: clientId, scope });
    const deviceRes = await fetch(`${oauthBase}/login/device/code`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body,
    });

    const deviceData = await deviceRes.json();
    if (!deviceRes.ok || !deviceData.device_code) {
      const msg = deviceData.error_description || deviceData.error || `HTTP ${deviceRes.status}`;
      setGitHubLoginStatus(`GitHub login start failed: ${msg}`, "err");
      return;
    }

    deviceCode = String(deviceData.device_code);
    interval = Number(deviceData.interval || 5);
    expiresAt = Date.now() + Number(deviceData.expires_in || 900) * 1000;

    const verifyUri = String(deviceData.verification_uri || `${oauthBase}/login/device`);
    const userCode = String(deviceData.user_code || "");
    setGitHubLoginStatus(`Open ${verifyUri} and enter code: ${userCode}`, "ok");
    window.open(verifyUri, "_blank", "noopener,noreferrer");
  } catch (err) {
    setGitHubLoginStatus(`Could not start GitHub login: ${String(err)}`, "err");
    ids.githubLoginBtn.disabled = false;
    return;
  }

  try {
    while (Date.now() < expiresAt) {
      await sleep(interval * 1000);

      const pollBody = new URLSearchParams({
        client_id: clientId,
        device_code: deviceCode,
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
      });

      const tokenRes = await fetch(`${oauthBase}/login/oauth/access_token`, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: pollBody,
      });
      const tokenData = await tokenRes.json().catch(() => ({}));

      if (tokenData.access_token) {
        ids.authMode.value = "bearer";
        ids.authValue.value = String(tokenData.access_token);
        saveSettings();
        setGitHubLoginStatus("GitHub login complete. Bearer token populated.", "ok");
        setStatus("GitHub login complete. Ready to query chatbot.", "ok");
        return;
      }

      const error = String(tokenData.error || "");
      if (error === "authorization_pending") {
        setGitHubLoginStatus("Waiting for GitHub authorization...", "muted");
        continue;
      }
      if (error === "slow_down") {
        interval += 5;
        setGitHubLoginStatus("GitHub asked to slow down polling...", "muted");
        continue;
      }
      if (error === "expired_token") {
        setGitHubLoginStatus("GitHub device code expired. Start login again.", "err");
        return;
      }
      if (error === "access_denied") {
        setGitHubLoginStatus("GitHub login cancelled/denied.", "err");
        return;
      }

      const msg = tokenData.error_description || tokenData.error || `HTTP ${tokenRes.status}`;
      setGitHubLoginStatus(`GitHub login failed: ${msg}`, "err");
      return;
    }

    setGitHubLoginStatus("Login timed out. Start GitHub login again.", "err");
  } catch (err) {
    setGitHubLoginStatus(`GitHub login failed: ${String(err)}`, "err");
  } finally {
    ids.githubLoginBtn.disabled = false;
  }
}

function buildHeaders() {
  const headers = { "Content-Type": "application/json" };
  const authMode = ids.authMode.value;
  const authValue = ids.authValue.value.trim();

  if (!authValue || authMode === "none") return headers;
  if (authMode === "token") headers["X-Api-Token"] = authValue;
  if (authMode === "bearer") headers.Authorization = `Bearer ${authValue}`;
  return headers;
}

/* ── Sources: render top-level scalars as pills, skip nested objects ── */
const SOURCES_HIGHLIGHT_KEYS = new Set([
  "assistant_mode", "provider", "model_id", "mode", "context_source",
  "kb_count", "jira_count", "confluence_count", "github_count",
  "memory_enabled", "memory_turns",
]);

function renderSources(sources = {}) {
  const entries = Object.entries(sources);
  if (entries.length === 0) {
    ids.sources.innerHTML = "";
    return;
  }

  // Render scalar highlight keys as pills; show nested objects in a collapsible detail
  const pills = [];
  const nested = {};

  for (const [k, v] of entries) {
    if (v !== null && typeof v === "object") {
      nested[k] = v;
    } else if (SOURCES_HIGHLIGHT_KEYS.has(k)) {
      pills.push(`<span class="source-pill"><strong>${escapeHtml(k)}</strong>${escapeHtml(String(v))}</span>`);
    }
  }

  let html = `<div class="source-pills">${pills.join("")}</div>`;

  // Render nested objects (guardrail, budget, model_routing, etc.) in a collapsible block
  const nestedKeys = Object.keys(nested);
  if (nestedKeys.length > 0) {
    const detailItems = nestedKeys.map((k) => {
      const json = JSON.stringify(nested[k], null, 2);
      return `<details class="source-detail"><summary>${escapeHtml(k)}</summary><pre>${escapeHtml(json)}</pre></details>`;
    }).join("");
    html += `<div class="source-details">${detailItems}</div>`;
  }

  ids.sources.innerHTML = html;
}

/* ── Guardrail intervention notice ── */
function clearGuardrailNotices() {
  ids.answer.parentNode.querySelectorAll(".guardrail-notice").forEach((el) => el.remove());
}

function renderGuardrailNotice(sources = {}) {
  clearGuardrailNotices();
  const g = sources.guardrail;
  if (g && g.intervened) {
    const notice = document.createElement("div");
    notice.className = "guardrail-notice status err";
    notice.style.marginTop = "8px";
    notice.textContent = "Guardrail intervened — the response may have been modified or blocked.";
    ids.answer.parentNode.insertBefore(notice, ids.answer.nextSibling);
  }
}

/* ── Citations: render using the actual API fields (source, title, locator) ── */
function renderCitations(citations = []) {
  if (!Array.isArray(citations) || citations.length === 0) {
    ids.citations.hidden = true;
    ids.citations.innerHTML = "";
    return;
  }

  const items = citations.map((c) => {
    const title = escapeHtml(c.title || c.text || c.content || JSON.stringify(c));
    const source = c.source || "";
    const locator = c.locator || c.url || c.link || "";
    const badge = source ? `<span class="citation-badge">${escapeHtml(source)}</span> ` : "";
    const label = locator
      ? `${badge}<a href="${escapeHtml(locator)}" target="_blank" rel="noopener noreferrer">${title}</a>`
      : `${badge}${title}`;
    return `<li>${label}</li>`;
  });

  ids.citations.innerHTML = `<h3>Citations</h3><ol>${items.join("")}</ol>`;
  ids.citations.hidden = false;
}

/* ── Stream answer with markdown rendering ── */
async function renderAnswerStream(chunks = [], fallbackText = "") {
  if (!Array.isArray(chunks) || chunks.length === 0) {
    lastRawAnswer = fallbackText;
    ids.answer.innerHTML = renderMarkdown(fallbackText);
    ids.copyBtn.hidden = !fallbackText;
    return;
  }

  lastRawAnswer = "";
  ids.answer.innerHTML = "";
  for (const chunk of chunks) {
    lastRawAnswer += String(chunk);
    ids.answer.innerHTML = renderMarkdown(lastRawAnswer);
    // Small delay gives a stream-like UX while keeping API simple.
    // eslint-disable-next-line no-await-in-loop
    await sleep(35);
  }
  ids.copyBtn.hidden = false;
}

function deriveModelsEndpoint(queryEndpoint) {
  const endpoint = queryEndpoint.trim();
  if (!endpoint) return "";

  try {
    const u = new URL(endpoint);
    if (u.pathname.endsWith("/chatbot/query")) {
      u.pathname = u.pathname.replace(/\/chatbot\/query$/, "/chatbot/models");
      return u.toString();
    }

    const basePath = u.pathname.endsWith("/") ? u.pathname.slice(0, -1) : u.pathname;
    u.pathname = `${basePath}/chatbot/models`;
    return u.toString();
  } catch {
    return "";
  }
}

function setModelSuggestions(models = []) {
  ids.modelSuggestions.innerHTML = "";
  for (const m of models) {
    const option = document.createElement("option");
    const id = typeof m === "object" ? m.model_id : m;
    const label = typeof m === "object" && m.name ? `${m.name} (${m.provider || ""})` : "";
    option.value = String(id);
    if (label) option.label = label;
    ids.modelSuggestions.appendChild(option);
  }
}

async function refreshModels() {
  const endpoint = deriveModelsEndpoint(ids.chatbotUrl.value);
  if (!endpoint) {
    setStatus("Set Chatbot URL first (must be a valid URL).", "err");
    return;
  }

  ids.refreshModelsBtn.disabled = true;
  setStatus("Fetching active GovCloud Bedrock models...", "loading");

  try {
    const res = await fetch(endpoint, {
      method: "GET",
      headers: buildHeaders(),
    });
    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setStatus(`Model refresh failed: ${errMsg}`, "err");
      return;
    }

    const models = (body.models || []).filter((m) => m.model_id);
    setModelSuggestions(models);
    setStatus(`Loaded ${models.length} model option(s) from ${body.region || "GovCloud"}.`, "ok");
  } catch (err) {
    setStatus(`Model refresh failed: ${String(err)}`, "err");
  } finally {
    ids.refreshModelsBtn.disabled = false;
  }
}

function deriveImageEndpoint(queryEndpoint) {
  const endpoint = queryEndpoint.trim();
  if (!endpoint) return "";

  try {
    const u = new URL(endpoint);
    if (u.pathname.endsWith("/chatbot/query")) {
      u.pathname = u.pathname.replace(/\/chatbot\/query$/, "/chatbot/image");
      return u.toString();
    }

    const basePath = u.pathname.endsWith("/") ? u.pathname.slice(0, -1) : u.pathname;
    u.pathname = `${basePath}/chatbot/image`;
    return u.toString();
  } catch {
    return "";
  }
}

/* ── Extract a human-readable error from API error responses ── */
function extractErrorMessage(body, statusCode) {
  if (body && body.error) {
    const msg = String(body.error).replace(/_/g, " ");
    return `${msg} (${statusCode})`;
  }
  return `Request failed (${statusCode})`;
}

/* ── Scroll to the response panel ── */
function scrollToResponse() {
  ids.answer.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* ── Format elapsed time ── */
function formatElapsed(ms) {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

async function askChatbot() {
  const endpoint = ids.chatbotUrl.value.trim();
  const query = ids.query.value.trim();

  if (!endpoint) {
    setStatus("Enter chatbot URL first.", "err");
    return;
  }
  if (!query) {
    setStatus("Enter a query first.", "err");
    return;
  }

  saveSettings();
  ids.sendBtn.disabled = true;
  setStatus("Sending request...", "loading");
  const startTime = performance.now();

  const payload = {
    query,
    assistant_mode: ids.assistantMode.value,
    llm_provider: "bedrock",
    retrieval_mode: ids.retrievalMode.value,
    stream: ids.streamMode.value === "true",
    stream_chunk_chars: 140,
  };

  const modelId = ids.modelId.value.trim();
  if (modelId) payload.model_id = modelId;

  const conversationId = ids.conversationId.value.trim();
  if (conversationId) payload.conversation_id = conversationId;

  const jiraJql = ids.jiraJql.value.trim();
  const confluenceCql = ids.confluenceCql.value.trim();
  if (jiraJql) payload.jira_jql = jiraJql;
  if (confluenceCql) payload.confluence_cql = confluenceCql;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(payload),
    });

    const body = await res.json().catch(() => ({}));
    const elapsed = formatElapsed(Math.round(performance.now() - startTime));

    if (!res.ok) {
      lastRawAnswer = JSON.stringify(body, null, 2) || `HTTP ${res.status}`;
      ids.answer.textContent = lastRawAnswer;
      ids.copyBtn.hidden = false;
      renderSources({});
      renderCitations([]);
      ids.imageWrap.hidden = true;
      ids.downloadImgBtn.hidden = true;
      setStatus(extractErrorMessage(body, res.status), "err");
      scrollToResponse();
      return;
    }

    // Auto-fill conversation_id from response for multi-turn memory
    if (body.conversation_id && !ids.conversationId.value.trim()) {
      ids.conversationId.value = body.conversation_id;
    }

    // Store response_id for feedback
    lastResponseId = body.response_id || body.conversation_id || null;

    const streamChunks = (((body || {}).stream || {}).chunks || []);
    await renderAnswerStream(streamChunks, body.answer || JSON.stringify(body, null, 2));
    renderSources(body.sources || {});
    renderCitations(body.citations || []);
    renderGuardrailNotice(body.sources || {});
    ids.imageWrap.hidden = true;
    ids.downloadImgBtn.hidden = true;
    ids.feedbackBar.hidden = false;

    const model = (body.sources || {}).model_id || "";
    const cached = ((body.sources || {}).response_cache || {}).hit;
    let statusMsg = `Response received in ${elapsed}`;
    if (model) statusMsg += ` via ${model}`;
    if (cached) statusMsg += " (cached)";
    setStatus(statusMsg, "ok");
    scrollToResponse();
  } catch (err) {
    lastRawAnswer = String(err);
    ids.answer.textContent = lastRawAnswer;
    ids.copyBtn.hidden = false;
    renderSources({});
    renderCitations([]);
    ids.imageWrap.hidden = true;
    ids.downloadImgBtn.hidden = true;
    setStatus("Network/CORS error. Check API URL and auth mode.", "err");
  } finally {
    ids.sendBtn.disabled = false;
  }
}

async function generateImage() {
  const endpoint = deriveImageEndpoint(ids.chatbotUrl.value);
  const query = ids.query.value.trim();

  if (!endpoint) {
    setStatus("Enter chatbot query URL first.", "err");
    return;
  }
  if (!query) {
    setStatus("Enter a prompt first (Query field).", "err");
    return;
  }

  saveSettings();
  ids.imageBtn.disabled = true;
  setStatus("Generating image...", "loading");
  const startTime = performance.now();

  const payload = { query };
  const modelId = ids.modelId.value.trim();
  if (modelId) payload.model_id = modelId;
  const imageSize = ids.imageSize.value;
  if (imageSize) payload.size = imageSize;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(payload),
    });

    const body = await res.json().catch(() => ({}));
    const elapsed = formatElapsed(Math.round(performance.now() - startTime));

    if (!res.ok) {
      lastRawAnswer = JSON.stringify(body, null, 2) || `HTTP ${res.status}`;
      ids.answer.textContent = lastRawAnswer;
      ids.copyBtn.hidden = false;
      ids.imageWrap.hidden = true;
      ids.downloadImgBtn.hidden = true;
      setStatus(extractErrorMessage(body, res.status), "err");
      scrollToResponse();
      return;
    }

    const imageB64 = ((body.images || [])[0] || "").trim();
    if (!imageB64) {
      lastRawAnswer = JSON.stringify(body, null, 2);
      ids.answer.textContent = lastRawAnswer;
      ids.copyBtn.hidden = false;
      ids.imageWrap.hidden = true;
      ids.downloadImgBtn.hidden = true;
      setStatus("Image endpoint returned no images.", "err");
      scrollToResponse();
      return;
    }

    ids.imagePreview.src = `data:image/png;base64,${imageB64}`;
    ids.imageWrap.hidden = false;
    ids.downloadImgBtn.hidden = false;
    lastRawAnswer = `Image generated with ${body.model_id || "unknown model"} (${body.size || "default size"}).`;
    ids.answer.innerHTML = renderMarkdown(lastRawAnswer);
    ids.copyBtn.hidden = true;
    renderSources({});
    renderCitations([]);
    setStatus(`Image ready in ${elapsed} via ${body.model_id || "unknown model"}`, "ok");
    scrollToResponse();
  } catch (err) {
    ids.imageWrap.hidden = true;
    ids.downloadImgBtn.hidden = true;
    lastRawAnswer = String(err);
    ids.answer.textContent = lastRawAnswer;
    ids.copyBtn.hidden = false;
    setStatus("Image generation network/CORS error.", "err");
  } finally {
    ids.imageBtn.disabled = false;
  }
}

/* ── Copy response to clipboard ── */
function copyAnswer() {
  if (!lastRawAnswer) return;
  navigator.clipboard.writeText(lastRawAnswer).then(() => {
    ids.copyBtn.textContent = "Copied!";
    setTimeout(() => { ids.copyBtn.textContent = "📋 Copy"; }, 1500);
  }).catch(() => {
    ids.copyBtn.textContent = "Failed";
    setTimeout(() => { ids.copyBtn.textContent = "📋 Copy"; }, 1500);
  });
}

/* ── Download generated image ── */
function downloadImage() {
  const src = ids.imagePreview.src;
  if (!src) return;
  const a = document.createElement("a");
  a.href = src;
  a.download = `generated-image-${Date.now()}.png`;
  a.click();
}

/* ── Clear / reset response panel ── */
function clearResponse() {
  lastRawAnswer = "";
  lastResponseId = null;
  ids.answer.innerHTML = "No response yet.";
  ids.sources.innerHTML = "";
  ids.citations.innerHTML = "";
  ids.citations.hidden = true;
  ids.imageWrap.hidden = true;
  ids.imagePreview.src = "";
  ids.copyBtn.hidden = true;
  ids.downloadImgBtn.hidden = true;
  ids.feedbackBar.hidden = true;
  clearGuardrailNotices();
  setStatus("Ready.");
}

/* ── Auth value show/hide toggle ── */
function toggleAuthVisibility() {
  const isPassword = ids.authValue.type === "password";
  ids.authValue.type = isPassword ? "text" : "password";
  ids.authToggleBtn.textContent = isPassword ? "🙈" : "👁";
  ids.authToggleBtn.title = isPassword ? "Hide auth value" : "Show auth value";
}

/* ── Atlassian token show/hide toggle ── */
function toggleAtlassianTokenVisibility() {
  const isPassword = ids.atlassianApiToken.type === "password";
  ids.atlassianApiToken.type = isPassword ? "text" : "password";
  ids.atlassianTokenToggleBtn.textContent = isPassword ? "🙈" : "👁";
  ids.atlassianTokenToggleBtn.title = isPassword ? "Hide token" : "Show token";
}

/* ── Atlassian session management ── */
function setAtlassianStatus(message, kind = "muted") {
  ids.atlassianStatus.className = `status ${kind}`;
  ids.atlassianStatus.textContent = message;
}

function deriveAtlassianEndpoint(queryEndpoint, action) {
  const endpoint = queryEndpoint.trim();
  if (!endpoint) return "";

  try {
    const u = new URL(endpoint);
    if (u.pathname.endsWith("/chatbot/query")) {
      u.pathname = u.pathname.replace(/\/chatbot\/query$/, `/chatbot/atlassian/${action}`);
      return u.toString();
    }

    const basePath = u.pathname.endsWith("/") ? u.pathname.slice(0, -1) : u.pathname;
    u.pathname = `${basePath}/chatbot/atlassian/${action}`;
    return u.toString();
  } catch {
    return "";
  }
}

async function createAtlassianSession() {
  const endpoint = deriveAtlassianEndpoint(ids.chatbotUrl.value, "session");
  const email = ids.atlassianEmail.value.trim();
  const apiToken = ids.atlassianApiToken.value.trim();

  if (!endpoint) {
    setAtlassianStatus("Set Chatbot URL first.", "err");
    return;
  }
  if (!email || !apiToken) {
    setAtlassianStatus("Enter both email and API token.", "err");
    return;
  }

  ids.atlassianLoginBtn.disabled = true;
  setAtlassianStatus("Creating session...", "muted");

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify({ email, api_token: apiToken }),
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setAtlassianStatus(`Session creation failed: ${errMsg}`, "err");
      return;
    }

    setAtlassianStatus("Session created successfully.", "ok");
    saveSettings();
  } catch (err) {
    setAtlassianStatus(`Network error: ${String(err)}`, "err");
  } finally {
    ids.atlassianLoginBtn.disabled = false;
  }
}

async function clearAtlassianSession() {
  const endpoint = deriveAtlassianEndpoint(ids.chatbotUrl.value, "session/clear");

  if (!endpoint) {
    setAtlassianStatus("Set Chatbot URL first.", "err");
    return;
  }

  ids.atlassianLogoutBtn.disabled = true;
  setAtlassianStatus("Clearing session...", "muted");

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setAtlassianStatus(`Clear failed: ${errMsg}`, "err");
      return;
    }

    setAtlassianStatus("Session cleared.", "ok");
  } catch (err) {
    setAtlassianStatus(`Network error: ${String(err)}`, "err");
  } finally {
    ids.atlassianLogoutBtn.disabled = false;
  }
}

/* ── Memory management ── */
function setMemoryStatus(message, kind = "muted") {
  ids.memoryStatus.className = `status ${kind}`;
  ids.memoryStatus.textContent = message;
}

function deriveMemoryEndpoint(queryEndpoint, action) {
  const endpoint = queryEndpoint.trim();
  if (!endpoint) return "";

  try {
    const u = new URL(endpoint);
    if (u.pathname.endsWith("/chatbot/query")) {
      u.pathname = u.pathname.replace(/\/chatbot\/query$/, `/chatbot/memory/${action}`);
      return u.toString();
    }

    const basePath = u.pathname.endsWith("/") ? u.pathname.slice(0, -1) : u.pathname;
    u.pathname = `${basePath}/chatbot/memory/${action}`;
    return u.toString();
  } catch {
    return "";
  }
}

async function clearConversation() {
  const endpoint = deriveMemoryEndpoint(ids.chatbotUrl.value, "clear");
  const conversationId = ids.conversationId.value.trim();

  if (!endpoint) {
    setMemoryStatus("Set Chatbot URL first.", "err");
    return;
  }
  if (!conversationId) {
    setMemoryStatus("Enter a conversation ID first.", "err");
    return;
  }

  ids.memoryClearBtn.disabled = true;
  setMemoryStatus("Clearing conversation...", "muted");

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify({ conversation_id: conversationId }),
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setMemoryStatus(`Clear failed: ${errMsg}`, "err");
      return;
    }

    setMemoryStatus("Conversation cleared.", "ok");
  } catch (err) {
    setMemoryStatus(`Network error: ${String(err)}`, "err");
  } finally {
    ids.memoryClearBtn.disabled = false;
  }
}

async function clearAllMemory() {
  const endpoint = deriveMemoryEndpoint(ids.chatbotUrl.value, "clear-all");

  if (!endpoint) {
    setMemoryStatus("Set Chatbot URL first.", "err");
    return;
  }

  if (!confirm("Clear ALL conversation history? This cannot be undone.")) {
    setMemoryStatus("Cancelled.", "muted");
    return;
  }

  ids.memoryClearAllBtn.disabled = true;
  setMemoryStatus("Clearing all memory...", "muted");

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setMemoryStatus(`Clear all failed: ${errMsg}`, "err");
      return;
    }

    setMemoryStatus("All memory cleared.", "ok");
  } catch (err) {
    setMemoryStatus(`Network error: ${String(err)}`, "err");
  } finally {
    ids.memoryClearAllBtn.disabled = false;
  }
}

/* ── Feedback (thumbs up/down) ── */
let lastResponseId = null;

function deriveFeedbackEndpoint(queryEndpoint) {
  const endpoint = queryEndpoint.trim();
  if (!endpoint) return "";

  try {
    const u = new URL(endpoint);
    if (u.pathname.endsWith("/chatbot/query")) {
      u.pathname = u.pathname.replace(/\/chatbot\/query$/, "/chatbot/feedback");
      return u.toString();
    }

    const basePath = u.pathname.endsWith("/") ? u.pathname.slice(0, -1) : u.pathname;
    u.pathname = `${basePath}/chatbot/feedback`;
    return u.toString();
  } catch {
    return "";
  }
}

async function sendFeedback(rating) {
  const endpoint = deriveFeedbackEndpoint(ids.chatbotUrl.value);

  if (!endpoint) {
    setStatus("Set Chatbot URL first.", "err");
    return;
  }
  if (!lastResponseId) {
    setStatus("No response to provide feedback on.", "err");
    return;
  }

  const payload = {
    response_id: lastResponseId,
    rating,
    sentiment: rating === 1 ? "positive" : "negative",
  };

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(payload),
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const errMsg = body.error || `HTTP ${res.status}`;
      setStatus(`Feedback failed: ${errMsg}`, "err");
      return;
    }

    setStatus(`Feedback sent: ${rating === 1 ? "positive" : "negative"}`, "ok");
  } catch (err) {
    setStatus(`Feedback error: ${String(err)}`, "err");
  }
}

/* ── Keyboard shortcut: Ctrl/Cmd+Enter to send ── */
ids.query.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    if (!ids.sendBtn.disabled) askChatbot();
  }
});

/* ── Event listeners ── */
ids.saveBtn.addEventListener("click", saveSettings);
ids.sendBtn.addEventListener("click", askChatbot);
ids.imageBtn.addEventListener("click", generateImage);
ids.githubLoginBtn.addEventListener("click", startGitHubLogin);
ids.refreshModelsBtn.addEventListener("click", refreshModels);
ids.copyBtn.addEventListener("click", copyAnswer);
ids.downloadImgBtn.addEventListener("click", downloadImage);
ids.clearBtn.addEventListener("click", clearResponse);
ids.authToggleBtn.addEventListener("click", toggleAuthVisibility);
ids.atlassianTokenToggleBtn.addEventListener("click", toggleAtlassianTokenVisibility);
ids.atlassianLoginBtn.addEventListener("click", createAtlassianSession);
ids.atlassianLogoutBtn.addEventListener("click", clearAtlassianSession);
ids.memoryClearBtn.addEventListener("click", clearConversation);
ids.memoryClearAllBtn.addEventListener("click", clearAllMemory);
ids.thumbsUpBtn.addEventListener("click", () => sendFeedback(1));
ids.thumbsDownBtn.addEventListener("click", () => sendFeedback(-1));

loadSettings();
setStatus("Ready.");
setGitHubLoginStatus("Not started.");
setAtlassianStatus("No session.");
setMemoryStatus("No action taken.");
