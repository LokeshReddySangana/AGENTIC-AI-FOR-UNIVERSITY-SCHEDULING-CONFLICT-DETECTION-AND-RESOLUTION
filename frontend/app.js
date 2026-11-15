/* Schedule Conflict Agent — console client */
const state = {
  conflicts: [],
  selected: null,
  alternatives: [],
  schedule: null,
  policy: null,
  model: null,
  version: 0,
  severity: "all",
  weeks: [],
  weekIndex: 0,
  weekTerm: null,
  resourceTables: {},
};

const CRITERIA = ["disruption", "faculty", "room", "continuity", "margin"];
const CRIT_LABEL = {
  disruption: "student disruption",
  faculty: "faculty impact",
  room: "room adequacy",
  continuity: "continuity",
  margin: "rule margin",
};
const TITLES = {
  dashboard: ["Dashboard", "University Scheduling Overview"],
  conflicts: ["Conflicts", "Detect, explain and repair scheduling conflicts"],
  timetable: ["Timetable", "Weekly view of every scheduled session"],
  model: ["Optimization", "Model performance and schedule acceptance"],
  rules: ["Alternative Schedules", "Generate and compare feasible schedule repairs"],
  audit: ["Resources", "Rooms, faculty workload and recent schedule activity"],
  reports: ["Reports", "Schedule utilization and workload analytics"],
};
const DAYS = { 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday" };
const STRATEGY_LABEL = {
  "A1-time-shift": "Time shift",
  "A2-room-change": "Room change",
  "A3-faculty-substitution": "Instructor substitution",
  "A1+A2": "Time and room change",
  "A4-combined": "Combined re-placement",
  "A6-linked-reshuffle": "Linked-group re-shuffle",
};

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const hhmm = (m) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
const dateLabel = (date) => new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(date);

function termWeeks(term) {
  const start = new Date(`${term.starts_on}T00:00:00Z`);
  const end = new Date(`${term.ends_on}T00:00:00Z`);
  const weeks = [];
  for (let cursor = new Date(start); cursor <= end; cursor.setUTCDate(cursor.getUTCDate() + 7)) {
    const weekStart = new Date(cursor);
    const weekEnd = new Date(cursor);
    weekEnd.setUTCDate(weekEnd.getUTCDate() + 6);
    weeks.push({ start: weekStart, end: weekEnd > end ? new Date(end) : weekEnd });
  }
  return weeks;
}

function renderWeekControls() {
  const options = state.weeks
    .map((week, index) => `<option value="${index}">Week ${index + 1} · ${dateLabel(week.start)}–${dateLabel(week.end)}</option>`)
    .join("");
  document.querySelectorAll(".week-select").forEach((select) => {
    select.innerHTML = options;
    select.value = String(state.weekIndex);
  });
  document.querySelectorAll(".week-step").forEach((button) => {
    const nextIndex = state.weekIndex + Number(button.dataset.step);
    button.disabled = nextIndex < 0 || nextIndex >= state.weeks.length;
  });
}

function changeTimetableWeek(index) {
  if (index < 0 || index >= state.weeks.length) return;
  state.weekIndex = index;
  renderWeekControls();
  renderTimetable("timetable", $("#dashboardGroupFilter").value);
  renderTimetable("fullTimetable", $("#fullGroupFilter").value);
}

async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  const text = await res.text();
  const data = text ? JSON.parse(text) : {};
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
  return data;
}

function toast(msg, kind = "") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast show ${kind}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = "toast"), 3600);
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    await loadStats();
    await Promise.all([loadConflicts(), loadTimetable()]);
    const rules = await api("/api/constraints");
    renderRules(rules);
    state.policy = rules.policy;
    renderPolicySliders();
    await Promise.all([loadModel(), loadAudit()]);
  } catch (err) {
    toast(err.message, "err");
  }
}

/* ------------------------------------------------------------------- KPIs */
const ICONS = {
  grid: `<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.2"/><rect x="14" y="3" width="7" height="7" rx="1.2"/><rect x="3" y="14" width="7" height="7" rx="1.2"/><rect x="14" y="14" width="7" height="7" rx="1.2"/></svg>`,
  alert: `<svg viewBox="0 0 24 24"><path d="M12 3.5l9 16.5H3z"/><path d="M12 9.5v4M12 16.5h.01"/></svg>`,
  bolt: `<svg viewBox="0 0 24 24"><path d="M13 2.5L4.5 14H11l-1 7.5L18.5 10H12z"/></svg>`,
  tree: `<svg viewBox="0 0 24 24"><circle cx="6" cy="6.5" r="2.3"/><circle cx="18" cy="6.5" r="2.3"/><circle cx="12" cy="18" r="2.3"/><path d="M8.3 6.5h7.4M7.4 8.5l3.3 7M16.6 8.5l-3.3 7"/></svg>`,
  clock: `<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5l3.2 1.9"/></svg>`,
  people: `<svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M16 5.5a3 3 0 0 1 0 5.8M17 14a4.5 4.5 0 0 1 3.5 4.4"/></svg>`,
  check: `<svg viewBox="0 0 24 24"><path d="m5 12.5 4.3 4.3L19.5 6.8"/><circle cx="12" cy="12" r="9"/></svg>`,
};

