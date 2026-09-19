/* The assistant itself: chat, memory, documents, vault, dashboard, settings. */

const App = {
  view: "chat",
  conversationId: null,
  conversations: [],
  streaming: false,
  settings: null,
};

App.NAV = [
  ["chat", "✦", "Chat"],
  ["memory", "◈", "Memory"],
  ["documents", "▤", "Documents"],
  ["vault", "🔒", "Vault"],
  ["dashboard", "◎", "Dashboard"],
  ["settings", "⚙", "Settings"],
];

/* ------------------------------------------------------------------- boot */

PM.boot = async ({ showTutorial = false } = {}) => {
  let state;
  try {
    state = await PM.get("/api/state");
  } catch (error) {
    PM.render(`<div class="wizard">${PM.brand()}
      <div class="card"><h1>PocketMind is not responding</h1>
      <p class="intro">${PM.esc(error.message)}</p></div></div>`);
    return;
  }
  PM.state = state;

  if (state.mode === "setup") {
    if (state.candidates.length) return App.chooseDrive(state.candidates);
    return Setup.welcome();
  }

  try {
    App.settings = await PM.get("/api/settings");
  } catch {
    App.settings = null;
  }
  App.view = "chat";
  App.paint();
  if (showTutorial || !state.tutorial_seen) App.tutorial();
};

/* A drive exists but more than one was found, or auto-open did not happen. */
App.chooseDrive = (candidates) => {
  PM.render(`
    <div class="wizard">
      ${PM.brand()}
      <section class="card">
        <div class="eyebrow">Welcome back</div>
        <h1>Open your PocketMind drive</h1>
        <p class="intro">More than one PocketMind installation is connected. Choose the one to open.</p>
        <div class="option-list">
          ${candidates.map((item) => `
            <button class="option" data-root="${PM.esc(item.root)}" type="button">
              <span class="radio" aria-hidden="true"></span>
              <span class="option-body">
                <span class="option-title">${PM.esc(item.display_name || "PocketMind")} · ${PM.esc(item.drive_id)}</span>
                <span class="option-meta">${PM.esc(item.root)}</span>
              </span>
            </button>`).join("")}
        </div>
        <div class="error" id="error"></div>
        <footer class="actions">
          <span>Or set up a new drive.</span>
          <button class="secondary" id="new-setup">Set up another drive</button>
        </footer>
      </section>
    </div>`);

  PM.on(".option[data-root]", "click", async (event) => {
    try {
      await PM.post("/api/setup/open", { root: event.currentTarget.dataset.root });
      PM.boot();
    } catch (error) {
      PM.setError("#error", error);
    }
  });
  PM.one("#new-setup").addEventListener("click", Setup.welcome);
};

/* ------------------------------------------------------------------ shell */

App.paint = async () => {
  const runtime = PM.state?.runtime || {};
  const vault = PM.state?.vault || {};
  const network = PM.state?.network || {};

  PM.render(`
    <div class="shell">
      <aside class="sidebar">
        ${PM.brand()}
        ${App.NAV.map(([key, icon, label]) => `
          <button class="nav-item ${App.view === key ? "active" : ""}" data-view="${key}">
            <span class="nav-icon">${icon}</span>${label}
          </button>`).join("")}
        <div class="nav-spacer"></div>
        <div class="sidebar-foot">
          <div><b>${PM.esc(PM.state?.installation?.drive_id || "")}</b> · ${PM.esc(PM.state?.installation?.display_name || "")}</div>
          <div>PocketMind ${PM.esc(PM.state?.version || "")}</div>
        </div>
      </aside>
      <main class="main">
        <header class="main-head">
          <div>
            <h1 id="view-title">PocketMind</h1>
            <div class="sub" id="view-sub"></div>
          </div>
          <div class="head-actions">
            <span class="pill ${runtime.blocked_reason ? "bad" : runtime.running ? "good" : ""}"><span class="dot"></span>${
              runtime.blocked_reason ? "Model blocked" : runtime.running ? "Model running" : "Model idle"}</span>
            <span class="pill ${vault.state === "unlocked" ? "warn" : "good"}"><span class="dot"></span>${
              vault.state === "unlocked" ? "Vault unlocked" : vault.state === "locked" ? "Vault locked" : "No vault"}</span>
            <span class="pill ${network.online ? "" : "good"}"><span class="dot"></span>${
              network.online ? "Internet available" : "Offline"}</span>
          </div>
        </header>
        <div class="main-body" id="view-body"><div class="loading">Loading…</div></div>
      </main>
    </div>`);

  PM.on(".nav-item", "click", (event) => {
    App.view = event.currentTarget.dataset.view;
    App.paint();
  });

  await App.renderView();
};

/* Views render asynchronously, so a slow one can finish after the user has
   already switched away. Anything that touches the DOM checks first that the
   view it belongs to is still the one on screen. */
App.isCurrent = () => App.view === App.renderingView;

App.head = (title, subtitle, actionsHtml = "") => {
  if (!App.isCurrent()) return;
  PM.one("#view-title").textContent = title;
  PM.one("#view-sub").textContent = subtitle || "";
  const actions = PM.one(".head-actions");
  if (actionsHtml && !actions.dataset.extended) {
    actions.insertAdjacentHTML("afterbegin", actionsHtml);
    actions.dataset.extended = "1";
  }
};

