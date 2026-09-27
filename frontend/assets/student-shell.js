// Shared student portal chrome: header, sidebar, footer, toast. Requires common.js.
//
// Page layout:
//   <div id="shell"></div>
//   <div class="lg:pl-64 flex flex-col flex-1 min-h-screen"><main class="pt-16 ...">…</main><div id="shell-footer"></div></div>
(function () {
  const { $, esc, requireRole, logout, apiQuery } = window.App;

  const IMG = {
    logo: "assets/umbc-logo.png",
    mascot: "https://lh3.googleusercontent.com/aida-public/AB6AXuCkUp3icA4g0CZZFfRXQdVOrxXHM-JfKJb3ulct4zZvA8U2kh9qMWQdvZhieVIRqfFbSqHfwN7ISdt5k4dQUsRDm555nv2J_QS-KMRD28pm_-qxWm2zsNpDT_BIG829FtEm-HINbH7ZByd8tiPYq3WR4zwNNNvPeoTwpuHrkMrGxfLBUXlzmb7p2vTcAOxHtzOAQvMgZbdCdbcCpRPyEQLZkcOoQ3-_VwIIR3HUXLJ6Gb6ZskquIT48lF5dRfVtlhO69aQ",
    footer: "assets/umbc-logo.png",
  };

  // href: null means the page isn't built yet.
  const NAV = [
    { key: "overview", label: "Overview", icon: "dashboard", href: "student.html" },
    { key: "degree", label: "Degree & Skills", icon: "school", href: "degree.html" },
    { key: "pathways", label: "Career Pathways", icon: "alt_route", href: "pathways.html" },
    { key: "plan", label: "Spring Course Plan", icon: "event_note", href: "plan.html" },
    { key: "market", label: "Market Insights", icon: "trending_up", href: "market.html" },
    { key: "appointments", label: "Advisor Appointments", icon: "event_available", href: "appointments.html" },
    { key: "resume", label: "Resume & Portfolio", icon: "description", href: "resume.html" },
  ];

  function navLink(item, active) {
    const href = item.href ? item.href + apiQuery() : "#";
    if (item.key === active) {
      return `<a aria-current="page" class="flex items-center gap-space-md px-space-md py-2.5 rounded-lg transition-colors bg-surface-container-high text-primary font-bold shadow-[inset_3px_0_0_0_#ffb300]" href="${href}"><span class="material-symbols-outlined text-body-lg text-primary">${item.icon}</span><span>${esc(item.label)}</span></a>`;
    }
    return `<a ${item.href ? "" : "data-soon"} class="flex items-center gap-space-md px-space-md py-2.5 rounded-lg text-body-md text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-colors" href="${href}"><span class="material-symbols-outlined text-body-lg text-on-surface-variant">${item.icon}</span><span>${esc(item.label)}</span>${item.href ? "" : `<span class="ml-auto text-[10px] font-label-code text-outline">SOON</span>`}</a>`;
  }

  function mount({ active }) {
    const session = requireRole("student");
    if (!session) return null;

    $("shell").innerHTML = `
      <aside id="shell-aside" class="hidden lg:flex fixed left-0 top-16 bottom-0 w-64 bg-surface-container-lowest z-40 flex-col justify-between border-r border-surface-container shadow-[0_4px_24px_rgba(0,0,0,0.6)]">
        <div class="flex flex-col">
          <div class="px-space-md py-space-sm bg-surface-container-low flex items-center justify-between border-b border-surface-container">
            <span class="font-label-code text-label-code text-secondary tracking-wider font-semibold">STUDENT PORTAL</span>
            <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 font-label-sm text-[11px] font-medium"><span class="h-1.5 w-1.5 rounded-full bg-emerald-400"></span>Active</span>
          </div>
          <div class="p-space-md flex flex-col gap-space-xs">
            <div class="bg-surface-container px-space-md py-space-sm rounded-lg flex items-center justify-between border border-outline-variant/30">
              <div class="flex flex-col min-w-0">
                <span class="font-label-sm text-label-sm text-on-surface-variant uppercase tracking-wider">Degree Plan</span>
                <span class="text-sm text-primary font-bold truncate" id="side-major">—</span>
                <span class="text-[11px] text-on-surface-variant truncate" id="side-track">&nbsp;</span>
              </div>
              <img alt="UMBC Retriever Mascot" class="w-9 h-9 object-contain drop-shadow" src="${IMG.mascot}">
            </div>
          </div>
          <nav class="flex flex-col px-space-sm gap-1 pt-1">${NAV.map((n) => navLink(n, active)).join("")}</nav>
        </div>
        <div class="p-space-md border-t border-surface-container">
          <div class="flex items-center gap-2 text-xs text-on-surface-variant"><span class="material-symbols-outlined text-base text-primary">database</span><span>Synthetic data · HackUMBC 2026</span></div>
        </div>
      </aside>

      <header id="shell-header" class="fixed top-0 left-0 right-0 h-16 bg-surface-container-lowest/95 backdrop-blur-xl z-50 border-b border-surface-container shadow-[0_2px_16px_rgba(0,0,0,0.5)]">
        <div class="w-full h-16 px-space-md md:px-space-lg flex items-center justify-between gap-3">
          <div class="flex items-center gap-4 min-w-0">
            <img alt="UMBC" class="h-8 object-contain" src="${IMG.logo}">
            <div class="h-6 w-px bg-outline-variant/40 hidden sm:block"></div>
            <div class="hidden sm:flex items-center gap-space-sm">
              <span class="text-body-lg font-bold text-on-surface tracking-tight">Career Advisor</span>
              <span class="text-xs px-2 py-0.5 rounded bg-surface-container font-medium text-secondary">Academic &amp; Career Portal</span>
            </div>
          </div>
          <div class="flex items-center gap-space-md">
            <div class="hidden lg:flex items-center gap-space-xs bg-surface-container-high px-space-md py-1.5 rounded-lg border border-outline-variant/30">
              <span class="font-label-code text-label-code text-on-surface-variant">CAMPUS ID:</span>
              <span class="font-label-code text-label-code text-primary font-bold">${esc(session.user.campus_id)}</span>
            </div>
            <div class="hidden md:flex items-center gap-space-sm">
              <div class="flex items-center gap-1.5 px-space-sm py-1 rounded-md bg-surface-container text-xs text-on-surface-variant"><span class="material-symbols-outlined text-sm text-secondary">event</span><span>Records as of Sep 15, 2026</span></div>
              <div class="hidden 2xl:flex items-center gap-1.5 px-space-sm py-1 rounded-md bg-surface-container text-xs text-on-surface-variant"><span class="h-2 w-2 rounded-full bg-emerald-400"></span><span>Fall 2026 in progress</span></div>
            </div>
            <div class="flex items-center gap-2.5">
              <div class="w-8 h-8 rounded-full bg-surface-container-highest border border-outline-variant/30 ring-2 ring-primary/40 flex items-center justify-center shrink-0 overflow-hidden">
                <svg class="w-5 h-5 text-on-surface-variant" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"></path></svg>
              </div>
              <div class="hidden xl:flex flex-col text-left">
                <span class="text-xs font-semibold text-on-surface leading-tight">${esc(session.user.campus_id)}</span>
                <span class="text-[11px] text-on-surface-variant leading-tight" id="hdr-sub">&nbsp;</span>
              </div>
            </div>
            <button id="logout" class="flex items-center gap-space-xs px-3 py-1.5 rounded-lg bg-surface-container hover:bg-surface-container-high text-on-surface-variant hover:text-on-surface transition-colors font-label-code text-label-code font-medium border border-outline-variant/30" type="button"><span class="material-symbols-outlined text-body-md text-error">logout</span><span class="hidden sm:inline">Sign out</span></button>
          </div>
        </div>
      </header>

      <div id="toast" class="hidden fixed bottom-6 left-1/2 -translate-x-1/2 z-[60] bg-surface-container-high text-on-surface text-xs px-4 py-2 rounded-lg border border-outline-variant/40 shadow-xl"></div>`;

    $("shell-footer").innerHTML = `
      <footer class="w-full bg-surface-container-lowest border-t border-surface-container py-4 mt-auto">
        <div class="max-w-[1720px] mx-auto px-space-lg flex flex-col md:flex-row items-center justify-between gap-4">
          <div class="flex items-center gap-4 text-center md:text-left">
            <img alt="UMBC" class="h-6 object-contain" src="${IMG.footer}">
            <div class="h-4 w-px bg-outline-variant/40 hidden sm:block"></div>
            <span class="text-xs text-on-surface-variant">Retriever Career Intelligence · HackUMBC 2026 project</span>
          </div>
          <div class="flex flex-wrap items-center justify-center gap-4 text-xs text-on-surface-variant">
            <span>Synthetic dataset — not real student records</span>
            <span>Salaries are nominal, not inflation-adjusted</span>
          </div>
        </div>
      </footer>`;

    $("logout").addEventListener("click", logout);
    document.querySelectorAll("[data-soon]").forEach((a) => a.addEventListener("click", (e) => {
      e.preventDefault();
      toast(`${a.textContent.replace("SOON", "").trim()} is coming soon.`);
    }));
    return session;
  }

  // Fill in the parts of the chrome that depend on the student record.
  function setStudent(s) {
    $("hdr-sub").textContent = `${s.class_level} • ${s.major}`;
    $("side-major").textContent = s.major;
    $("side-track").textContent = s.track === "General" ? "General track" : `${s.track} track`;
  }

  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 2500);
  }

  window.Shell = { mount, setStudent, toast };
})();