async function loadStats() {
  const [s, m, conflictData] = await Promise.all([api("/api/stats"), api("/api/model"), api("/api/conflicts")]);
  state.version = s.version;
  $("#versionChip").textContent = `v${s.version}`;
  $("#sideTerm").textContent = s.term ? s.term.name : "";
  const c = s.conflicts;
  const auc = m.trained && m.metrics ? m.metrics.auc : null;
  const conflictedSessions = new Set(conflictData.conflicts.flatMap((conflict) => conflict.session_ids || [])).size;
  const recommendationSummary = $("#recommendationSummary");
  if (recommendationSummary) {
    recommendationSummary.textContent = c.total
      ? `${c.total} open conflicts across ${s.sessions} scheduled classes. Review the highest-impact issues or compare feasible repairs ranked against institutional constraints.`
      : `All ${s.sessions} scheduled classes currently satisfy the active hard constraints.`;
  }

  const cards = [
    { label: "Scheduled classes", value: s.sessions, sub: `${s.rooms} rooms · ${s.groups} groups`, icon: ICONS.grid },
    { label: "Open conflicts", value: c.total, sub: `${Object.keys(c.by_code).length} conflict classes`, icon: ICONS.alert, cls: c.total ? "danger" : "good" },
    { label: "Critical", value: c.critical, sub: c.critical ? "needs attention" : "none outstanding", icon: ICONS.bolt, cls: c.critical ? "danger" : "good" },
    { label: "Conflict-free classes", value: Math.max(0, s.sessions - conflictedSessions), sub: "not involved in open conflicts", icon: ICONS.check, cls: "good" },
    { label: "Faculty members", value: s.faculty, sub: "total teaching staff", icon: ICONS.people },
    { label: "Model AUC", value: auc !== null ? auc.toFixed(3) : "—", sub: "random forest, held-out", icon: ICONS.tree, cls: "accent" },
  ];
  $("#kpiRow").innerHTML = cards
    .map(
      (k) => `<div class="kpi">
        <div class="kpi-label">${k.label}${k.icon}</div>
        <div class="kpi-value ${k.cls || ""}">${k.value}</div>
        <div class="kpi-sub">${esc(k.sub)}</div>
      </div>`
    )
    .join("");

  $("#statusPill").innerHTML = `<i></i><span>${c.total ? "attention needed" : "validated"}</span>`;
  $("#statusPill").classList.toggle("warn", Boolean(c.total));

  if (state.schedule) {
    $("#pageSub").textContent = `${state.schedule.term.name} · ${state.schedule.sessions.length} sessions · ${c.total} conflicts`;
  }
}

/* -------------------------------------------------------------- conflicts */
async function loadConflicts() {
  const data = await api("/api/conflicts");
  state.conflicts = data.conflicts;
  renderConflicts();
  const select = $("#alternativeConflictSelect");
  if (select) {
    const previous = select.value;
    select.innerHTML = state.conflicts
      .map((conflict) => `<option value="${conflict.conflict_id}">${esc(conflict.code)} · ${esc(conflict.severity)} · ${esc(conflict.message)}</option>`)
      .join("");
    if (state.conflicts.some((conflict) => String(conflict.conflict_id) === previous)) select.value = previous;
  }
  renderReports();
}

function renderConflicts() {
  const list = state.conflicts.filter((c) => state.severity === "all" || c.severity === state.severity);
  const critical = state.conflicts.filter((c) => c.severity === "critical").length;
  const dashboardCount = $("#conflictCount");
  const fullCount = $("#fullConflictCount");
  if (dashboardCount) dashboardCount.textContent = state.conflicts.length;
  if (fullCount) fullCount.textContent = state.conflicts.length;
  document.querySelectorAll(".severity-filter .seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.sev === state.severity)
  );

  if (!list.length) {
    const empty = `<li class="empty" style="padding:36px 8px">
      <h3>${state.conflicts.length ? "Nothing at this severity" : "Schedule validates cleanly"}</h3>
      <p>${state.conflicts.length ? "Change the filter to see the remaining conflicts." : "No hard constraint is violated."}</p></li>`;
    [$("#conflictList"), $("#fullConflictList")].filter(Boolean).forEach((host) => (host.innerHTML = empty));
    return;
  }

  const items = list
    .map(
      (c) => `<li class="conflict-item ${state.selected === c.conflict_id ? "selected" : ""}"
        data-id="${c.conflict_id}">
        <div class="ci-top">
          <span class="ci-code">${c.code} · ${c.constraint}</span>
          <span class="badge ${c.severity}">${c.severity}</span>
        </div>
        <div class="ci-msg">${esc(c.message)}</div>
        <div class="ci-foot">
          <span class="chip">${c.session_ids.length} session${c.session_ids.length > 1 ? "s" : ""}</span>
          <span class="chip">score ${Number(c.score).toFixed(0)}</span>
        </div>
      </li>`
    )
    .join("");
  [$("#conflictList"), $("#fullConflictList")].filter(Boolean).forEach((host) => (host.innerHTML = items));

  document.querySelectorAll(".conflict-item").forEach((el) =>
    el.addEventListener("click", () => selectConflict(Number(el.dataset.id), el.closest("#fullConflictList") ? "fullDetail" : "detail"))
  );
}