App.body = (html, flush = false) => {
  const body = PM.one("#view-body");
  if (!body || !App.isCurrent()) return body;
  body.className = flush ? "main-body flush" : "main-body";
  body.innerHTML = html;
  return body;
};

/* Shown at the top of the chat when this computer cannot run the engine, so
   the user learns it before typing a message rather than after. */
App.blockedBanner = () => {
  const reason = PM.state?.runtime?.blocked_reason;
  if (!reason) return "";
  return `
    <div class="notice warn" style="margin:20px 28px 0">
      <div class="icon">!</div>
      <div>
        <strong>This computer cannot run your AI model</strong>
        <p>${PM.esc(reason)}</p>
        <p>Everything else on your drive still works: your memories, documents, and vault are all
        available here.</p>
      </div>
    </div>`;
};

App.refreshState = async () => {
  try {
    PM.state = await PM.get("/api/state");
  } catch {
    /* keep the last known state */
  }
};

App.renderView = async () => {
  App.renderingView = App.view;
  try {
    await App.views[App.view]();
  } catch (error) {
    if (error.status === 409 || error.status === 410) {
      PM.toast(error.message, true);
      await App.refreshState();
      return PM.boot();
    }
    App.body(`<div class="empty">${PM.esc(error.message)}</div>`);
  }
};

App.views = {};

/* ------------------------------------------------------------------- chat */

App.views.chat = async () => {
  App.head("Chat", "Everything you type here stays on your drive.");
  App.conversations = await PM.get("/api/conversations");

  App.body(`
    <div class="chat-layout">
      <div class="chat-list">
        <div class="chat-list-head">
          <button class="primary" id="new-chat">+ New chat</button>
          <input type="search" id="chat-search" placeholder="Search conversations…">
        </div>
        <div class="chat-list-items" id="chat-items"></div>
      </div>
      <div class="chat-panel">
        ${App.blockedBanner()}
        <div class="messages" id="messages"></div>
        <div class="composer">
          <form id="chat-form">
            <textarea id="chat-input" placeholder="Ask PocketMind…" rows="2"></textarea>
            <button class="primary" type="submit" id="send">Send</button>
          </form>
          <div class="hint">
            <label><input type="checkbox" id="use-memory" checked> Use my memories</label>
            <label><input type="checkbox" id="use-documents" checked> Use my documents</label>
            <span id="chat-status"></span>
          </div>
        </div>
      </div>
    </div>`, true);

  App.paintConversations();
  PM.one("#new-chat").addEventListener("click", () => {
    App.conversationId = null;
    App.paintConversations();
    App.paintMessages([]);
  });
  PM.one("#chat-search").addEventListener("input", App.searchConversations);
  PM.one("#chat-form").addEventListener("submit", App.send);
  PM.one("#chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      PM.one("#chat-form").requestSubmit();
    }
  });

  if (App.conversationId) await App.openConversation(App.conversationId);
  else App.paintMessages([]);
};

App.paintConversations = (rows = App.conversations) => {
  const list = PM.one("#chat-items");
  if (!list) return;
  if (!rows.length) {
    list.innerHTML = '<div class="empty" style="border:0">No conversations yet.</div>';
    return;
  }
  list.innerHTML = rows.map((row) => `
    <button class="chat-item ${row.id === App.conversationId ? "active" : ""}" data-id="${row.id}">
      <b>${PM.esc(row.title)}</b>
      <small>${PM.esc(PM.when(row.updated_at))} · ${row.message_count ?? 0} messages</small>
    </button>`).join("");

  PM.on(".chat-item", "click", (event) => App.openConversation(Number(event.currentTarget.dataset.id)), list);
};

App.searchConversations = async (event) => {
  const query = event.target.value.trim();
  if (!query) return App.paintConversations();
  try {
    const hits = await PM.get(`/api/conversations/search?q=${encodeURIComponent(query)}`);
    const seen = new Map();
    hits.forEach((hit) => {
      if (!seen.has(hit.id)) seen.set(hit.id, { id: hit.id, title: hit.title, updated_at: hit.updated_at });
    });
    App.paintConversations([...seen.values()]);
  } catch (error) {
    PM.toast(error.message, true);
  }
};

App.openConversation = async (id) => {
  App.conversationId = id;
  App.paintConversations();
  const messages = await PM.get(`/api/conversations/${id}/messages`);
  App.paintMessages(messages);
};

App.paintMessages = (messages) => {
  const container = PM.one("#messages");
  if (!container) return;
  if (!messages.length) {
    const name = PM.state?.installation?.display_name;
    container.innerHTML = `
      <div class="msg assistant">
        <div class="who">PocketMind</div>
        <div class="bubble">${name ? `Hello ${PM.esc(name)}. ` : ""}What would you like to work on?</div>
        <div class="suggestions">
          ${["What do you remember about me?",
             "Remember that I prefer …",
             "Search my documents for …",
             "Help me plan my week.",
             "What projects am I working on?"]
            .map((text) => `<button class="suggestion" data-say="${PM.esc(text)}">${PM.esc(text)}</button>`).join("")}
        </div>
      </div>`;
    PM.on(".suggestion", "click", (event) => {
      PM.one("#chat-input").value = event.currentTarget.dataset.say;
      PM.one("#chat-input").focus();
    }, container);
    return;
  }

  container.innerHTML = messages.map(App.messageHtml).join("");
  App.addConversationControls();
  container.scrollTop = container.scrollHeight;
};

