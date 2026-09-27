// Shared helpers: API access with the session token, session storage, formatting.
(function () {
  const API_OVERRIDE = new URLSearchParams(location.search).get("api");
  const API = API_OVERRIDE || "http://localhost:8000";
  // Query string to carry between pages: only the API override, never page-specific params.
  const apiQuery = () => (API_OVERRIDE ? `?api=${encodeURIComponent(API_OVERRIDE)}` : "");
  const SESSION_KEY = "career-advisor-session";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (n) => (n == null ? "—" : "$" + Number(n).toLocaleString());
  const pct = (x) => (x == null ? "—" : Math.round(x * 1000) / 10 + "%");
  const tags = (list, cls = "") =>
    list.length ? `<div class="tags">${list.map((s) => `<span class="tag ${cls}">${esc(s)}</span>`).join("")}</div>` : `<span class="muted small">None</span>`;

  // Session lives in sessionStorage (this tab only) or, with "remember", localStorage (survives
  // browser restarts until the token expires). Storage can throw in private modes, so guard it.
  function read(storage) {
    try {
      const s = JSON.parse(storage.getItem(SESSION_KEY) || "null");
      if (s && s.expires_at * 1000 > Date.now()) return s;
    } catch {}
    return null;
  }
  function getSession() { return read(sessionStorage) || read(localStorage); }
  function setSession(s, remember = false) {
    clearSession();
    try { (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, JSON.stringify(s)); } catch {}
  }
  function clearSession() {
    try { sessionStorage.removeItem(SESSION_KEY); } catch {}
    try { localStorage.removeItem(SESSION_KEY); } catch {}
  }

  function logout() { clearSession(); location.href = "index.html" + apiQuery(); }

  // Redirect to login unless signed in with the given role.
  function requireRole(role) {
    const s = getSession();
    if (!s || s.user.role !== role) { logout(); return null; }
    return s;
  }
  function homeFor(user) { return (user.role === "advisor" ? "advisor.html" : "student.html") + apiQuery(); }

  async function api(path, options = {}) {
    const s = getSession();
    const headers = { ...(options.headers || {}) };
    if (s) headers.Authorization = "Bearer " + s.token;
    const res = await fetch(API + path, { ...options, headers });
    const body = await res.json().catch(() => ({}));
    if (res.status === 401 && s) { logout(); throw new Error("Session expired"); }
    if (!res.ok) {
      const err = new Error(typeof body.detail === "string" ? body.detail : body.detail ? JSON.stringify(body.detail) : res.statusText);
      err.status = res.status; err.body = body;
      throw err;
    }
    return body;
  }

  // Minimal markdown for advisor replies: escape first, then bold, headings, bullet lists, paragraphs.
  function md(text) {
    const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").split("\n");
    let html = "", list = false;
    for (const raw of lines) {
      const line = raw.trim();
      const item = line.match(/^[*-]\s+(.*)$/);
      if (item) { if (!list) { html += "<ul>"; list = true; } html += `<li>${item[1]}</li>`; continue; }
      if (list) { html += "</ul>"; list = false; }
      if (!line) continue;
      const h = line.match(/^#{1,6}\s+(.*)$/);
      html += h ? `<h4>${h[1]}</h4>` : `<p>${line}</p>`;
    }
    return html + (list ? "</ul>" : "");
  }

  async function renderStatus(el) {
    try {
      const h = await api("/api/health");
      const g = h.services.gemini, b = h.services.backboard;
      el.innerHTML =
        `<span><span class="dot ${g.configured ? "ok" : "off"}"></span>Gemini</span>` +
        `<span><span class="dot ${b.configured ? "ok" : "off"}"></span>Backboard</span>`;
    } catch {
      el.innerHTML = `<span><span class="dot off"></span>API offline</span>`;
    }
  }

  function renderTopbar(el, session, title) {
    el.innerHTML = `
      <h1>UMBC Career Advisor</h1>
      <span class="role">${esc(session.user.role === "advisor" ? "Advisor" : "Student")}</span>
      <span class="muted small">${esc(title || session.user.display_name)}</span>
      <span class="spacer"></span>
      <span class="status" id="status"></span>
      ${window.Theme ? `<button id="theme-toggle" type="button">${Theme.get() === "light" ? "Dark" : "Light"} theme</button>` : ""}
      <button id="logout">Sign out</button>`;
    el.querySelector("#logout").addEventListener("click", logout);
    el.querySelector("#theme-toggle")?.addEventListener("click", (e) => {
      Theme.toggle();
      e.currentTarget.textContent = `${Theme.get() === "light" ? "Dark" : "Light"} theme`;
    });
    renderStatus(el.querySelector("#status"));
  }

  window.App = { API, apiQuery, $, esc, money, pct, tags, md, api, getSession, setSession, clearSession, logout, requireRole, homeFor, renderTopbar };
})();