/* ----------------------------------------------------------------- detail */
async function selectConflict(id, detailTarget = "detail") {
  state.selected = id;
  renderConflicts();
  const detail = $(`#${detailTarget}`);
  if (!detail) return;
  detail.innerHTML = `<div class="empty"><h3>Analysing conflict…</h3>
    <p>Validating candidate placements against the constraint registry and scoring the survivors.</p></div>`;
  try {
    const data = await api(`/api/conflicts/${id}/resolve`, { method: "POST" });
    state.alternatives = data.alternatives;
    renderDetail(data.conflict, data.alternatives, detailTarget);
  } catch (err) {
    detail.innerHTML = `<div class="empty"><h3>Could not resolve</h3><p>${esc(err.message)}</p></div>`;
  }
}

function evidenceChips(conflict) {
  const e = conflict.entities || {};
  const chips = [];
  if (e.room) chips.push(`room ${esc(e.room)}`);
  if (e.faculty) chips.push(esc(e.faculty));
  if (Array.isArray(e.groups)) chips.push(e.groups.join(", "));
  if (typeof e.students === "number") chips.push(`${e.students} students`);
  if (e.day) {
    const time = e.start !== undefined ? ` ${hhmm(e.start)}–${hhmm(e.end)}` : "";
    chips.push(`${DAYS[e.day] || "day " + e.day}${time}`);
  }
  return chips.map((t) => `<span class="chip">${esc(t)}</span>`).join("");
}

function renderDetail(conflict, alternatives, detailTarget = "detail") {
  const detail = $(`#${detailTarget}`);
  if (!detail) return;
  const head = `<div class="detail-head">
    <div>
      <div class="detail-title">
        <h2>${conflict.code} · ${conflict.constraint}</h2>
        <span class="badge ${conflict.severity}">${conflict.severity}</span>
        <span class="badge neutral">severity ${Number(conflict.score).toFixed(0)}</span>
      </div>
      <p class="detail-msg">${esc(conflict.message)}</p>
      <div class="evidence">${evidenceChips(conflict)}</div>
    </div>
  </div>`;

  if (!alternatives.length) {
    detail.innerHTML = `${head}<div class="empty" style="padding:44px 20px">
      <h3>No feasible repair</h3>
      <p>Every candidate placement violates a hard constraint. This conflict needs an additional
         resource — a room, instructor or time slot — before it can be resolved.</p></div>`;
    return;
  }

  const cards = alternatives
    .map((a, i) => {
      const s = a.score;
      const crit = CRITERIA.map((k) => {
        const v = s.breakdown[k] ?? 0;
        return `<div class="crit-item ${v < 0.4 ? "weak" : ""}">
          <div class="crit-label"><span>${CRIT_LABEL[k]}</span><b>${v.toFixed(2)}</b></div>
          <div class="crit-track"><i style="width:${Math.max(2, v * 100)}%"></i></div>
        </div>`;
      }).join("");
      const learned = typeof s.learned === "number" ? s.learned : null;
      return `<article class="rec ${i === 0 ? "best" : ""}">
        <div class="rec-top">
          <span class="rec-rank">${i + 1}</span>
          <span class="rec-strategy">${esc(STRATEGY_LABEL[a.strategy] || a.strategy)}</span>
          ${i === 0 ? '<span class="badge low">recommended</span>' : ""}
          <span class="badge low">feasible</span>
          ${s.pareto ? '<span class="badge neutral">pareto</span>' : ""}
          <span class="rec-score">${s.total.toFixed(2)}<small>/1</small></span>
        </div>
        <p class="rec-text">${esc(a.explanation)}</p>
        <div class="crit">${crit}</div>
        ${
          learned !== null
            ? `<div class="learned">
                 <span>model acceptance</span>
                 <div class="track"><i style="width:${Math.round(learned * 100)}%"></i></div>
                 <b>${(learned * 100).toFixed(1)}%</b>
               </div>`
            : ""
        }
        <div class="rec-actions">
          <button class="btn secondary small" data-preview="${a.alternative_id}">Preview impact</button>
          <button class="btn primary small" data-apply="${a.alternative_id}">Apply</button>
        </div>
      </article>`;
    })
    .join("");

  detail.innerHTML = `${head}
    <div class="results-heading">
      <div>
        <span class="workspace-eyebrow">FEASIBLE CANDIDATES</span>
        <p class="rec-summary">${alternatives.length} repairs ranked by policy fit and predicted acceptance.</p>
      </div>
      <span class="ranking-note">Policy 70% <i></i> Model 30%</span>
    </div>
    <div class="rec-list">${cards}</div>`;

  detail.querySelectorAll("[data-preview]").forEach((b) =>
    b.addEventListener("click", () => previewAlternative(Number(b.dataset.preview)))
  );
  detail.querySelectorAll("[data-apply]").forEach((b) =>
    b.addEventListener("click", () => applyAlternative(Number(b.dataset.apply)))
  );
}

/* ---------------------------------------------------------------- actions */
const sessionById = (id) =>
  (state.schedule?.sessions || []).find((s) => s.id === Number(id)) || { id, course: "session", kind: "" };