App.messageHtml = (message) => `
  <div class="msg ${message.role === "user" ? "user" : "assistant"}">
    <div class="who">${message.role === "user" ? "You" : "PocketMind"}</div>
    <div class="bubble">${PM.esc(message.content)}</div>
    ${message.sources?.length
      ? `<div class="sources">From your documents: ${message.sources.map(PM.esc).join(", ")}</div>` : ""}
  </div>`;

App.addConversationControls = () => {
  if (!App.conversationId || !App.isCurrent()) return;
  const actions = PM.one(".head-actions");
  if (!actions || actions.dataset.chatControls) return;
  actions.dataset.chatControls = "1";
  actions.insertAdjacentHTML("afterbegin", `
    <button class="secondary" id="rename-chat">Rename</button>
    <button class="danger" id="delete-chat">Delete</button>`);

  PM.one("#rename-chat").addEventListener("click", async () => {
    const current = App.conversations.find((row) => row.id === App.conversationId);
    const title = window.prompt("New name for this conversation:", current?.title || "");
    if (!title) return;
    await PM.patch(`/api/conversations/${App.conversationId}`, { title });
    App.paint();
  });
  PM.one("#delete-chat").addEventListener("click", async () => {
    if (!PM.confirmAction("Delete this conversation? This cannot be undone.")) return;
    await PM.del(`/api/conversations/${App.conversationId}`);
    App.conversationId = null;
    PM.toast("Conversation deleted.");
    App.paint();
  });
};

App.send = async (event) => {
  event.preventDefault();
  if (App.streaming) return;
  const input = PM.one("#chat-input");
  const text = input.value.trim();
  if (!text) return;

  const container = PM.one("#messages");
  if (!App.conversationId) container.innerHTML = "";
  container.insertAdjacentHTML("beforeend", App.messageHtml({ role: "user", content: text, sources: [] }));
  input.value = "";
  container.scrollTop = container.scrollHeight;

  const bubbleId = `reply-${Date.now()}`;
  container.insertAdjacentHTML("beforeend", `
    <div class="msg assistant" id="${bubbleId}">
      <div class="who">PocketMind</div>
      <div class="bubble"><span class="cursor">&nbsp;</span></div>
      <div class="sources"></div>
    </div>`);
  const bubble = PM.one(`#${bubbleId} .bubble`);
  const sourcesNode = PM.one(`#${bubbleId} .sources`);
  const status = PM.one("#chat-status");

  App.streaming = true;
  PM.one("#send").disabled = true;
  status.textContent = "Thinking… the model is loading if this is the first message.";

  let answer = "";
  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        conversation_id: App.conversationId,
        use_memory: PM.one("#use-memory").checked,
        use_documents: PM.one("#use-documents").checked,
      }),
    });
    if (!response.ok) throw new PM.ApiError(await PM.detailOf(response), response.status);

    for await (const event of App.readEvents(response)) {
      if (event.name === "start") {
        App.conversationId = event.data.conversation_id;
        status.textContent = event.data.saved_memory
          ? `Saved to memory: "${event.data.saved_memory}"`
          : event.data.memories_used
            ? `Using ${event.data.memories_used} memory(ies)`
            : "";
        if (event.data.sources?.length) {
          sourcesNode.textContent = `From your documents: ${event.data.sources.join(", ")}`;
        }
      } else if (event.name === "token") {
        answer += event.data.text;
        bubble.textContent = answer;
        PM.one("#messages").scrollTop = PM.one("#messages").scrollHeight;
      } else if (event.name === "error") {
        throw new PM.ApiError(event.data.detail, 503, event.data.hint);
      }
    }
    if (!answer.trim()) bubble.textContent = "(The model returned an empty answer.)";
  } catch (error) {
    bubble.textContent = error.hint ? `${error.message}\n\n${error.hint}` : error.message;
    bubble.style.borderColor = "rgba(255,143,143,.4)";
  } finally {
    App.streaming = false;
    const send = PM.one("#send");
    if (send) send.disabled = false;
    if (status && !status.textContent.startsWith("Saved")) status.textContent = "";
    App.conversations = await PM.get("/api/conversations").catch(() => App.conversations);
    App.paintConversations();
    App.addConversationControls();
  }
};

/* Parse a server-sent event stream into {name, data} objects. */
App.readEvents = async function* (response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let split;
    while ((split = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      let name = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        yield { name, data: JSON.parse(data) };
      } catch {
        /* ignore malformed frames */
      }
    }
  }
};

/* ----------------------------------------------------------------- memory */

