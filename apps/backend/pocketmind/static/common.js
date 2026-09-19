/* Shared helpers for the PocketMind interface.
   Everything is namespaced on `PM` so the wizard and the app shell can share
   state without a module bundler. */

const PM = {
  root: document.querySelector("#root"),

  /* The vault session token lives in memory only. Putting it in localStorage
     would leave it behind on a borrowed computer, which is exactly what this
     product exists to avoid. */
  vaultToken: null,

  state: null,
  setupDraft: null,
};

/* ------------------------------------------------------------- formatting */

PM.esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (character) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);

PM.bytes = (value) => {
  if (value === null || value === undefined) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = Number(value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index >= 2 ? 1 : 0)} ${units[index]}`;
};

PM.when = (value) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const days = Math.floor((Date.now() - date.getTime()) / 86400000);
  if (days === 0) return `Today, ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return date.toLocaleDateString();
};

PM.stars = (count) => "★".repeat(count) + "☆".repeat(Math.max(5 - count, 0));

/* -------------------------------------------------------------------- API */

class ApiError extends Error {
  constructor(message, status, hint) {
    super(message);
    this.status = status;
    this.hint = hint || "";
  }
}
PM.ApiError = ApiError;

PM.request = async (path, { method = "GET", body, headers = {}, raw = false } = {}) => {
  const options = { method, headers: { ...headers } };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  if (PM.vaultToken) options.headers["X-Vault-Session"] = PM.vaultToken;

  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError("PocketMind is not responding. Is the window that started it still open?", 0);
  }
  if (raw) {
    if (!response.ok) throw new ApiError(await PM.detailOf(response), response.status);
    return response;
  }
  if (response.status === 204) return null;

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    throw new ApiError(
      payload?.detail || `Something went wrong (${response.status}).`,
      response.status,
      payload?.hint,
    );
  }
  return payload;
};

PM.detailOf = async (response) => {
  try {
    const body = await response.json();
    if (body?.detail) return body.hint ? `${body.detail} ${body.hint}` : body.detail;
  } catch {
    /* fall through to the readable default below */
  }
  if (response.status >= 500) {
    return "PocketMind hit an unexpected problem. Check PocketMind/logs/pocketmind.log on your drive, "
      + "and make sure the drive is still connected.";
  }
  return `PocketMind could not complete that request (${response.status}).`;
};

PM.get = (path) => PM.request(path);
PM.post = (path, body) => PM.request(path, { method: "POST", body });
PM.put = (path, body) => PM.request(path, { method: "PUT", body });
PM.patch = (path, body) => PM.request(path, { method: "PATCH", body });
PM.del = (path) => PM.request(path, { method: "DELETE" });

/* ------------------------------------------------------------------- view */

PM.render = (html) => {
  PM.root.innerHTML = html;
};

PM.on = (selector, event, handler, scope = document) => {
  scope.querySelectorAll(selector).forEach((node) => node.addEventListener(event, handler));
};

PM.one = (selector, scope = document) => scope.querySelector(selector);

PM.setError = (selector, error) => {
  const node = PM.one(selector);
  if (!node) return;
  if (!error) {
    node.textContent = "";
    return;
  }
  node.textContent = error.hint ? `${error.message} ${error.hint}` : error.message;
};

let toastTimer = null;
PM.toast = (message, bad = false) => {
  document.querySelector(".toast")?.remove();
  const node = document.createElement("div");
  node.className = `toast${bad ? " bad" : ""}`;
  node.textContent = message;
  document.body.append(node);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.remove(), bad ? 7000 : 4000);
};

PM.confirmAction = (message) => window.confirm(message);

PM.brand = () => `
  <div class="brand">
    <div class="brand-mark" aria-hidden="true">◉</div>
    <div><strong>PocketMind</strong><span>Your AI. Your memories. Your drive.</span></div>
  </div>`;

PM.progressBar = (steps, currentIndex) => `
  <section class="progress" aria-label="Setup progress">
    ${steps
      .map((label, index) => {
        const status = index === currentIndex ? "current" : index < currentIndex ? "done" : "";
        const mark = index < currentIndex ? "✓" : index + 1;
        return `<div class="progress-step ${status}"><span>${mark}</span><b>${PM.esc(label)}</b></div>`;
      })
      .join('<i></i>')}
  </section>`;