const slotLabel = (id) =>
  (state.schedule?.slots || []).find((s) => s.id === Number(id))?.label || `slot ${id}`;

async function previewAlternative(altId) {
  try {
    const p = await api(`/api/alternatives/${altId}/preview`, { method: "POST" });
    const alt = p.alternative;
    const rows = alt.patch
      .map((patch) => {
        const sess = sessionById(patch.session_id);
        return `<tr>
          <td>${esc(sess.course)} ${esc(sess.kind)}</td>
          <td>${sess.slot_label ? esc(sess.slot_label) : "—"} → ${esc(slotLabel(patch.slot_id))}</td>
          <td>${esc(sess.room || "—")} → room ${patch.room_id}</td></tr>`;
      })
      .join("");
    const comps = Object.keys(p.penalty.components)
      .map(
        (k) => `<tr><td>${k}</td><td>${(p.before.components[k] ?? 0).toFixed(3)}</td>
          <td>${p.penalty.components[k].toFixed(3)}</td></tr>`
      )
      .join("");

    $("#modalTitle").textContent = "Impact preview";
    $("#modalSub").textContent = `${STRATEGY_LABEL[alt.strategy] || alt.strategy} · score ${alt.score.total.toFixed(3)}`;
    $("#modalBody").innerHTML = `
      <p class="note" style="margin-top:0">${esc(alt.explanation)}</p>
      <table class="diff-table" style="margin-top:14px">
        <thead><tr><th>Session</th><th>Slot</th><th>Room</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="hr"></div>
      <dl class="kv">
        <dt>Hard violations after</dt>
        <dd>${p.hard_violations} (baseline ${p.baseline_violations})
          ${p.patch_clean ? '· <span class="badge low">patch clean</span>' : '· <span class="badge critical">breaks a rule</span>'}</dd>
        <dt>Soft penalty</dt><dd>${p.before.total.toFixed(3)} → ${p.penalty.total.toFixed(3)}</dd>
        <dt>Model acceptance</dt>
        <dd>${typeof alt.score.learned === "number" ? (alt.score.learned * 100).toFixed(1) + "%" : "n/a"}</dd>
      </dl>
      <div class="hr"></div>
      <table class="table">
        <thead><tr><th>Soft component</th><th>Before</th><th>After</th></tr></thead>
        <tbody>${comps}</tbody>
      </table>
      <div class="modal-actions">
        <button class="btn secondary" id="modalCancel">Close</button>
        <button class="btn primary" id="modalApply">Apply this change</button>
      </div>`;
    openModal();
    $("#modalCancel").addEventListener("click", closeModal);
    $("#modalApply").addEventListener("click", () => {
      closeModal();
      applyAlternative(altId);
    });
  } catch (err) {
    toast(err.message, "err");
  }
}

async function applyAlternative(altId) {
  try {
    const res = await api(`/api/alternatives/${altId}/apply`, {
      method: "POST",
      body: JSON.stringify({ actor: "scheduler", expected_version: state.version }),
    });
    toast(`Applied · schedule at v${res.version} · ${res.remaining_conflicts.total} conflict(s) remain`, "ok");
    state.selected = null;
    await Promise.all([loadStats(), loadConflicts(), loadTimetable(), loadAudit()]);
    $("#detail").innerHTML = `<div class="empty">
      <h3>Change applied</h3>
      <p>The schedule is at version ${res.version}. ${res.remaining_conflicts.total} conflict(s) remain.
         The change is recorded in the audit log and can be rolled back.</p></div>`;
  } catch (err) {
    toast(err.message, "err");
  }
}

/* -------------------------------------------------------------- timetable */
async function loadTimetable() {
  const s = await api("/api/schedule");
  state.schedule = s;
  if (state.conflicts.length >= 0) {
    $("#pageSub").textContent = `${s.term.name} · ${s.sessions.length} sessions · ${state.conflicts.length} conflicts`;
  }
  const termKey = s.term.id ?? s.term.name;
  if (state.weekTerm !== termKey) {
    state.weeks = termWeeks(s.term);
    state.weekTerm = termKey;
    const today = new Date();
    const todayUtc = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    const currentWeek = state.weeks.findIndex((week) => todayUtc >= week.start.getTime() && todayUtc <= week.end.getTime());
    state.weekIndex = currentWeek >= 0 ? currentWeek : 0;
  }
  renderWeekControls();
  const groups = [...new Set(s.sessions.flatMap((session) => session.groups))].sort();
  document.querySelectorAll(".timetable-group-filter").forEach((select) => {
    const previous = select.dataset.ready ? select.value : "all";
    select.innerHTML = `<option value="all">All groups</option>${groups
      .map((group) => `<option value="${esc(group)}">${esc(group)}</option>`)
      .join("")}`;
    select.value = previous === "all" || groups.includes(previous) ? previous : groups[0] || "all";
    select.dataset.ready = "true";
  });

  renderTimetable("timetable", $("#dashboardGroupFilter").value);
  renderTimetable("fullTimetable", $("#fullGroupFilter").value);
  renderResources(s);
  renderReports();
}