App.views.memory = async () => {
  App.head("Memory", "What PocketMind remembers about you. Nothing here is shared.");
  const memories = await PM.get("/api/memories");
  const categories = [...new Set(memories.map((item) => item.category))].sort();

  App.body(`
    <div class="toolbar">
      <input type="search" id="memory-search" placeholder="Search memories…">
      <select id="memory-filter">
        <option value="">All categories</option>
        ${categories.map((name) => `<option value="${PM.esc(name)}">${PM.esc(name)}</option>`).join("")}
      </select>
      <button class="secondary" id="knowledge">What do you know about me?</button>
      <button class="primary" id="add-memory">+ Add memory</button>
    </div>
    <div class="list" id="memory-list"></div>`);

  const paint = (rows) => {
    const list = PM.one("#memory-list");
    if (!rows.length) {
      list.innerHTML = `<div class="empty">No memories yet. Tell PocketMind
        "remember that …" in a chat, or add one here.</div>`;
      return;
    }
    list.innerHTML = rows.map((memory) => `
      <div class="list-row">
        <div class="grow">
          <p>${PM.esc(memory.content)}</p>
          <div class="meta">${PM.esc(memory.category)} · importance ${memory.importance} · ${PM.esc(PM.when(memory.created_at))}</div>
        </div>
        <div class="list-actions">
          <button class="secondary" data-edit="${memory.id}">Edit</button>
          <button class="danger" data-delete="${memory.id}">Delete</button>
        </div>
      </div>`).join("");

    PM.on("[data-edit]", "click", async (event) => {
      const id = Number(event.currentTarget.dataset.edit);
      const memory = memories.find((item) => item.id === id);
      const content = window.prompt("Edit this memory:", memory.content);
      if (content === null) return;
      await PM.patch(`/api/memories/${id}`, { content });
      PM.toast("Memory updated.");
      App.renderView();
    }, list);

    PM.on("[data-delete]", "click", async (event) => {
      if (!PM.confirmAction("Delete this memory? This cannot be undone.")) return;
      await PM.del(`/api/memories/${event.currentTarget.dataset.delete}`);
      PM.toast("Memory deleted.");
      App.renderView();
    }, list);
  };

  paint(memories);

  PM.one("#memory-search").addEventListener("input", (event) => {
    const query = event.target.value.toLowerCase();
    paint(memories.filter((item) => item.content.toLowerCase().includes(query)));
  });
  PM.one("#memory-filter").addEventListener("change", (event) => {
    const value = event.target.value;
    paint(value ? memories.filter((item) => item.category === value) : memories);
  });
  PM.one("#add-memory").addEventListener("click", async () => {
    const content = window.prompt("What should PocketMind remember?");
    if (!content?.trim()) return;
    await PM.post("/api/memories", { content: content.trim(), category: "personal", importance: 3 });
    PM.toast("Saved to memory.");
    App.renderView();
  });
  PM.one("#knowledge").addEventListener("click", App.knowledge);
};

App.knowledge = async () => {
  const summary = await PM.get("/api/knowledge");
  const sections = Object.entries(summary.memories_by_category);
  App.body(`
    <div class="toolbar"><button class="secondary" id="back">← Back to memory</button></div>
    <div class="section">
      <h2>Profile</h2>
      <div class="spec-grid">
        <div class="spec"><span>Name</span><b>${PM.esc(summary.display_name || "—")}</b></div>
        <div class="spec"><span>Main uses</span><b>${PM.esc(summary.use_cases.join(", ") || "—")}</b></div>
        <div class="spec"><span>Conversations</span><b>${summary.conversation_count}</b></div>
        <div class="spec"><span>Vault entries</span><b>${summary.vault_entry_count}</b></div>
      </div>
    </div>
    ${sections.map(([category, rows]) => `
      <div class="section">
        <h2>${PM.esc(category)}</h2>
        <div class="list">
          ${rows.map((memory) => `
            <div class="list-row">
              <div class="grow"><p>${PM.esc(memory.content)}</p></div>
              <div class="list-actions"><button class="danger" data-delete="${memory.id}">Delete</button></div>
            </div>`).join("")}
        </div>
      </div>`).join("")}
    <div class="section">
      <h2>Documents (${summary.documents.length})</h2>
      <div class="list">
        ${summary.documents.map((document) => `
          <div class="list-row"><div class="grow"><p>${PM.esc(document.filename)}</p>
          <div class="meta">${document.chunk_count} passages · ${PM.bytes(document.byte_size)}</div></div></div>`).join("")
          || '<div class="empty">No documents indexed.</div>'}
      </div>
    </div>
    <div class="notice"><div class="icon">✓</div><div><p>${PM.esc(summary.note)}</p></div></div>`);

  PM.one("#back").addEventListener("click", () => App.renderView());
  PM.on("[data-delete]", "click", async (event) => {
    if (!PM.confirmAction("Delete this memory?")) return;
    await PM.del(`/api/memories/${event.currentTarget.dataset.delete}`);
    App.knowledge();
  });
};

/* -------------------------------------------------------------- documents */

