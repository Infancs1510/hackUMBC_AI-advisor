// Renders dashboard and alumni payloads. Display only -- every number comes from the API.
(function () {
  const { esc, money, pct, tags } = window.App;

  const statusLabel = (s) => esc(s.replaceAll("_", " "));
  const experiences = (list) =>
    list.length
      ? list.map((x) => `<div class="small">${esc(x.name)} · <span class="muted">${esc(x.organization)}, ${esc(x.term)} (${esc(x.outcome)})</span></div>`).join("")
      : `<span class="muted small">None</span>`;

  function profileCard(s, heading) {
    return `
      <div class="card">
        <h2>${heading}</h2>
        <div class="stats">
          <div class="stat"><div class="v">${s.gpa ?? "—"}</div><div class="l">GPA${s.gpa == null ? " (first term)" : ""}</div></div>
          <div class="stat"><div class="v">${s.credits_earned}<span class="muted small"> / ${s.credits_required}</span></div><div class="l">Credits (+${s.credits_in_progress} in progress)</div></div>
          <div class="stat"><div class="v">${esc(s.class_level)}</div><div class="l">${esc(s.entry_type)} · grad ${esc(s.expected_graduation_term)}</div></div>
          <div class="stat"><div class="v">${s.internship_count}</div><div class="l">Internships / co-ops</div></div>
          <div class="stat"><div class="v">${s.credential_count}</div><div class="l">Credentials</div></div>
          <div class="stat"><div class="v">${s.engagement_activity_count}</div><div class="l">Activities</div></div>
        </div>
        <div class="small muted" style="margin-top:8px">Standing: ${esc(s.academic_standing)}${s.minor ? ` · Minor: ${esc(s.minor)}` : ""}${s.second_major ? ` · Second major: ${esc(s.second_major)}` : ""}</div>
        <div class="grid2" style="margin-top:14px">
          <div><strong class="small">Internships</strong>${experiences(s.internships)}</div>
          <div><strong class="small">Credentials</strong>${experiences(s.credentials)}</div>
        </div>
      </div>`;
  }

  function coursesCard(s) {
    const row = (c) => `<tr><td>${esc(c.term)}</td><td><strong>${esc(c.course_id)}</strong> <span class="muted">${esc(c.title)}</span></td><td>${c.credits}</td><td>${esc(c.grade)}</td></tr>`;
    const all = [...s.in_progress_courses, ...[...s.completed_courses].reverse()];
    if (!all.length) return "";
    return `
      <details class="card">
        <summary><strong>Courses</strong> <span class="muted small">(${s.completed_courses.length} completed, ${s.in_progress_courses.length} in progress)</span></summary>
        <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Term</th><th>Course</th><th>Cr</th><th>Grade</th></tr></thead><tbody>${all.map(row).join("")}</tbody></table></div>
      </details>`;
  }

  function renderDashboard(el, d, { onSelectCareer, heading } = {}) {
    const s = d.student;
    const p = d.pathway;
    const sal = d.salary;

    const matches = d.career_matches.map((m) => `
      <div class="match ${m.career === d.selected_career ? "sel" : ""}" data-career="${esc(m.career)}" title="Show the pathway for ${esc(m.career)}">
        <div>${esc(m.career)}</div>
        <div class="bar"><div class="p" style="width:${m.projected_score}%"></div><div class="s" style="width:${m.score}%"></div></div>
        <div class="small">${m.score}<span class="muted"> / ${m.projected_score}</span></div>
      </div>`).join("");

    const courses = p ? p.recommended_courses.map((c) => `
      <tr>
        <td><strong>${esc(c.course_id)}</strong><br><span class="muted small">${esc(c.title)}</span></td>
        <td><span class="badge ${esc(c.status)}">${statusLabel(c.status)}</span>
          ${c.missing_prerequisites.length ? `<div class="small muted">needs ${esc(c.missing_prerequisites.join(", "))}</div>` : ""}</td>
        <td>${tags(c.skills_gained)}</td>
        <td class="small">${c.offered_next_term ? "✓ " + esc(p.next_term) : `<span class="muted">${esc(c.terms_offered.join(", "))}</span>`}</td>
        <td class="small">${c.difficulty_index}</td>
      </tr>`).join("") : "";

    const steps = p && p.prerequisite_steps.length ? `
      <div style="margin-top:12px"><strong class="small">Take first</strong>
        ${p.prerequisite_steps.map((st) => `<div class="small">${esc(st.course_id)} ${esc(st.title)} <span class="badge ${esc(st.status)}">${statusLabel(st.status)}</span> <span class="muted">→ unlocks ${esc(st.unlocks.join(", "))}</span></div>`).join("")}
      </div>` : "";

    const e = sal && sal.entry_level;
    const o = p && p.alumni_outcomes;
    const seniority = sal ? Object.entries(sal.by_seniority).map(([lvl, st]) =>
      `<tr><td>${esc(lvl)}</td><td>${st.sample_size}</td><td>${money(st.median)}</td><td class="muted">${money(st.p25)} – ${money(st.p75)}</td></tr>`).join("") : "";

    el.innerHTML = `
      ${profileCard(s, heading || `${esc(s.campus_id)} · ${esc(s.major)} · ${esc(s.track)}`)}

      <div class="card">
        <h2>Skills from completed courses</h2>
        ${tags(d.skills.map((x) => x.skill))}
        ${d.in_progress_skills.length ? `<div style="margin-top:10px" class="small muted">In progress this term:</div>${tags(d.in_progress_skills.map((x) => x.skill), "ip")}` : ""}
      </div>

      <div class="card">
        <h2>Career matches <span class="sub">— score / projected after this term · click to explore</span></h2>
        ${matches}
        <div class="small muted" style="margin-top:8px">${esc(d.match_score_note)}</div>
      </div>

      ${p ? `
      <div class="card">
        <h2>Pathway to ${esc(p.career)}</h2>
        <div class="grid2">
          <div><strong class="small">Skills you have</strong>${tags(p.current_skills_matched)}</div>
          <div><strong class="small">Skills to build</strong>${tags(p.missing_skills, "miss")}</div>
        </div>
        ${courses ? `<div class="table-wrap" style="margin-top:12px">
          <table><thead><tr><th>Course</th><th>Status</th><th>Skills gained</th><th>Offered</th><th>Difficulty</th></tr></thead><tbody>${courses}</tbody></table>
        </div>` : `<div class="small muted" style="margin-top:12px">No catalog courses cover the remaining skills.</div>`}
        ${steps}
      </div>` : ""}

      ${sal ? `
      <div class="grid2">
        <div class="card">
          <h2>${esc(sal.career)} salaries (alumni)</h2>
          ${e ? `<div class="stats">
            <div class="stat"><div class="v">${money(e.median)}</div><div class="l">Entry-level median (n=${e.sample_size})</div></div>
            <div class="stat"><div class="v small">${money(e.p25)} – ${money(e.p75)}</div><div class="l">25th – 75th percentile</div></div>
          </div>` : ""}
          <div class="table-wrap" style="margin-top:10px"><table><thead><tr><th>Seniority</th><th>n</th><th>Median</th><th>IQR</th></tr></thead><tbody>${seniority}</tbody></table></div>
          <div class="small muted" style="margin-top:8px">${esc(sal.basis)}${e ? ` Start years ${e.start_year_min}–${e.start_year_max}.` : ""}</div>
        </div>
        ${o ? `<div class="card">
          <h2>Alumni who started in ${esc(p.career)}</h2>
          <div class="stats">
            <div class="stat"><div class="v">${o.alumni_count}</div><div class="l">Alumni</div></div>
            <div class="stat"><div class="v">${pct(o.share_with_internship)}</div><div class="l">Had an internship</div></div>
            <div class="stat"><div class="v">${pct(o.first_job_remote_share)}</div><div class="l">First job remote</div></div>
          </div>
          <div style="margin-top:10px"><strong class="small">How they found the job</strong>
            ${Object.entries(o.found_via).map(([k, v]) => `<div class="small">${esc(k)} <span class="muted">· ${v}</span></div>`).join("")}
          </div>
        </div>` : ""}
      </div>` : ""}

      ${coursesCard(s)}
    `;
    if (onSelectCareer) {
      el.querySelectorAll(".match").forEach((m) => m.addEventListener("click", () => onSelectCareer(m.dataset.career)));
    }
  }

  function renderAlumni(el, d) {
    const a = d.alumnus, j = d.first_job, fm = d.first_job_career_match;
    const history = d.employment_history.map((h) => `
      <tr><td class="small">${esc(h.start_date)} → ${h.end_date ? esc(h.end_date) : "<strong>current</strong>"}</td>
      <td><strong>${esc(h.job_title)}</strong><br><span class="muted small">${esc(h.employer)} · ${esc(h.region)}${h.is_remote ? " · remote" : ""}</span></td>
      <td>${esc(h.seniority_level)}</td><td>${money(h.annual_salary_usd)}</td><td class="small">${esc(h.change_type)}</td></tr>`).join("");
    el.innerHTML = `
      <div class="card">
        <h2>${esc(a.campus_id)} · Alum · ${esc(a.degree_level)}, ${esc(a.major)} (${esc(a.track)})</h2>
        <div class="stats">
          <div class="stat"><div class="v">${a.final_gpa}</div><div class="l">Final GPA</div></div>
          <div class="stat"><div class="v">${esc(a.graduation_term)}</div><div class="l">Graduated (${a.time_to_degree_years} yrs)</div></div>
          <div class="stat"><div class="v">${a.internship_count}</div><div class="l">Internships</div></div>
          <div class="stat"><div class="v">${money(a.net_cost_usd)}</div><div class="l">Net cost (${money(a.total_loans_usd)} loans)</div></div>
          <div class="stat"><div class="v small">${esc(a.first_destination)}</div><div class="l">First destination</div></div>
        </div>
      </div>
      <div class="card">
        <h2>First job</h2>
        ${j ? `<div><strong>${esc(j.title)}</strong> at ${esc(j.employer)} <span class="muted">(${esc(j.industry)}, ${esc(j.region)})</span></div>
          <div class="small">${money(j.annual_salary_usd)} nominal · ${j.is_remote ? "remote" : "on-site"} · found via ${esc(j.found_via)}${j.months_to_first_job != null ? ` · ${j.months_to_first_job} months after graduating` : ""}</div>
          ${fm ? `<div class="small muted" style="margin-top:6px">Coursework skill overlap with ${esc(fm.career)}: ${fm.score}/100</div>` : ""}`
        : `<span class="muted">No employment reported.</span>`}
      </div>
      <div class="card">
        <h2>Employment history</h2>
        ${history ? `<div class="table-wrap"><table><thead><tr><th>Dates</th><th>Role</th><th>Level</th><th>Salary</th><th>Change</th></tr></thead><tbody>${history}</tbody></table></div>
          <div class="small muted" style="margin-top:8px">${esc(d.salary_basis)}</div>` : `<span class="muted">No job records.</span>`}
      </div>
      <div class="card"><h2>Skills from coursework</h2>${tags(d.skills.map((x) => x.skill))}</div>`;
  }

  window.Dashboard = { renderDashboard, renderAlumni };
})();