function renderTimetable(targetId, group) {
  const s = state.schedule;
  if (!s) return;
  const sessions = group === "all" ? s.sessions : s.sessions.filter((session) => session.groups.includes(group));
  const days = [...new Set(s.slots.map((x) => x.day))].sort((a, b) => a - b);
  const bySlot = {};
  for (const sess of sessions) (bySlot[`${sess.day}-${sess.start}`] ||= []).push(sess);
  const times = [...new Set(s.slots.map((x) => x.start))].sort((a, b) => a - b);
  const selectedWeek = state.weeks[state.weekIndex];

  let html = `<table class="grid"><thead><tr><th class="time">Time</th>${days
    .map((d) => {
      const date = new Date(selectedWeek.start);
      date.setUTCDate(date.getUTCDate() + d - 1);
      return `<th>${DAYS[d] || "Day " + d}<small>${dateLabel(date)}</small></th>`;
    })
    .join("")}</tr></thead><tbody>`;
  for (const t of times) {
    html += `<tr><th class="time">${hhmm(t)}</th>`;
    for (const d of days) {
      const items = bySlot[`${d}-${t}`] || [];
      const visibleItems = group === "all" ? items.slice(0, 3) : items;
      html += `<td>${visibleItems
        .map(
          (x) => `<div class="mini ${x.kind}"><b>${esc(x.course)} · ${esc(x.room)}</b>
            <span>${esc(x.faculty)} · ${x.students} students</span></div>`
        )
        .join("")}${items.length > visibleItems.length ? `<span class="timetable-overflow">+ ${items.length - visibleItems.length} more classes</span>` : ""}</td>`;
    }
    html += `</tr>`;
  }
  $(`#${targetId}`).innerHTML = `${html}</tbody></table>`;
  const title = targetId === "timetable" ? $("#timetableTitle") : $("#fullTimetableTitle");
  if (title) title.textContent = `Weekly Timetable · ${group === "all" ? "All groups" : group}`;
}

function renderDataTable(headers, rows) {
  return `<table class="data-table"><thead><tr>${headers.map((header) => `<th>${esc(header)}</th>`).join("")}</tr></thead>
    <tbody>${rows.length ? rows.map((row) => `<tr>${row.map((cell) => `<td>${esc(cell)}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${headers.length}">No data available</td></tr>`}</tbody></table>`;
}

function renderResources(schedule) {
  const rooms = schedule.rooms || [];
  const sessions = schedule.sessions || [];
  const faculty = new Map();
  sessions.forEach((session) => {
    const workload = faculty.get(session.faculty) || { sessions: 0, minutes: 0 };
    workload.sessions += 1;
    workload.minutes += session.end - session.start;
    faculty.set(session.faculty, workload);
  });
  const activeRooms = new Set(sessions.map((session) => session.room)).size;
  const metrics = [
    ["Rooms", rooms.length, `${activeRooms} assigned this week`],
    ["Faculty", faculty.size, "with scheduled sessions"],
    ["Scheduled sessions", sessions.length, `${new Set(sessions.flatMap((session) => session.groups)).size} student groups`],
  ];
  $("#resourceMetrics").innerHTML = metrics.map(([label, value, sub]) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-sub">${sub}</div></div>`).join("");

  const roomRows = rooms
    .map((room) => {
      const scheduled = sessions.filter((session) => session.room === room.code).length;
      const utilization = schedule.slots.length ? `${Math.round((scheduled / schedule.slots.length) * 100)}%` : "0%";
      return [room.code, room.kind, room.capacity, scheduled, utilization];
    })
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));

  const facultyRows = [...faculty.entries()]
    .map(([name, workload]) => [name, workload.sessions, `${(workload.minutes / 60).toFixed(1)} h`])
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  state.resourceTables = { rooms: roomRows, faculty: facultyRows };
  renderResourceTable("rooms");
  renderResourceTable("faculty");
  renderDashboardAnalytics(schedule);
}

function renderResourceTable(kind) {
  const config = {
    rooms: { searchId: "roomSearch", hostId: "roomTable", countId: "roomResultCount", paginationId: "roomPagination", pageSize: 12, headers: ["Room", "Type", "Capacity", "Sessions", "Slot use"] },
    faculty: { searchId: "facultySearch", hostId: "facultyTable", countId: "facultyResultCount", paginationId: "facultyPagination", pageSize: 20, headers: ["Faculty member", "Sessions", "Weekly hours"] },
  }[kind];
  const rows = state.resourceTables[kind] || [];
  const search = $(`#${config.searchId}`).value.trim().toLowerCase();
  const filtered = search ? rows.filter((row) => row.some((value) => String(value).toLowerCase().includes(search))) : rows;
  const pageCount = Math.max(1, Math.ceil(filtered.length / config.pageSize));
  state[`${kind}Page`] = Math.min(state[`${kind}Page`] || 1, pageCount);
  const page = state[`${kind}Page`];
  const pageRows = filtered.slice((page - 1) * config.pageSize, page * config.pageSize);
  $(`#${config.hostId}`).innerHTML = renderDataTable(config.headers, pageRows);
  $(`#${config.countId}`).textContent = filtered.length === rows.length ? `${rows.length} total` : `${filtered.length} of ${rows.length}`;
  $(`#${config.paginationId}`).innerHTML = `
    <button type="button" data-resource-page="${kind}" data-page="${page - 1}" ${page <= 1 ? "disabled" : ""} aria-label="Previous page">‹</button>
    <span>Page ${page} of ${pageCount}</span>
    <button type="button" data-resource-page="${kind}" data-page="${page + 1}" ${page >= pageCount ? "disabled" : ""} aria-label="Next page">›</button>`;
  $(`#${config.paginationId}`).querySelectorAll("[data-resource-page]").forEach((button) =>
    button.addEventListener("click", () => {
      state[`${kind}Page`] = Number(button.dataset.page);
      renderResourceTable(kind);
    })
  );
}