App.views.documents = async () => {
  App.head("Documents", "Your private knowledge base. Files are indexed on the drive and never uploaded.");
  const documents = await PM.get("/api/documents");

  App.body(`
    <div class="toolbar">
      <button class="primary" id="pick-files">+ Add documents</button>
      <input type="file" id="file-input" multiple class="hidden"
             accept=".txt,.md,.markdown,.csv,.tsv,.json,.pdf,.docx,.py,.js,.ts,.html,.css,.yaml,.yml,.sql,.sh,.ps1">
      <input type="text" id="folder-path" placeholder="Or paste a folder path to index, e.g. C:\\Users\\you\\Notes">
      <button class="secondary" id="import-folder">Index folder</button>
    </div>
    <div id="upload-status"></div>
    <div class="list" id="document-list">
      ${documents.length ? documents.map((document) => `
        <div class="list-row">
          <div class="grow">
            <p><b>${PM.esc(document.filename)}</b></p>
            <div class="meta">${document.chunk_count} passages · ${PM.bytes(document.byte_size)} ·
              indexed ${PM.esc(PM.when(document.indexed_at))}${
                document.source_path ? ` · ${PM.esc(document.source_path)}` : ""}</div>
          </div>
          <div class="list-actions"><button class="danger" data-delete="${document.id}">Remove</button></div>
        </div>`).join("")
        : `<div class="empty">No documents yet. Add PDFs, Word files, notes, spreadsheets, or code
           and PocketMind will be able to answer questions about them.</div>`}
    </div>`);

  PM.one("#pick-files").addEventListener("click", () => PM.one("#file-input").click());
  PM.one("#file-input").addEventListener("change", async (event) => {
    const files = [...event.target.files];
    const status = PM.one("#upload-status");
    for (const [index, file] of files.entries()) {
      status.innerHTML = `<div class="loading">Indexing ${PM.esc(file.name)} (${index + 1} of ${files.length})…</div>`;
      const form = new FormData();
      form.append("file", file);
      try {
        const result = await PM.request("/api/documents", { method: "POST", body: form });
        if (result.status === "skipped") PM.toast(`${file.name}: ${result.detail}`);
      } catch (error) {
        PM.toast(`${file.name}: ${error.message}`, true);
      }
    }
    status.innerHTML = "";
    PM.toast("Finished indexing.");
    App.renderView();
  });

  PM.one("#import-folder").addEventListener("click", async () => {
    const folder = PM.one("#folder-path").value.trim();
    if (!folder) return PM.toast("Paste the full path of a folder first.", true);
    PM.one("#upload-status").innerHTML = '<div class="loading">Indexing folder…</div>';
    try {
      const result = await PM.post("/api/documents/import-folder", { folder, recursive: true });
      PM.toast(`Indexed ${result.indexed} file(s) into ${result.passages} passages. ${result.skipped} skipped.`);
    } catch (error) {
      PM.toast(error.message, true);
    }
    App.renderView();
  });

  PM.on("[data-delete]", "click", async (event) => {
    if (!PM.confirmAction("Remove this document from your knowledge base?")) return;
    await PM.del(`/api/documents/${event.currentTarget.dataset.delete}`);
    PM.toast("Document removed.");
    App.renderView();
  });
};

/* ------------------------------------------------------------------ vault */

App.views.vault = async () => {
  const status = await PM.get("/api/vault/status");
  App.head("Vault", "Passwords, keys, and secure notes. The assistant can never read these.");

  if (status.state === "absent") return App.vaultCreate();
  if (status.state === "locked" || !PM.vaultToken) return App.vaultUnlock(status);
  return App.vaultEntries(status);
};

App.vaultCreate = () => {
  App.body(`
    <div class="card" style="max-width:520px">
      <h1>Create your vault</h1>
      <p class="intro">This drive has no vault yet. Choose a master password to create one.</p>
      <label class="field"><span>Master password</span>
        <input type="password" id="password" minlength="12" autocomplete="new-password"></label>
      <label class="field"><span>Confirm password</span>
        <input type="password" id="confirm" autocomplete="new-password"></label>
      <div class="error" id="error"></div>
      <button class="primary" id="create">Create vault</button>
    </div>`);

  PM.one("#create").addEventListener("click", async () => {
    const password = PM.one("#password").value;
    if (password !== PM.one("#confirm").value) {
      return PM.setError("#error", { message: "The two passwords do not match." });
    }
    try {
      const result = await PM.post("/api/vault/create", { password });
      PM.vaultToken = result.session_token;
      PM.toast("Vault created and unlocked.");
      App.paint();
    } catch (error) {
      PM.setError("#error", error);
    }
  });
};

App.vaultUnlock = (status) => {
  App.body(`
    <div class="card" style="max-width:520px">
      <h1>Vault locked</h1>
      <p class="intro">
        ${status.secret_count} item(s) stored. Enter your master password to unlock.
        The vault relocks automatically after ${Math.round(status.lock_timeout_seconds / 60)} minutes of inactivity.
      </p>
      <label class="field"><span>Master password</span>
        <input type="password" id="password" autocomplete="current-password" autofocus></label>
      <div class="error" id="error"></div>
      <button class="primary" id="unlock">Unlock</button>
    </div>`);

  const unlock = async () => {
    try {
      const result = await PM.post("/api/vault/unlock", { password: PM.one("#password").value });
      PM.vaultToken = result.session_token;
      await App.refreshState();
      App.paint();
    } catch (error) {
      PM.setError("#error", error);
    }
  };
  PM.one("#unlock").addEventListener("click", unlock);
  PM.one("#password").addEventListener("keydown", (event) => { if (event.key === "Enter") unlock(); });
};

