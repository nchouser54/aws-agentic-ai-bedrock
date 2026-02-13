const ids = {
  chatbotUrl: document.getElementById("chatbotUrl"),
  authMode: document.getElementById("authMode"),
  authValue: document.getElementById("authValue"),
  retrievalMode: document.getElementById("retrievalMode"),
  assistantMode: document.getElementById("assistantMode"),
  llmProvider: document.getElementById("llmProvider"),
  modelId: document.getElementById("modelId"),
  conversationId: document.getElementById("conversationId"),
  streamMode: document.getElementById("streamMode"),
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
  status: document.getElementById("status"),
  answer: document.getElementById("answer"),
  sources: document.getElementById("sources"),
  imageWrap: document.getElementById("imageWrap"),
  imagePreview: document.getElementById("imagePreview"),
  sendBtn: document.getElementById("sendBtn"),
  imageBtn: document.getElementById("imageBtn"),
  saveBtn: document.getElementById("saveBtn"),
};

const SETTINGS_KEY = "chatbot-webapp-settings-v1";

function setStatus(message, kind = "muted") {
  ids.status.className = `status ${kind}`;
  ids.status.textContent = message;
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return;
    const s = JSON.parse(raw);
    ids.chatbotUrl.value = s.chatbotUrl || "";
    ids.authMode.value = s.authMode || "token";
    ids.authValue.value = s.authValue || "";
    ids.retrievalMode.value = s.retrievalMode || "hybrid";
    ids.assistantMode.value = s.assistantMode || "contextual";
    ids.llmProvider.value = s.llmProvider || "bedrock";
    ids.modelId.value = s.modelId || "";
    ids.conversationId.value = s.conversationId || "";
    ids.streamMode.value = s.streamMode || "true";
    ids.jiraJql.value = s.jiraJql || "";
    ids.confluenceCql.value = s.confluenceCql || "";
    ids.githubOauthBaseUrl.value = s.githubOauthBaseUrl || "";
    ids.githubClientId.value = s.githubClientId || "";
    ids.githubScope.value = s.githubScope || "read:user read:org";
  } catch {
    setStatus("Could not load saved settings.", "err");
  }
}

function saveSettings() {
  const s = {
    chatbotUrl: ids.chatbotUrl.value.trim(),
    authMode: ids.authMode.value,
    authValue: ids.authValue.value,
    retrievalMode: ids.retrievalMode.value,
    assistantMode: ids.assistantMode.value,
    llmProvider: ids.llmProvider.value,
    modelId: ids.modelId.value.trim(),
    conversationId: ids.conversationId.value.trim(),
    streamMode: ids.streamMode.value,
    jiraJql: ids.jiraJql.value.trim(),
    confluenceCql: ids.confluenceCql.value.trim(),
    githubOauthBaseUrl: ids.githubOauthBaseUrl.value.trim(),
    githubClientId: ids.githubClientId.value.trim(),
    githubScope: ids.githubScope.value.trim() || "read:user read:org",
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

function renderSources(sources = {}) {
  const entries = Object.entries(sources)
    .map(([k, v]) => `<strong>${k}</strong>: ${String(v)}`)
    .join(" · ");
  ids.sources.innerHTML = entries || "";
}

async function renderAnswerStream(chunks = [], fallbackText = "") {
  if (!Array.isArray(chunks) || chunks.length === 0) {
    ids.answer.textContent = fallbackText;
    return;
  }

  ids.answer.textContent = "";
  for (const chunk of chunks) {
    ids.answer.textContent += String(chunk);
    // Small delay gives a stream-like UX while keeping API simple.
    // eslint-disable-next-line no-await-in-loop
    await sleep(35);
  }
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
  for (const modelId of models) {
    const option = document.createElement("option");
    option.value = String(modelId);
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
  setStatus("Fetching active GovCloud Bedrock models...", "muted");

  try {
    const res = await fetch(endpoint, {
      method: "GET",
      headers: buildHeaders(),
    });
    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      setStatus(`Model refresh failed (${res.status}).`, "err");
      return;
    }

    const models = (body.models || []).map((m) => m.model_id).filter(Boolean);
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
  setStatus("Sending request...", "muted");

  const payload = {
    query,
    assistant_mode: ids.assistantMode.value,
    llm_provider: ids.llmProvider.value,
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
    if (!res.ok) {
      ids.answer.textContent = JSON.stringify(body, null, 2) || `HTTP ${res.status}`;
      renderSources({});
      ids.imageWrap.hidden = true;
      setStatus(`Request failed (${res.status}).`, "err");
      return;
    }

    const streamChunks = (((body || {}).stream || {}).chunks || []);
    await renderAnswerStream(streamChunks, body.answer || JSON.stringify(body, null, 2));
    renderSources(body.sources || {});
    ids.imageWrap.hidden = true;
    setStatus("Response received.", "ok");
  } catch (err) {
    ids.answer.textContent = String(err);
    renderSources({});
    ids.imageWrap.hidden = true;
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
  setStatus("Generating image...", "muted");

  const payload = { query };
  const modelId = ids.modelId.value.trim();
  if (modelId) payload.model_id = modelId;

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: buildHeaders(),
      body: JSON.stringify(payload),
    });

    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      ids.answer.textContent = JSON.stringify(body, null, 2) || `HTTP ${res.status}`;
      ids.imageWrap.hidden = true;
      setStatus(`Image generation failed (${res.status}).`, "err");
      return;
    }

    const imageB64 = ((body.images || [])[0] || "").trim();
    if (!imageB64) {
      ids.answer.textContent = JSON.stringify(body, null, 2);
      ids.imageWrap.hidden = true;
      setStatus("Image endpoint returned no images.", "err");
      return;
    }

    ids.imagePreview.src = `data:image/png;base64,${imageB64}`;
    ids.imageWrap.hidden = false;
    ids.answer.textContent = `Image generated with ${body.model_id || "unknown model"} (${body.size || "default size"}).`;
    renderSources({});
    setStatus("Image ready.", "ok");
  } catch (err) {
    ids.imageWrap.hidden = true;
    ids.answer.textContent = String(err);
    setStatus("Image generation network/CORS error.", "err");
  } finally {
    ids.imageBtn.disabled = false;
  }
}

ids.saveBtn.addEventListener("click", saveSettings);
ids.sendBtn.addEventListener("click", askChatbot);
ids.imageBtn.addEventListener("click", generateImage);
ids.githubLoginBtn.addEventListener("click", startGitHubLogin);
ids.refreshModelsBtn.addEventListener("click", refreshModels);

loadSettings();
setStatus("Ready.");
setGitHubLoginStatus("Not started.");