function renderDashboardAnalytics(schedule) {
  const regularSlots = schedule.slots.filter((slot) => !slot.is_exam);
  const regularRooms = schedule.rooms.filter((room) => room.kind !== "exam_hall");
  const capacity = regularSlots.length * regularRooms.length;
  const used = new Set(schedule.sessions.filter((session) => session.kind !== "exam").map((session) => `${session.room}-${session.day}-${session.start}`)).size;
  const utilization = capacity ? Math.min(100, Math.round((used / capacity) * 100)) : 0;
  const donut = $(".donut-chart");
  if (donut) donut.style.background = `conic-gradient(var(--purple-bar) 0 ${utilization}%, #e1def6 ${utilization}% 100%)`;
  $("#roomUtilization").textContent = `${utilization}%`;
  $("#usedRoomSlots").textContent = `In use (${used})`;
  $("#availableRoomSlots").textContent = `Available (${Math.max(0, capacity - used)})`;

  const facultyHours = new Map();
  schedule.sessions.filter((session) => session.kind !== "exam").forEach((session) => {
    facultyHours.set(session.faculty, (facultyHours.get(session.faculty) || 0) + (session.end - session.start) / 60);
  });
  const bands = [["0–8", 0, 8], ["9–12", 9, 12], ["13–16", 13, 16], ["17–20", 17, 20], [">20", 21, Infinity]];
  const counts = bands.map(([, min, max]) => [...facultyHours.values()].filter((hours) => hours >= min && hours <= max).length);
  const maxCount = Math.max(...counts, 1);
  $("#facultyWorkloadChart").innerHTML = bands.map(([label], index) => `
    <div class="bar-group"><span class="bar-value">${counts[index]}</span>
      <div class="bar" style="height:${Math.max(4, (counts[index] / maxCount) * 76)}%;"></div><label>${label}</label>
    </div>`).join("");
}

function renderReports() {
  const schedule = state.schedule;
  if (!schedule) return;
  const conflicts = state.conflicts;
  const counts = {
    critical: conflicts.filter((conflict) => conflict.severity === "critical").length,
    high: conflicts.filter((conflict) => conflict.severity === "high").length,
    medium: conflicts.filter((conflict) => conflict.severity === "medium").length,
  };
  const roomCount = schedule.rooms?.length || 0;
  const facultyCount = new Set(schedule.sessions.map((session) => session.faculty)).size;
  const groupCount = new Set(schedule.sessions.flatMap((session) => session.groups)).size;
  $("#reportTerm").textContent = schedule.term.name;
  $("#reportMetrics").innerHTML = [
    ["Scheduled sessions", schedule.sessions.length],
    ["Rooms", roomCount],
    ["Faculty", facultyCount],
    ["Student sections", groupCount],
    ["Open conflicts", conflicts.length],
  ].map(([label, value]) => `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div></div>`).join("");

  const dailyCounts = Object.entries(DAYS).map(([day, label]) => [label, schedule.sessions.filter((session) => session.day === Number(day)).length]).filter((row) => row[1] > 0);
  $("#dayReport").innerHTML = renderDataTable(["Weekday", "Sessions"], dailyCounts);
  $("#severityReport").innerHTML = renderDataTable(["Severity", "Open conflicts"], Object.entries(counts).map(([severity, count]) => [severity, count]));
}

/* ------------------------------------------------------------------ model */
async function loadModel() {
  const m = await api("/api/model");
  state.model = m;
  if (!m.trained) {
    $("#modelMeta").textContent = "not trained yet";
    $("#modelMetrics").innerHTML = `<div class="metric"><div class="k">status</div><div class="v">—</div></div>`;
    $("#featureWeights").innerHTML = `<p class="muted">Press Retrain to fit the forest.</p>`;
    return;
  }

  const hp = m.hyperparameters || {};
  $("#modelMeta").textContent = `random forest · ${hp.n_estimators} trees · depth ${hp.max_depth} · supervised binary classification`;

  const metric = (k, v, cls = "") => `<div class="metric ${cls}"><div class="k">${k}</div><div class="v">${v}</div></div>`;
  const metrics = m.metrics || {};
  $("#modelMetrics").innerHTML = [
    metric("accuracy", metrics.accuracy?.toFixed(3) ?? "—", "highlight"),
    metric("precision", metrics.precision?.toFixed(3) ?? "—"),
    metric("recall", metrics.recall?.toFixed(3) ?? "—"),
    metric("f1", metrics.f1?.toFixed(3) ?? "—"),
    metric("auc", metrics.auc?.toFixed(3) ?? "—"),
    metric("log loss", metrics.log_loss?.toFixed(3) ?? "—"),
  ].join("");

  $("#modelParams").innerHTML = `
    <dt>Training rows</dt><dd>${m.n_train ?? "—"} train · ${m.n_test ?? "—"} held out</dd>
    <dt>Trees / depth</dt><dd>${hp.n_estimators ?? "—"} estimators · max depth ${hp.max_depth ?? "—"} · min leaf ${hp.min_samples_leaf ?? "—"}</dd>
    <dt>Trained at</dt><dd>${m.trained_at ? esc(m.trained_at.replace("T", " ").slice(0, 19)) + " UTC" : "—"}</dd>
    <dt>Label source</dt><dd>scheduler decisions (bootstrap policy + applied repairs)</dd>`;

  const imp = m.importances || [];
  const maxImp = Math.max(...imp.map((x) => x.importance), 0.001);
  $("#featureWeights").innerHTML = imp
    .map(
      (x) => `<div class="imp-row">
        <span class="imp-name">${esc(x.feature)}</span>
        <div class="imp-track"><i style="width:${Math.max(2, (x.importance / maxImp) * 100)}%"></i></div>
        <span class="imp-val">${x.importance.toFixed(3)}</span>
      </div>`
    )
    .join("");
}