App.vaultEntries = async (status) => {
  let entries;
  try {
    entries = await PM.get("/api/vault/entries");
  } catch (error) {
    PM.vaultToken = null;
    return App.vaultUnlock(status);
  }

  // Keep the header pill honest: the vault may have auto-locked, or been
  // unlocked, since the shell was last painted.
  if (PM.state?.vault?.state !== status.state) {
    await App.refreshState();
    const pill = PM.one(".head-actions .pill:nth-child(2)");
    if (pill) {
      pill.className = `pill ${status.state === "unlocked" ? "warn" : "good"}`;
      pill.innerHTML = `<span class="dot"></span>${
        status.state === "unlocked" ? "Vault unlocked" : "Vault locked"}`;
    }
  }

  App.body(`
    <div class="toolbar">
      <button class="primary" id="add-secret">+ Add secret</button>
      <button class="secondary" id="change-password">Change master password</button>
      <button class="secondary" id="lock">Lock vault now</button>
      <span class="pill warn"><span class="dot"></span>Relocks in ${Math.round((status.seconds_until_lock ?? 0) / 60)} min</span>
    </div>
    <div class="list" id="secret-list">
      ${entries.length ? entries.map((entry) => `
        <div class="list-row">
          <div class="grow">
            <p><b>${PM.esc(entry.name)}</b></p>
            ${entry.note ? `<div class="meta">${PM.esc(entry.note)}</div>` : ""}
            <div class="meta">Added ${PM.esc(PM.when(entry.created_at))}</div>
            <div class="secret-value hidden" data-value-for="${PM.esc(entry.name)}"></div>
          </div>
          <div class="list-actions">
            <button class="secondary" data-reveal="${PM.esc(entry.name)}">Show</button>
            <button class="danger" data-delete="${PM.esc(entry.name)}">Delete</button>
          </div>
        </div>`).join("")
        : '<div class="empty">Your vault is empty. Add a password, API key, or secure note.</div>'}
    </div>
    <div class="notice">
      <div class="icon">🔒</div>
      <div>
        <strong>Kept apart from your AI memory</strong>
        <p>Vault contents are encrypted with Argon2id and AES-GCM and are never placed in the model's context.
        If you ask the assistant for a stored password it will tell you to open this screen instead.</p>
      </div>
    </div>`);

  PM.one("#add-secret").addEventListener("click", async () => {
    const name = window.prompt("Name for this secret (for example, 'Email recovery code'):");
    if (!name?.trim()) return;
    const value = window.prompt(`Value for "${name}":`);
    if (!value) return;
    await PM.post("/api/vault/entries", { name: name.trim(), value, note: "" });
    PM.toast("Stored in your vault.");
    App.renderView();
  });

  PM.one("#lock").addEventListener("click", async () => {
    await PM.post("/api/vault/lock");
    PM.vaultToken = null;
    await App.refreshState();
    App.paint();
  });

  PM.one("#change-password").addEventListener("click", async () => {
    const current = window.prompt("Current master password:");
    if (!current) return;
    const next = window.prompt("New master password (at least 12 characters):");
    if (!next) return;
    try {
      const result = await PM.post("/api/vault/change-password", {
        current_password: current, new_password: next });
      PM.vaultToken = result.session_token;
      PM.toast("Master password changed.");
    } catch (error) {
      PM.toast(error.message, true);
    }
  });

  PM.on("[data-reveal]", "click", async (event) => {
    const name = event.currentTarget.dataset.reveal;
    const target = PM.one(`[data-value-for="${CSS.escape(name)}"]`);
    if (!target.classList.contains("hidden")) {
      target.classList.add("hidden");
      event.currentTarget.textContent = "Show";
      return;
    }
    try {
      const secret = await PM.post(`/api/vault/entries/${encodeURIComponent(name)}/reveal`);
      target.textContent = secret.value;
      target.classList.remove("hidden");
      event.currentTarget.textContent = "Hide";
    } catch (error) {
      PM.toast(error.message, true);
    }
  });

  PM.on("[data-delete]", "click", async (event) => {
    const name = event.currentTarget.dataset.delete;
    if (!PM.confirmAction(`Delete "${name}" from your vault? This cannot be undone.`)) return;
    await PM.del(`/api/vault/entries/${encodeURIComponent(name)}`);
    PM.toast("Deleted from your vault.");
    App.renderView();
  });
};

/* -------------------------------------------------------------- dashboard */

App.views.dashboard = async () => {
  App.head("Dashboard", "A summary of what is on your drive.");
  const data = await PM.get("/api/dashboard");
  const usedPercent = data.storage_total_bytes
    ? Math.round((data.storage_used_bytes / data.storage_total_bytes) * 100) : 0;

  App.body(`
    <div class="section">
      <h2>Status</h2>
      <div class="spec-grid">
        <div class="spec"><span>Assistant</span><b>${data.runtime.running ? "Running locally" : "Idle"}</b></div>
        <div class="spec"><span>Model</span><b>${PM.esc(data.runtime.model_name || "None")}</b></div>
        <div class="spec"><span>Engine</span><b>${PM.esc((data.runtime.backend || "cpu").toUpperCase())}${
          data.runtime.gpu_layers ? ` · ${data.runtime.gpu_layers} GPU layers` : ""}</b></div>
        <div class="spec"><span>Vault</span><b>${data.vault.state === "unlocked" ? "Unlocked" : "Locked"} · ${data.vault.secret_count} items</b></div>
        <div class="spec"><span>Network</span><b>${data.network.online ? "Internet available" : "Offline"}</b></div>
        <div class="spec"><span>Telemetry</span><b>None</b></div>
      </div>
    </div>
    <div class="section">
      <h2>Your data</h2>
      <div class="spec-grid">
        <div class="spec"><span>Memories</span><b>${data.memory_count}</b></div>
        <div class="spec"><span>Documents</span><b>${data.document_count}</b></div>
        <div class="spec"><span>Conversations</span><b>${data.conversation_count}</b></div>
        <div class="spec"><span>Messages</span><b>${data.message_count}</b></div>
      </div>
    </div>
    <div class="section">
      <h2>Storage on ${PM.esc(data.drive_id)}</h2>
      <div class="bar-label">
        <span>PocketMind uses ${PM.bytes(data.pocketmind_bytes)}</span>
        <span>${PM.bytes(data.storage_used_bytes)} of ${PM.bytes(data.storage_total_bytes)} used</span>
      </div>
      <div class="bar-outer"><i style="width:${usedPercent}%"></i></div>
    </div>
    <div class="section">
      <h2>Controls</h2>
      <div class="toolbar">
        <button class="secondary" id="start-runtime">Start model</button>
        <button class="secondary" id="stop-runtime">Stop model</button>
        <button class="secondary" id="tutorial">Show tips</button>
      </div>
    </div>`);

  PM.one("#start-runtime").addEventListener("click", async () => {
    PM.toast("Loading the model — this can take a minute from a USB drive.");
    try {
      await PM.post("/api/runtime/start");
      await App.refreshState();
      App.paint();
    } catch (error) { PM.toast(error.hint ? `${error.message} ${error.hint}` : error.message, true); }
  });
  PM.one("#stop-runtime").addEventListener("click", async () => {
    await PM.post("/api/runtime/stop");
    await App.refreshState();
    App.paint();
  });
  PM.one("#tutorial").addEventListener("click", App.tutorial);
};

