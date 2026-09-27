// Shared advisor portal chrome: header (with student search), sidebar, footer, toast. Requires common.js.
// Page layout matches the student portal: <div id="shell"></div> + .lg:pl-64 wrapper + <div id="shell-footer"></div>.
(function () {
  const { $, esc, requireRole, logout, apiQuery } = window.App;

  // href: "#…" anchors are sections of the dashboard; null = not built yet.
  const NAV = [
    { key: "dashboard", label: "Advisor Dashboard", icon: "dashboard", href: "advisor.html" },
    { key: "roster", label: "Student Roster & Triage", icon: "group", href: "roster.html" },
    { key: "plans", label: "Plan Review Queue", icon: "fact_check", href: "plans.html" },
    { key: "schedule", label: "Appointments & Schedule", icon: "calendar_month", href: "schedule.html" },
    { key: "analytics", label: "Degree Pathway Analytics", icon: "insights", href: "analytics.html" },
    { key: "reports", label: "Reports & Exports", icon: "assessment", href: "reports.html" },
  ];

  // Adds the ?api= override (if any) while keeping the link's own query and hash.
  function withApi(href) {
    const [pathAndQuery, hash] = href.split("#");
    const [path, query] = pathAndQuery.split("?");
    const params = new URLSearchParams(query || "");
    const api = new URLSearchParams(apiQuery().slice(1)).get("api");
    if (api) params.set("api", api);
    const qs = params.toString();
    return path + (qs ? "?" + qs : "") + (hash ? "#" + hash : "");
  }

  function navLink(item, active) {
    const href = item.href ? withApi(item.href) : "#";
    if (item.key === active) {
      return `<a aria-current="page" class="flex items-center gap-space-md px-space-md py-2.5 rounded-lg bg-surface-container-high text-primary font-bold shadow-[inset_3px_0_0_0_rgb(var(--c-primary-container))]" href="${href}"><span class="material-symbols-outlined text-body-lg text-primary">${item.icon}</span><span>${esc(item.label)}</span></a>`;
    }
    return `<a ${item.href ? "" : "data-soon"} class="flex items-center gap-space-md px-space-md py-2.5 rounded-lg text-body-md text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors" href="${href}"><span class="material-symbols-outlined text-body-lg text-on-surface-variant">${item.icon}</span><span>${esc(item.label)}</span>${item.href ? "" : `<span class="ml-auto text-[10px] font-label-code text-outline">SOON</span>`}</a>`;
  }

  function mount({ active }) {
    const session = requireRole("advisor");
    if (!session) return null;
    $("shell").innerHTML = `
      <aside class="hidden lg:flex fixed left-0 top-16 bottom-0 w-64 bg-surface-container-lowest z-40 flex-col justify-between border-r border-surface-container shadow-[0_4px_24px_rgb(var(--c-shadow)/0.35)] overflow-y-auto">
        <div class="flex flex-col">
          <div class="px-space-md py-space-sm bg-surface-container-low flex items-center justify-between border-b border-surface-container">
            <span class="font-label-code text-label-code text-secondary tracking-wider font-semibold">ADVISOR PORTAL</span>
            <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[11px] font-medium"><span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>Signed in</span>
          </div>
          <div class="p-space-md">
            <div class="bg-surface-container px-space-md py-space-sm rounded-lg border border-outline-variant/30">
              <div class="flex items-start gap-space-sm">
                <span class="material-symbols-outlined text-primary-container mt-0.5">school</span>
                <div class="min-w-0">
                  <div class="text-sm font-bold text-on-surface truncate" id="adv-name">Advisor</div>
                  <div class="text-[11px] text-on-surface-variant">Computer Science &amp; Information Systems advising</div>
                </div>
              </div>
              <div class="mt-space-sm pt-space-xs border-t border-outline-variant/20 flex items-center justify-between text-[11px] text-on-surface-variant">
                <span>Caseload</span><span class="font-bold text-primary px-1.5 py-0.5 bg-surface-container-highest rounded" id="adv-count">—</span>
              </div>
            </div>
          </div>
          <div class="px-space-md mb-space-xs text-[10px] text-outline uppercase tracking-wider font-label-code">Navigation</div>
          <nav class="flex flex-col px-space-sm gap-1">${NAV.map((n) => navLink(n, active)).join("")}</nav>
        </div>
        <div class="p-space-md border-t border-surface-container">
          <div class="flex items-center gap-2 text-xs text-on-surface-variant"><span class="material-symbols-outlined text-base text-primary">database</span><span>Synthetic data · HackUMBC 2026</span></div>
        </div>
      </aside>

      <header class="fixed top-0 left-0 right-0 h-16 bg-surface-container-lowest/95 backdrop-blur-xl z-50 border-b border-surface-container shadow-[0_2px_16px_rgb(var(--c-shadow)/0.3)]">
        <div class="w-full h-16 px-space-md md:px-space-lg flex items-center justify-between gap-3">
          <div class="flex items-center gap-4 min-w-0">
            <img alt="UMBC" class="h-8 w-auto object-contain shrink-0" src="assets/umbc-logo.png">
            <div class="h-6 w-px bg-outline-variant/40 hidden sm:block"></div>
            <div class="hidden sm:flex items-center gap-space-sm">
              <span class="text-body-lg font-bold text-on-surface tracking-tight">Career Intelligence</span>
              <span class="text-xs px-2 py-0.5 rounded bg-surface-container font-medium text-secondary">Advisor Portal</span>
            </div>
          </div>
          <form id="adv-search" class="hidden md:flex flex-1 max-w-md mx-space-md">
            <div class="relative w-full">
              <span class="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-outline">search</span>
              <input id="adv-search-input" class="w-full pl-10 pr-space-md py-1.5 bg-surface-container rounded-lg text-sm text-on-surface placeholder:text-outline border border-outline-variant/30 focus:outline-none focus:ring-1 focus:ring-primary" placeholder="Open a student or alum by campus ID (CID-123456)" autocomplete="off">
            </div>
          </form>
          <div class="flex items-center gap-space-md">
            <a id="adv-bell" href="${withApi("schedule.html")}" class="relative w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors" title="Upcoming appointments">
              <span class="material-symbols-outlined">notifications</span>
              <span id="adv-bell-count" class="hidden absolute -top-1 -right-1 px-1.5 py-0.5 rounded-full bg-primary-container text-on-primary text-[10px] leading-tight font-bold"></span>
            </a>
            <div class="h-6 w-px bg-outline-variant/40 hidden sm:block"></div>
            <div class="hidden sm:block text-right leading-tight">
              <div class="text-xs font-semibold text-on-surface" id="adv-header-name">Advisor</div>
              <div class="text-[11px] text-on-surface-variant">Academic advising</div>
            </div>
            ${Theme.buttonHtml("w-9 h-9 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface transition-colors")}
            <button id="logout" class="flex items-center gap-space-xs px-3 py-1.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface transition-colors font-label-code text-label-code font-medium border border-outline-variant/30" type="button"><span class="material-symbols-outlined text-body-md text-error">logout</span><span class="hidden sm:inline">Sign out</span></button>
          </div>
        </div>
      </header>
      <div id="toast" class="hidden fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] bg-surface-container-high text-on-surface text-xs px-4 py-2 rounded-lg border border-outline-variant/40 shadow-xl"></div>`;

    $("shell-footer").innerHTML = `
      <footer class="w-full bg-surface-container-lowest border-t border-surface-container py-4 mt-auto">
        <div class="max-w-[1720px] mx-auto px-space-lg flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-on-surface-variant">
          <span>Retriever Career Intelligence · Advisor portal · HackUMBC 2026 project</span>
          <span>Synthetic dataset — not real student records</span>
        </div>
      </footer>`;

    $("logout").addEventListener("click", logout);
    Theme.bind($("shell"));
    $("adv-search").addEventListener("submit", (e) => {
      e.preventDefault();
      const id = $("adv-search-input").value.trim().toUpperCase();
      if (/^CID-\d{6}$/.test(id)) location.href = withApi(`student-file.html#${id}`);
      else toast("Enter a campus ID like CID-116490.");
    });
    document.querySelectorAll("[data-soon]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      toast(`${a.textContent.replace("SOON", "").trim()} is coming soon.`);
    }));
    return session;
  }

  function setAdvisor({ name, caseload, upcoming }) {
    $("adv-name").textContent = name;
    $("adv-header-name").textContent = name;
    $("adv-count").textContent = `${caseload.toLocaleString()} students`;
    if (upcoming) { $("adv-bell-count").textContent = upcoming; $("adv-bell-count").classList.remove("hidden"); }
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 2800);
  }

  window.AdvisorShell = { mount, setAdvisor, toast, withApi };
})();