async function trainModel() {
  const btn = $("#trainBtn");
  btn.disabled = true;
  btn.textContent = "Training…";
  try {
    const rep = await api("/api/model/train", { method: "POST" });
    toast(`Forest retrained · accuracy ${rep.metrics.accuracy} · AUC ${rep.metrics.auc}`, "ok");
    await Promise.all([loadModel(), loadStats(), loadAudit()]);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "Retrain";
  }
}

/* ------------------------------------------------------------------ rules */
function renderRules(data) {
  $("#hardRules").innerHTML = `<thead><tr><th>Rule</th><th>Code</th><th>Severity</th></tr></thead><tbody>` +
    data.hard
      .map(
        (r) => `<tr><td><code>${r.constraint}</code></td><td>${r.code}</td>
          <td><span class="badge ${r.severity}">${r.severity}</span></td></tr>`
      )
      .join("") + `</tbody>`;
  $("#softRules").innerHTML = `<thead><tr><th>Soft preference</th><th>Weight</th></tr></thead><tbody>` +
    Object.entries(data.soft)
      .map(([k, v]) => `<tr><td>${k}</td><td>${v.toFixed(2)}</td></tr>`)
      .join("") + `</tbody>`;
}

function renderPolicySliders() {
  const p = state.policy || {};
  $("#policySliders").innerHTML = CRITERIA.map(
    (k) => `<div class="slider-row">
      <span>${CRIT_LABEL[k]}</span>
      <input type="range" min="0" max="100" value="${Math.round((p[k] ?? 0.2) * 100)}" data-k="${k}" />
      <output data-out="${k}">${(p[k] ?? 0.2).toFixed(2)}</output>
    </div>`
  ).join("");
  document.querySelectorAll("#policySliders input").forEach((el) => {
    el.addEventListener("input", () => {
      $(`[data-out="${el.dataset.k}"]`).textContent = (Number(el.value) / 100).toFixed(2);
    });
    el.addEventListener("change", savePolicy);
  });
}

async function savePolicy() {
  const body = {};
  document.querySelectorAll("#policySliders input").forEach((el) => (body[el.dataset.k] = Number(el.value) / 100));
  try {
    state.policy = await api("/api/policy", { method: "POST", body: JSON.stringify(body) });
    renderPolicySliders();
    toast("Weights updated — ranking refreshed", "ok");
    if (state.selected) selectConflict(state.selected);
  } catch (err) {
    toast(err.message, "err");
  }
}