/* --------------------------------------------------------------- settings */

App.views.settings = async () => {
  App.head("Settings", "Everything is stored on your drive.");
  const [settings, models] = await Promise.all([PM.get("/api/settings"), PM.get("/api/models")]);
  App.settings = settings;

  const field = (name, label, input, help = "") =>
    `<label class="field"><span>${label}</span>${input}${help ? `<small>${help}</small>` : ""}</label>`;

  App.body(`
    <div class="section">
      <h2>Assistant</h2>
      ${field("system_prompt", "System prompt",
        `<textarea id="system_prompt" rows="5">${PM.esc(settings.system_prompt)}</textarea>`,
        "How your assistant introduces itself and what it should focus on.")}
      <div class="spec-grid">
        ${field("temperature", "Creativity",
          `<input type="number" id="temperature" step="0.1" min="0" max="2" value="${settings.temperature}">`)}
        ${field("context_length", "Context size",
          `<input type="number" id="context_length" min="512" max="131072" step="512" value="${settings.context_length}">`)}
        ${field("max_tokens", "Longest reply",
          `<input type="number" id="max_tokens" min="64" max="32768" step="64" value="${settings.max_tokens}">`)}
      </div>
    </div>

    <div class="section">
      <h2>Memory and documents</h2>
      <div class="inline-choices" style="margin-bottom:16px">
        <label><input type="checkbox" id="memory_enabled" ${settings.memory_enabled ? "checked" : ""}> Memory enabled</label>
        <label><input type="checkbox" id="auto_memory" ${settings.auto_memory ? "checked" : ""}> Save when I say "remember that…"</label>
        <label><input type="checkbox" id="documents_enabled" ${settings.documents_enabled ? "checked" : ""}> Use my documents</label>
      </div>
      <div class="spec-grid">
        ${field("memory_results", "Memories per answer",
          `<input type="number" id="memory_results" min="0" max="20" value="${settings.memory_results}">`)}
        ${field("retrieval_results", "Document passages per answer",
          `<input type="number" id="retrieval_results" min="0" max="20" value="${settings.retrieval_results}">`)}
        ${field("chunk_size", "Passage size",
          `<input type="number" id="chunk_size" min="200" max="4000" step="50" value="${settings.chunk_size}">`)}
        ${field("chunk_overlap", "Passage overlap",
          `<input type="number" id="chunk_overlap" min="0" max="1000" step="25" value="${settings.chunk_overlap}">`)}
      </div>
    </div>

    <div class="section">
      <h2>Vault and network</h2>
      <div class="spec-grid">
        ${field("vault_lock_seconds", "Auto-lock after (seconds)",
          `<input type="number" id="vault_lock_seconds" min="60" max="86400" step="60" value="${settings.vault_lock_seconds}">`)}
      </div>
      <div class="inline-choices">
        <label><input type="checkbox" id="network_allowed" ${settings.network_allowed ? "checked" : ""}> Allow internet access</label>
        <label><input type="checkbox" id="allow_model_updates" ${settings.allow_model_updates ? "checked" : ""}> Model updates</label>
        <label><input type="checkbox" id="allow_app_updates" ${settings.allow_app_updates ? "checked" : ""}> Application updates</label>
        <label><input type="checkbox" disabled> Telemetry (never)</label>
      </div>
    </div>

    <div class="toolbar"><button class="primary" id="save-settings">Save settings</button></div>

    <div class="section">
      <h2>Models on this drive</h2>
      <div class="list">
        ${models.map((model) => `
          <div class="list-row">
            <div class="grow">
              <p><b>${PM.esc(model.name)}</b>${model.installed ? '<span class="tag">Installed</span>' : ""}</p>
              <div class="meta">${PM.bytes(model.download_size_bytes)} · ${PM.esc(model.tier)} · ${PM.esc(model.license)}</div>
            </div>
            <div class="list-actions">
              ${model.installed
                ? `<button class="secondary" data-default="${PM.esc(model.id)}">Set default</button>
                   <button class="danger" data-remove="${PM.esc(model.id)}">Remove</button>`
                : `<button class="secondary" data-install="${PM.esc(model.id)}" ${model.available ? "" : "disabled"}>Install</button>`}
            </div>
          </div>`).join("")}
      </div>
    </div>

    <div class="section">
      <h2>Your data</h2>
      <div class="toolbar">
        <button class="secondary" id="export">Export my data</button>
        <button class="secondary" id="update-drive">Update the drive to this version</button>
        <button class="danger" id="eject">Eject drive safely</button>
      </div>
      <p class="intro">Exports are written to the <b>backups</b> folder on your drive and are not encrypted.</p>
    </div>`);

  PM.one("#save-settings").addEventListener("click", async () => {
    const value = (id, cast = Number) => cast(PM.one(`#${id}`).value);
    const checked = (id) => PM.one(`#${id}`).checked;
    try {
      App.settings = await PM.put("/api/settings", {
        ...settings,
        system_prompt: PM.one("#system_prompt").value,
        temperature: value("temperature"),
        context_length: value("context_length"),
        max_tokens: value("max_tokens"),
        memory_enabled: checked("memory_enabled"),
        auto_memory: checked("auto_memory"),
        documents_enabled: checked("documents_enabled"),
        memory_results: value("memory_results"),
        retrieval_results: value("retrieval_results"),
        chunk_size: value("chunk_size"),
        chunk_overlap: value("chunk_overlap"),
        vault_lock_seconds: value("vault_lock_seconds"),
        network_allowed: checked("network_allowed"),
        allow_model_updates: checked("allow_model_updates"),
        allow_app_updates: checked("allow_app_updates"),
      });
      PM.toast("Settings saved.");
    } catch (error) {
      PM.toast(error.message, true);
    }
  });

  PM.on("[data-install]", "click", async (event) => {
    PM.toast("Downloading — this can take several minutes.");
    try {
      await PM.post("/api/models/install", { model_id: event.currentTarget.dataset.install });
      PM.toast("Model installed.");
      App.renderView();
    } catch (error) { PM.toast(error.message, true); }
  });
  PM.on("[data-default]", "click", async (event) => {
    await PM.post("/api/models/default", { model_id: event.currentTarget.dataset.default });
    PM.toast("Default model updated.");
    App.renderView();
  });
  PM.on("[data-remove]", "click", async (event) => {
    if (!PM.confirmAction("Remove this model from the drive? It can be downloaded again later.")) return;
    try {
      await PM.del(`/api/models/${encodeURIComponent(event.currentTarget.dataset.remove)}`);
      PM.toast("Model removed.");
      App.renderView();
    } catch (error) { PM.toast(error.message, true); }
  });

  PM.one("#export").addEventListener("click", async () => {
    if (!PM.confirmAction(
      "This export contains your memories and conversations in readable form. Continue?")) return;
    try {
      const result = await PM.post("/api/export", {
        include_memories: true, include_conversations: true,
        include_documents: true, include_vault_names: false, acknowledge_sensitive: true });
      PM.toast(`Exported to ${result.path}`);
    } catch (error) { PM.toast(error.message, true); }
  });

  PM.one("#update-drive").addEventListener("click", async () => {
    if (!PM.confirmAction(
      "Copy this version of PocketMind onto the drive? Your memories, documents, and vault are not touched.")) return;
    try {
      const result = await PM.post("/api/system/update-drive");
      PM.toast(`Drive updated to ${result.version}. ${result.detail}`);
    } catch (error) { PM.toast(error.message, true); }
  });

  PM.one("#eject").addEventListener("click", async () => {
    if (!PM.confirmAction("Close PocketMind's files so the drive can be removed safely?")) return;
    try {
      await PM.post("/api/runtime/stop");
      await PM.post("/api/vault/lock");
    } catch { /* best effort */ }
    PM.vaultToken = null;
    PM.render(`<div class="wizard">${PM.brand()}
      <div class="card">
        <h1>Safe to remove</h1>
        <p class="intro">The model has stopped and your vault is locked. You can now eject the drive
        from Windows. Close the black PocketMind window when you are done.</p>
      </div></div>`);
  });
};

/* --------------------------------------------------------------- tutorial */

App.tutorial = () => {
  const existing = document.querySelector("#tutorial-card");
  if (existing) return;
  const node = document.createElement("div");
  node.id = "tutorial-card";
  node.className = "toast";
  node.style.maxWidth = "420px";
  node.innerHTML = `
    <b>Things you can ask</b>
    <ul style="margin:8px 0 12px 18px; padding:0; color:var(--muted); font-size:13px; line-height:1.8">
      <li>"What do you remember about me?"</li>
      <li>"Remember that I prefer FastAPI."</li>
      <li>"Search my documents for …"</li>
      <li>"Help me plan my week."</li>
      <li>"Summarise my project notes."</li>
    </ul>
    <button class="secondary" id="tutorial-close">Got it</button>`;
  document.body.append(node);
  node.querySelector("#tutorial-close").addEventListener("click", async () => {
    node.remove();
    try { await PM.post("/api/tutorial-seen"); } catch { /* not important */ }
  });
};

/* ------------------------------------------------------------------ start */

PM.boot();