/* ------------------------------------------------------------------ audit */
async function loadAudit() {
  const data = await api("/api/audit?limit=40");
  const rows = data.audit
    .map(
      (a) => `<tr>
      <td style="white-space:nowrap;color:var(--muted)">${a.created_at.replace("T", " ").slice(0, 19)}</td>
      <td>${esc(a.actor)}</td>
      <td><code>${a.action}</code></td>
      <td class="muted" style="max-width:520px">${esc(a.payload ? JSON.stringify(a.payload) : "")}</td>
      <td style="text-align:right">${
        a.payload && a.payload.snapshot
          ? `<button class="link-btn" data-rollback="${a.id}">Roll back</button>`
          : ""
      }</td></tr>`
    )
    .join("");
  $("#auditTable").innerHTML = `<table class="data-table"><thead><tr><th>When</th><th>Actor</th>
    <th>Action</th><th>Detail</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
  document.querySelectorAll("[data-rollback]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        const res = await api(`/api/rollback/${b.dataset.rollback}`, { method: "POST" });
        toast(`Rolled back · v${res.rolled_back_to}`, "ok");
        await Promise.all([loadStats(), loadConflicts(), loadTimetable(), loadAudit()]);
      } catch (err) {
        toast(err.message, "err");
      }
    })
  );
}

/* ----------------------------------------------------------------- modals */
const openModal = () => $("#modal").classList.add("open");
const closeModal = () => $("#modal").classList.remove("open");

/* ----------------------------------------------------------------- events */
const detectBtn = $("#detectBtn");
if (detectBtn) {
  detectBtn.addEventListener("click", async () => {
    const btn = $("#detectBtn");
    btn.disabled = true;
    try {
      const res = await api("/api/detect", { method: "POST" });
      toast(`Detection complete · ${res.summary.total} conflicts · ${res.summary.critical} critical`,
        res.summary.total ? "" : "ok");
      state.selected = null;
      await Promise.all([loadStats(), loadConflicts(), loadAudit()]);
      $("#detail").innerHTML = `<div class="empty">
        <h3>${res.summary.total} open conflict(s)</h3>
        <p>Select one from the list to review ranked repairs.</p></div>`;
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });
}

const reseedBtn = $("#reseedBtn");
if (reseedBtn) {
  reseedBtn.addEventListener("click", async () => {
    try {
      await api("/api/seed", { method: "POST" });
      await api("/api/detect", { method: "POST" });
      state.selected = null;
      toast("Sample dataset restored", "ok");
      await Promise.all([loadStats(), loadConflicts(), loadTimetable(), loadAudit()]);
      $("#detail").innerHTML = `<div class="empty"><h3>Select a conflict</h3><p>Sample term reloaded.</p></div>`;
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

const trainBtn = $("#trainBtn");
if (trainBtn) {
  trainBtn.addEventListener("click", trainModel);
}

const modalClose = $("#modalClose");
if (modalClose) {
  modalClose.addEventListener("click", closeModal);
}

const modal = $("#modal");
if (modal) {
  modal.addEventListener("click", (e) => {
    if (e.target.id === "modal") closeModal();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeModal();
});

document.querySelectorAll(".severity-filter .seg").forEach((b) =>
  b.addEventListener("click", () => {
    state.severity = b.dataset.sev;
    renderConflicts();
  })
);

document.querySelectorAll(".timetable-group-filter").forEach((select) =>
  select.addEventListener("change", () => renderTimetable(select.dataset.target, select.value))
);

document.querySelectorAll(".week-select").forEach((select) =>
  select.addEventListener("change", () => changeTimetableWeek(Number(select.value)))
);

document.querySelectorAll(".week-step").forEach((button) =>
  button.addEventListener("click", () => changeTimetableWeek(state.weekIndex + Number(button.dataset.step)))
);

$("#roomSearch").addEventListener("input", () => {
  state.roomsPage = 1;
  renderResourceTable("rooms");
});

$("#facultySearch").addEventListener("input", () => {
  state.facultyPage = 1;
  renderResourceTable("faculty");
});

$("#openConflictsBtn").addEventListener("click", () => activateTab("conflicts"));
$("#openAlternativesBtn").addEventListener("click", () => activateTab("rules"));

const findAlternativesBtn = $("#findAlternativesBtn");
if (findAlternativesBtn) {
  findAlternativesBtn.addEventListener("click", async () => {
    const conflictId = Number($("#alternativeConflictSelect").value);
    if (!conflictId) return;
    findAlternativesBtn.disabled = true;
    findAlternativesBtn.innerHTML = "<span>Scoring repairs...</span><span aria-hidden=\"true\">◌</span>";
    try {
      await selectConflict(conflictId, "alternativeDetail");
    } finally {
      findAlternativesBtn.disabled = false;
      findAlternativesBtn.innerHTML = "<span>Generate alternatives</span><span aria-hidden=\"true\">→</span>";
    }
  });
}

function activateTab(tab) {
  document.querySelectorAll(".nav-item").forEach((x) => x.classList.toggle("active", x.dataset.tab === tab));
  document.querySelectorAll(".panel-view").forEach((p) => p.classList.remove("active"));

  const target = $(`#view-${tab}`);
  if (target) {
    target.classList.add("active");
  }

  const [title, sub] = TITLES[tab] || TITLES.dashboard;
  const pageTitle = $("#pageTitle");
  const pageSub = $("#pageSub");
  if (pageTitle) pageTitle.textContent = title;
  if (pageSub) pageSub.textContent = sub;

  if (tab === "conflicts" || tab === "timetable") {
    const term = state.schedule?.term?.name;
    if (tab === "conflicts") {
      if (pageSub) pageSub.textContent = `${term ? term + " · " : ""}${state.conflicts.length} open conflicts · ${state.conflicts.filter((c) => c.severity === "critical").length} critical`;
    } else if (term && pageSub) {
      pageSub.textContent = `${term} · ${state.schedule.sessions.length} sessions`;
    }
  }

  if (tab === "audit") loadAudit();
  if (tab === "timetable") loadTimetable();
  if (tab === "model") loadModel();
}

document.querySelectorAll(".nav-item").forEach((btn) =>
  btn.addEventListener("click", () => activateTab(btn.dataset.tab))
);

/* deep links: #timetable, #model, #conflict-12 */
async function routeFromHash() {
  const raw = location.hash.replace("#", "");
  if (!raw) return;
  const [tab, id] = raw.split("-");
  if (["conflicts", "timetable", "model", "rules", "audit", "reports"].includes(tab)) activateTab(tab);
  if (tab === "conflict" && id) {
    activateTab("conflicts");
    selectConflict(Number(id));
  }
}

boot().then(routeFromHash);
