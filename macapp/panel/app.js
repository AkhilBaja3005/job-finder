/* Job Finder window. Plain JavaScript, no build step. Python is reached through window.pywebview.api. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $all = (sel, root) => [...(root || document).querySelectorAll(sel)];
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many || one + "s");

  /* ── State ───────────────────────────────────────────────────────────────── */
  const IS_MAC = /Mac/i.test(navigator.platform), MOD = IS_MAC ? "⌘" : "Ctrl+";
  const isMod = (e) => (IS_MAC ? e.metaKey : e.ctrlKey);
  if (!IS_MAC) document.documentElement.classList.add("no-traffic-lights");
  const S = {
    view: "run",
    info: null,           // from api.get_state()
    form: { roles: [], location: "", timeframe: "24h", min_ats: 65, limit: 0, title_keywords: [], skip_portals: [], primary_ai: "auto", headless: false, mode: "dry_run" },
    run: { running: false, offset: 0, lines: [], counts: { found: 0, position: 0, submitted: 0, needs_review: 0, skipped: 0 }, exit: null, started: false },
    apps: { rows: null, loading: false, filter: "all", query: "", sort: { key: "", dir: 1 }, limit: 100, syncing: false },
    update: null,
    pollTimer: null,
  };
  let saveTimer = null;

  /* ── Python bridge ───────────────────────────────────────────────────────── */
  const ready = new Promise((resolve) => {
    if (window.pywebview && window.pywebview.api) resolve();
    else window.addEventListener("pywebviewready", resolve, { once: true });
  });
  async function call(name, ...args) {
    await ready;
    try {
      const result = await window.pywebview.api[name](...args);
      if (result && result.ok === false && result.error) toast(result.error, "bad");
      return result;
    } catch (err) {
      toast("Something went wrong: " + (err && err.message ? err.message : err), "bad");
      return { ok: false, error: String(err) };
    }
  }

  /* ── Small UI helpers ────────────────────────────────────────────────────── */
  function toast(message, kind) {
    const el = document.createElement("div");
    el.className = "toast" + (kind === "bad" ? " bad" : "");
    el.innerHTML = icon(kind === "bad" ? "alert" : "check") + "<span>" + esc(message) + "</span>";
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), kind === "bad" ? 6500 : 3200);
  }
  function dialog({ title, body, confirm, danger, icon: ic }) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "scrim";
      wrap.innerHTML = '<div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t">' +
        (ic ? '<div class="ic">' + icon(ic) + "</div>" : "") + '<h2 id="dlg-t">' + esc(title) + "</h2>" + body +
        '<div class="btns"><button class="btn" data-r="0">Cancel</button><button class="btn ' + (danger ? "danger" : "primary") + '" data-r="1">' + esc(confirm) + "</button></div></div>";
      const done = (v) => { document.removeEventListener("keydown", onKey, true); wrap.remove(); resolve(v); };
      const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); done(false); } };
      wrap.addEventListener("click", (e) => { const r = e.target.closest("[data-r]"); if (r) done(r.dataset.r === "1"); else if (e.target === wrap) done(false); });
      document.addEventListener("keydown", onKey, true);
      $("#overlay").appendChild(wrap);
      $('[data-r="0"]', wrap).focus();
    });
  }
  function tagsInput(id, values, placeholder) {
    return '<div class="tags" data-tags="' + id + '">' + values.map((v, i) => '<span class="tag">' + esc(v) + '<button type="button" data-rm="' + id + ":" + i + '" aria-label="Remove ' + esc(v) + '">' + icon("x") + "</button></span>").join("") +
      '<input type="text" aria-label="' + esc(placeholder) + '" placeholder="' + (values.length ? "" : esc(placeholder)) + '"></div>';
  }
  function badge(text, kind) { return '<span class="badge ' + (kind || "") + '">' + esc(text) + "</span>"; }

  /* ── Shell: sidebar, status, theme ───────────────────────────────────────── */
  const NAV = [["run", "Run", "play"], ["apps", "Applications", "list"], ["settings", "Settings", "sliders"]];
  function renderShell() {
    $("#brand-logo").innerHTML = icon("logo");
    $("#nav").innerHTML = NAV.map(([id, label, ic]) => '<button data-nav="' + id + '"' + (S.view === id ? ' aria-current="page"' : "") + ">" + icon(ic) + "<span>" + label + "</span>" +
      (id === "apps" && S.apps.rows ? '<span class="count num">' + S.apps.rows.length + "</span>" : "") + "</button>").join("");
    const i = S.info, c = i && i.supabase, b = i && i.browser;
    const cloud = !c ? ["", "Checking…"] : !c.configured ? ["", "Local only"] : c.reachable ? ["good", "Synced with Supabase"] : ["warn", "Supabase unreachable"];
    $("#conn").innerHTML = '<div class="row"><span class="dot ' + cloud[0] + '"></span>' + esc(cloud[1]) + "</div>" +
      '<div class="row"><span class="dot ' + (S.run.running ? "good pulse" : "") + '"></span>' + (S.run.running ? "Running" : "Idle") + "</div>" +
      (i ? '<div class="row" style="color:var(--text-3)">Version ' + esc(i.version) + "</div>" : "");
    const chip = $("#update-chip");
    chip.hidden = !(S.update && S.update.newer);
    if (S.update && S.update.newer) chip.textContent = "Version " + S.update.latest + " is available";
  }
  function applyTheme() {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    call("set_theme", dark);
  }
  function go(view) {
    S.view = view;
    renderShell();
    ({ run: renderRun, apps: renderApps, settings: renderSettings }[view])();
    if (view === "apps" && S.apps.rows === null) loadApps();
    if (view === "settings" && S.sched === undefined) loadSchedule();
  }
  function head(title, sub, actions) {
    return '<header class="page-head"><div><h1>' + esc(title) + '</h1><div class="sub">' + esc(sub) + '</div></div><div class="actions">' + (actions || "") + "</div></header>";
  }

  /* ── Run screen ──────────────────────────────────────────────────────────── */
  function runButton() {
    return S.run.running
      ? '<button class="btn danger lg" data-act="stop">' + icon("stop") + "Stop<kbd>" + MOD + ".</kbd></button>"
      : '<button class="btn primary lg" data-act="start">' + icon("play") + (S.form.mode === "auto_apply" ? "Start applying" : "Start practice run") + "<kbd>" + MOD + "↵</kbd></button>";
  }
  function checklist() {
    const i = S.info; if (!i) return "";
    const hasKey = Object.values(i.keys).some((k) => k.set), hasProfile = i.prefs.profile_exists, cloud = i.supabase && i.supabase.configured;
    if (hasKey && hasProfile) return "";
    const step = (done, t, d, action, label) => '<div class="check ' + (done ? "done" : "") + '"><span class="tick">' + icon("check") + '</span><div><div class="t">' + t + '</div><div class="d">' + d + "</div></div>" +
      (done ? "" : '<button class="btn" data-act="' + action + '">' + label + "</button>") + "</div>";
    return '<section class="card"><div class="card-head"><h2>Get ready</h2><span class="sub">Two quick steps before your first run</span></div><div class="checklist">' +
      step(hasKey, "Add an AI key", "Gemini, Claude or OpenAI. Gemini has a free tier.", "goto-settings", "Add a key") +
      step(hasProfile, "Create your profile", "Built from your resume. The agent fills forms with it.", "build-profile", "Choose resume…") +
      step(cloud, "Connect Supabase (optional)", "Keeps applications in your own project.", "goto-settings", "Set up") + "</div></section>";
  }
  function profileCard() {
    const pc = S.info && S.info.profile_check; if (!pc || !pc.exists || !pc.missing.length) return "";
    const needed = pc.missing.filter((m) => m.needed), shown = (needed.length ? needed : pc.missing).slice(0, 6);
    return '<section class="card" id="profile-check"><div class="card-head"><h2>' + (needed.length ? "Finish your profile" : "Optional profile details") + '</h2><span class="sub">' + pc.filled + " of " + pc.total + ' filled</span></div>' +
      '<div class="checklist">' + shown.map((m) => '<div class="check"><span class="tick">' + icon("alert") + '</span><div><div class="t">' + esc(m.label) + '</div><div class="d">' + esc(m.why) + "</div></div></div>").join("") +
      (pc.missing.length > shown.length ? '<div class="d" style="padding:4px 2px">and ' + (pc.missing.length - shown.length) + " more</div>" : "") +
      '<div class="d" style="padding:6px 2px">Open the profile, fill these in, save, then come back. This page updates by itself.</div></div>' +
      '<div style="padding:0 16px 14px;display:flex;gap:8px"><button class="btn primary" data-open="profile">Edit profile</button><button class="btn" data-act="import-profile">Import profile.json…</button></div></section>';
  }
  function renderRun() {
    const f = S.form;
    $("#view").innerHTML = head("Run", "Find jobs, tailor your resume and fill applications." + usageNote(), '<span id="run-btn">' + runButton() + "</span>") +
      '<div class="scroll"><div class="stack">' + checklist() + profileCard() + '<div class="cols">' +
      '<section class="card card-pad form" aria-label="Search settings">' +
        '<div class="field"><label>Roles</label>' + tagsInput("roles", f.roles, "Add a role and press Return") + '<div class="help">One search per role.</div></div>' +
        '<div class="two"><div class="field"><label for="f-location">Location</label><input class="input" id="f-location" value="' + esc(f.location) + '" placeholder="London, UK" autocomplete="off"></div>' +
        '<div class="field"><span class="label">Posted within</span><div class="seg" role="group" aria-label="Posted within">' +
          [["24h", "24 hours"], ["48h", "2 days"], ["1w", "1 week"]].map(([v, l]) => '<button type="button" data-time="' + v + '" aria-pressed="' + (f.timeframe === v) + '">' + l + "</button>").join("") + "</div></div></div>" +
        '<div class="field"><span class="label">What the agent does</span><div class="seg real" role="group" aria-label="Mode">' +
          '<button type="button" data-mode="dry_run" aria-pressed="' + (f.mode === "dry_run") + '">Practice run</button><button type="button" class="is-real" data-mode="auto_apply" aria-pressed="' + (f.mode === "auto_apply") + '">Apply for real</button></div>' +
          '<div class="help" id="mode-help"></div></div>' +
        '<details class="disclosure"' + (S.advOpen ? " open" : "") + '><summary>' + icon("chevron") + 'Advanced</summary><div class="inner">' +
          '<div class="two"><div class="field"><label for="f-ats">Minimum ATS score</label><input class="input num" id="f-ats" type="number" min="0" max="100" value="' + esc(f.min_ats) + '"></div>' +
          '<div class="field"><label for="f-limit">Most applications per run</label><input class="input num" id="f-limit" type="number" min="0" value="' + esc(f.limit) + '"><div class="help">0 means no limit.</div></div></div>' +
          '<div class="field"><label>Job title must contain</label>' + tagsInput("title_keywords", f.title_keywords, "e.g. intern") + "</div>" +
          '<div class="field"><label>Skip these job sites</label>' + tagsInput("skip_portals", f.skip_portals, "e.g. workday") + "</div>" +
          '<div class="two"><div class="field"><label for="f-ai">AI that drives the browser</label><select class="select" id="f-ai">' +
            [["auto", "Automatic"], ["gemini", "Gemini"], ["anthropic", "Claude"], ["openai", "OpenAI"]].map(([v, l]) => '<option value="' + v + '"' + (f.primary_ai === v ? " selected" : "") + ">" + l + "</option>").join("") + "</select></div>" +
          '<div class="field"><span class="label">Browser window</span><label class="row-between" style="font-weight:400;color:var(--text)"><span>Hide while running</span><span class="switch"><input type="checkbox" id="f-headless"' + (f.headless ? " checked" : "") + '><i></i></span></label></div></div>' +
        "</div></details>" +
      "</section>" +
      '<section class="card act-card" aria-label="Activity"><div class="card-head"><h2>Activity</h2><div class="right"><button class="btn quiet" data-act="copy-log">Copy</button><button class="btn quiet" data-act="open-logs">Open log files</button></div></div>' +
        '<div class="card-pad"><div class="status-line" aria-live="polite"><span class="dot" id="run-dot"></span><span class="state" id="run-state"></span><span class="detail" id="run-detail"></span></div>' +
        '<div class="progress" id="run-bar"><i></i></div>' +
        '<div class="tiles"><div class="tile"><b class="num" id="t-checked">0</b><span>Checked</span></div><div class="tile good"><b class="num" id="t-sub">0</b><span>Submitted</span></div>' +
          '<div class="tile warn"><b class="num" id="t-rev">0</b><span>Need review</span></div><div class="tile"><b class="num" id="t-skip">0</b><span>Skipped</span></div></div>' +
        '<div class="log-wrap"><div class="log" id="log" role="log" aria-label="Run log" tabindex="0"></div></div></div></section>' +
      "</div></div></div>";
    updateModeHelp(); renderRunStatus(); renderLog(true);
  }
  function updateModeHelp() {
    const el = $("#mode-help"); if (!el) return;
    el.textContent = S.form.mode === "auto_apply" ? "Fills each form and presses Submit. Applications cannot be taken back." : "Fills each form and stops before Submit, so you can check the result.";
  }
  function renderRunStatus() {
    const r = S.run, c = r.counts;
    if (!$("#run-state")) return;
    const dot = $("#run-dot"); dot.className = "dot" + (r.running ? " good pulse" : "");
    $("#run-state").textContent = r.running ? "Running" : r.started ? (r.exit === 0 || r.exit === null ? "Finished" : "Ended with an error") : "Ready";
    $("#run-detail").textContent = r.running ? (c.found ? "Job " + c.position + " of " + c.found : "Searching job boards…") : r.started ? plural(c.submitted, "application") + " submitted" : "Nothing is running.";
    const bar = $("#run-bar"); bar.classList.toggle("indeterminate", r.running && !c.found);
    if (c.found) $("i", bar).style.width = Math.min(100, Math.round((c.position / c.found) * 100)) + "%"; else if (!r.running) $("i", bar).style.width = "0";
    $("#t-checked").textContent = c.position; $("#t-sub").textContent = c.submitted; $("#t-rev").textContent = c.needs_review; $("#t-skip").textContent = c.skipped;
    const btn = $("#run-btn"); if (btn) btn.innerHTML = runButton();
  }
  function lineClass(t) {
    if (/verified & submitted|SUBMISSION_CONFIRMED|Synced with/.test(t)) return "ok";
    if (/Traceback|Error|failed|Failed/.test(t)) return "bad";
    if (/^\s*\[\d+\/\d+\]\s+(Skipping|⏭)/.test(t) || /Skipping/.test(t)) return "skip";
    if (/^\[\d+\/\d+\]/.test(t) || /^\[Scanner\]/.test(t)) return "head";
    if (/^—/.test(t)) return "note";
    return "";
  }
  function renderLog(full) {
    const el = $("#log"); if (!el) return;
    if (full) el.innerHTML = S.run.lines.length ? S.run.lines.map(lineHtml).join("") : '<div class="empty">The run log appears here.</div>';
    else if (S._newLines && S._newLines.length) { if ($(".empty", el)) el.innerHTML = ""; el.insertAdjacentHTML("beforeend", S._newLines.map(lineHtml).join("")); }
    S._newLines = [];
    if (S.stick !== false) el.scrollTop = el.scrollHeight;
  }
  const lineHtml = (t) => '<div class="ln ' + lineClass(t) + '">' + esc(t) + "</div>";

  /* ── Running a scan ──────────────────────────────────────────────────────── */
  async function startRun() {
    const f = S.form;
    if (!f.roles.length) { toast("Add at least one role first.", "bad"); return; }
    if (f.mode === "auto_apply") {
      const where = f.location || "your saved location";
      const ok = await dialog({
        title: "Apply for real?", icon: "alert", danger: true, confirm: "Start applying",
        body: "<p>The agent will fill in and submit applications from your accounts. This cannot be undone.</p><ul>" +
          "<li>" + plural(f.roles.length, "role") + ": <span>" + esc(f.roles.slice(0, 3).join(", ")) + (f.roles.length > 3 ? "…" : "") + "</span></li>" +
          "<li>Location: <span>" + esc(where) + "</span></li>" +
          "<li>Limit: <span>" + (Number(f.limit) > 0 ? plural(Number(f.limit), "application") : "no limit") + "</span></li></ul>",
      });
      if (!ok) return;
    }
    const res = await call("start_scan", payload());
    if (!res || !res.ok) return;
    Object.assign(S.run, { running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 0, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
    S.stick = true; renderRunStatus(); renderLog(true); renderShell(); watchRun();
  }
  const payload = () => ({ ...S.form, roles: S.form.roles.join("\n"), title_keywords: S.form.title_keywords.join(","), skip_portals: S.form.skip_portals.join(",") });
  function watchRun() { if (!S.pollTimer) S.pollTimer = setInterval(pollRun, 750); pollRun(); }
  async function pollRun() {
    const r = await call("poll", S.run.offset);
    if (!r || r.lines === undefined) return;
    S.run.offset = r.next; S._newLines = r.lines; S.run.lines.push(...r.lines); S.run.counts = r.counts;
    const was = S.run.running; S.run.running = r.running; S.run.exit = r.exit_code;
    if (S.view === "run") { renderLog(false); renderRunStatus(); }
    if (was && !r.running) {
      clearInterval(S.pollTimer); S.pollTimer = null; renderShell();
      const c = r.counts;
      toast(r.exit_code === 0 || r.exit_code === null ? "Run finished: " + plural(c.submitted, "application") + " submitted, " + c.needs_review + " to review." : "The run ended with an error. See the activity log.", r.exit_code ? "bad" : "");
      S.apps.rows = null; setTimeout(() => { if (S.view === "apps") loadApps(); else loadApps(true); }, 3000);
    }
  }

  /* ── Applications screen ─────────────────────────────────────────────────── */
  const FILTERS = [["all", "All"], ["applied", "Applied"], ["review", "Needs review"], ["progress", "Replies"], ["closed", "Closed"], ["other", "Other"]];
  const STAGES = [["applied", "I submitted it"], ["replied", "Got a reply"], ["interview", "Interview"], ["offer", "Offer"], ["rejected", "Rejected"], ["skipped", "Skip"]];
  const statusLabel = (s) => ({ applied: "Applied", review: "Needs review" }[statusKind(s)] || (/^(replied|interview|offer|rejected|skipped)/i.test(s) ? s : null) || (/ready|tailored/i.test(s) ? "Ready" : (s || "—")));
  const statusKind = (s) => (/^(replied|interview|offer)/i.test(s) ? "progress" : /^(rejected|skipped)/i.test(s) ? "closed" : /appl|submitted/i.test(s) ? "applied" : /review|fail|unsub/i.test(s) ? "review" : "other");
  async function loadApps(quiet) {
    if (!quiet) { S.apps.loading = true; if (S.view === "apps") renderApps(); }
    const rows = await call("get_results");
    S.apps.rows = Array.isArray(rows) ? rows : []; S.apps.loading = false;
    renderShell(); if (S.view === "apps") renderApps();
  }
  function filteredApps() {
    const a = S.apps; let rows = a.rows || [];
    if (a.filter !== "all") rows = rows.filter((r) => statusKind(r.status) === a.filter);
    const q = a.query.trim().toLowerCase();
    if (q) rows = rows.filter((r) => (r.company + " " + r.title + " " + r.platform).toLowerCase().includes(q));
    if (a.sort.key) {
      const k = a.sort.key, num = k === "ats";
      rows = [...rows].sort((x, y) => (num ? parseInt(x[k]) - parseInt(y[k]) || 0 : String(x[k]).localeCompare(String(y[k]))) * a.sort.dir);
    }
    return rows;
  }
  function usageNote() {
    const u = S.info && S.info.usage_today; if (!u || !u.tokens) return "";
    const t = u.tokens >= 1e6 ? (u.tokens / 1e6).toFixed(1) + "M" : u.tokens >= 1e3 ? Math.round(u.tokens / 1e3) + "K" : String(u.tokens);
    return " Today: " + t + " AI tokens" + (u.cost ? " (about $" + u.cost.toFixed(2) + ")" : "") + ".";
  }
  function stageSummary() {
    const st = (S.info && S.info.stages) || {}, bits = [];
    if (st.replied) bits.push(st.replied + " replied"); if (st.interview) bits.push(plural(st.interview, "interview")); if (st.offer) bits.push(plural(st.offer, "offer"));
    return bits.length ? " · " + bits.join(", ") : "";
  }
  function renderApps() {
    const c = S.info && S.info.supabase, a = S.apps;
    const sync = c && c.configured ? '<button class="btn" data-act="sync">' + icon("refresh") + (a.syncing ? "Syncing…" : "Sync now") + "</button>" : "";
    $("#view").innerHTML = head("Applications", a.rows ? plural(a.rows.length, "job") + " recorded" + stageSummary() + (c && c.configured ? " · your Supabase project is included" : "") : "Loading…", sync) +
      '<div class="scroll"><div class="stack"><section class="card"><div class="toolbar"><div class="search">' + icon("search") + '<input class="input" id="a-q" type="search" placeholder="Search company or role" value="' + esc(a.query) + '" aria-label="Search applications"></div>' +
      '<div class="seg" role="group" aria-label="Filter">' + FILTERS.map(([v, l]) => '<button type="button" data-filter="' + v + '" aria-pressed="' + (a.filter === v) + '">' + l + "</button>").join("") + '</div></div><div id="a-body"></div></section></div></div>';
    renderAppsBody();
  }
  function renderAppsBody() {
    const body = $("#a-body"); if (!body) return; const a = S.apps;
    if (a.loading || a.rows === null) { body.innerHTML = '<div class="card-pad">' + [1, 2, 3, 4, 5].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</div>"; return; }
    if (!a.rows.length) { body.innerHTML = '<div class="empty-state">' + icon("inbox") + "<h3>No applications yet</h3><p>Start a run and every job the agent looks at will be listed here.</p></div>"; return; }
    const rows = filteredApps();
    if (!rows.length) { body.innerHTML = '<div class="empty-state">' + icon("search") + "<h3>No matches</h3><p>Try a different search or filter.</p></div>"; return; }
    const arrow = (k) => (a.sort.key === k ? '<span class="arrow">' + (a.sort.dir > 0 ? "↑" : "↓") + "</span>" : "");
    const shown = rows.slice(0, a.limit);
    body.innerHTML = '<div class="table-wrap"><table><thead><tr><th data-sort="company">Job' + arrow("company") + '</th><th data-sort="status">Status' + arrow("status") + '</th><th data-sort="ats">ATS match' + arrow("ats") + '</th><th aria-label="In Supabase"></th><th aria-label="Open"></th></tr></thead><tbody>' +
      shown.map((r) => {
        const k = statusKind(r.status), ats = parseInt(r.ats) || 0;
        return '<tr><td class="job"><div class="co">' + esc(r.company) + '</div><div class="ro" title="' + esc(r.title) + '">' + esc(r.title) + (r.platform ? '<span class="src"> · ' + esc(r.platform) + "</span>" : "") + "</div></td>" +
          '<td title="' + esc(r.status) + '">' + badge(statusLabel(r.status), k === "applied" ? "good" : k === "review" ? "warn" : "") + "</td>" +
          '<td><span class="score num">' + (r.ats ? '<span class="bar"><i style="width:' + Math.min(100, ats) + '%"></i></span>' + esc(r.ats) : "—") + "</span></td>" +
          '<td title="' + (r.synced ? "Saved to your account" : "Only on this computer") + '">' + icon(r.synced ? "cloud" : "cloudOff", ' class="cloud-ic' + (r.synced ? "" : " off") + '"') + "</td>" +
          "<td class=\"acts\">" + (r.url ? '<button class="btn quiet" data-url="' + esc(r.url) + '" aria-label="Open ' + esc(r.title) + '">Open</button>' : "") +
          (r.url && k === "review" ? '<button class="btn quiet" data-detail="' + esc(r.url) + '">Why</button><button class="btn quiet" data-review="' + esc(r.url) + '">Review</button>' : "") +
          (r.url ? '<select class="select stage" data-stage="' + esc(r.url) + '" aria-label="Update status of ' + esc(r.title) + '"><option value="">Update…</option>' + STAGES.map(([v, l]) => '<option value="' + v + '">' + l + "</option>").join("") + "</select>" : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="foot">Showing ' + shown.length + " of " + rows.length + (rows.length > shown.length ? '&nbsp;·&nbsp;<button class="btn quiet" data-act="more">Show more</button>' : "") + "</div>";
  }

  /* ── Settings screen ─────────────────────────────────────────────────────── */
  const PROVIDERS = [["gemini", "Gemini", "Free tier available"], ["anthropic", "Claude", "Anthropic"], ["openai", "OpenAI", "GPT models"]];
  async function loadSchedule() { const r = await call("schedule_status"); if (r && r.ok) { S.sched = r; if (S.view === "settings") renderSettings(); } }
  function renderSettings() {
    const i = S.info; if (!i) { $("#view").innerHTML = head("Settings", "") + '<div class="scroll"><div class="skeleton"></div></div>'; return; }
    const sb = i.supabase, br = i.browser, cl = i.cloud || {}, mb = i.mailbox || {};
    const row = (t, d, ctl, id) => '<div class="setting"><div class="info"><div class="t">' + t + '</div><div class="d">' + d + '</div></div><div class="ctl"' + (id ? ' id="' + id + '"' : "") + ">" + ctl + "</div></div>";
    $("#view").innerHTML = head("Settings", "Your folder, AI providers and connections.") + '<div class="scroll"><div class="stack" style="max-width:820px">' +
      '<div class="sect-title">General</div><section class="card">' +
        row("Job Finder folder", esc(i.workspace), '<button class="btn" data-act="choose-ws">Change…</button><button class="btn" data-open="workspace">' + icon("folder") + "Show</button>") +
        row("Profile", i.prefs.profile_exists ? esc(i.prefs.candidate_name || "Profile found") : "No profile in this folder yet", i.prefs.profile_exists ? '<button class="btn" data-open="profile">Edit</button><button class="btn" data-act="build-profile">Rebuild from resume…</button><button class="btn" data-act="import-profile">Import…</button>' : '<button class="btn primary" data-act="build-profile">Build from resume…</button><button class="btn" data-act="import-profile">Import profile.json…</button>') +
        row("Google Chrome", i.chrome_found ? "Found. The agent drives it to fill applications." : "Not found. Install Google Chrome to let the agent fill applications.", badge(i.chrome_found ? "Installed" : "Missing", i.chrome_found ? "good" : "bad")) +
      "</section>" +
      '<div class="sect-title">AI providers</div><section class="card">' +
        PROVIDERS.map(([id, name, d]) => row(name, d, (i.keys[id].set ? badge("Saved" + (i.keys[id].hint ? " ···" + i.keys[id].hint : ""), "good") : badge("Not set")) + '<button class="btn" data-key="' + id + '">' + (i.keys[id].set ? "Replace…" : "Add key…") + "</button>", "c-" + id)).join("") +
        '<div class="setting"><div class="info"><div class="t">Keys are stored privately</div><div class="d">In the .env file inside your folder, readable only by you. They never leave this Mac except to call the provider.</div></div><div class="ctl"><button class="btn" data-open="env">Open .env</button></div></div>' +
      "</section>" +
      '<div class="sect-title">Connections</div><section class="card">' +
        row("Supabase", sb.configured ? esc(sb.host || "Configured") + (sb.reachable ? " · connected" : " · " + (sb.error ? esc(sb.error) : "cannot be reached")) : "Not set up. Add SUPABASE_URL and a key to your .env to keep applications in your own project.",
          sb.configured ? badge(sb.reachable ? "Connected" : "Unreachable", sb.reachable ? "good" : "warn") + '<button class="btn" data-act="sync">' + icon("refresh") + "Sync now</button>" : '<button class="btn" data-open="env">Open .env</button>') +
        row("job-finder.space", cl.configured ? (cl.connected ? "Applications are saved to your account" + (cl.email ? " (" + esc(cl.email) + ")" : "") + " and show on the website and in the extension." : esc(cl.error || "Cannot be reached right now.")) : "Save your applications to your job-finder.space account with your sync code. API keys never leave this Mac.",
          cl.configured ? badge(cl.connected ? "Connected" : "Unreachable", cl.connected ? "good" : "warn") + '<button class="btn" data-act="sync-cloud">' + icon("refresh") + 'Sync now</button><button class="btn" data-act="disconnect-sync">Disconnect</button>' : '<button class="btn primary" data-act="add-sync">Add sync code…</button>', "c-sync") +
        row("Reply detection", mb.configured ? "Reads the last 30 days of " + esc(mb.user) + " for replies from employers and marks them (reply, interview, rejected, offer). Read only: nothing is sent, deleted or marked read." : "Optional. Connect a mailbox with an app password and replies from employers are marked for you. Automated 'we got your application' mails are ignored.",
          badge("Beta", "accent") + (mb.configured ? '<button class="btn" data-act="check-replies">' + icon("refresh") + 'Check now</button><button class="btn" data-act="disconnect-mailbox">Disconnect</button>' : '<button class="btn" data-act="add-mailbox">Connect…</button>'), "c-mailbox") +
        row("Daily run", S.sched && S.sched.enabled ? "Runs every day at " + String(S.sched.hour).padStart(2, "0") + ":" + String(S.sched.minute).padStart(2, "0") + (S.sched.real ? ", applying for real." : " as a practice run (nothing is submitted).") + " The Mac must be awake; the app does not need to be open." : "Runs a search every day at a time you choose, without opening the app. Starts as a practice run.",
          '<input class="input" id="sched-time" type="time" value="' + (S.sched && S.sched.enabled ? String(S.sched.hour).padStart(2, "0") + ":" + String(S.sched.minute).padStart(2, "0") : "08:00") + '" style="width:110px" aria-label="Daily run time">' +
          (S.sched && S.sched.enabled ? '<button class="btn" data-act="sched-on">Change time</button><button class="btn" data-act="sched-off">Turn off</button>' : '<button class="btn primary" data-act="sched-on">Turn on</button>')) +
        row("Saved answers", "Answers to questions your profile does not cover, such as why you want the job. The agent uses them word for word instead of guessing.", '<button class="btn" data-act="edit-answers">Edit…</button>') +
        row("Job site sign-ins", "Opens the agent's Chrome so you can sign in to LinkedIn, Indeed and Reed once. Runs reuse the sign-ins.", '<button class="btn" data-act="open-signin">Open Chrome to sign in</button>') +
        row("Page scraper browser", br.ready ? "Installed" : br.installing ? "Downloading, about 150 MB…" : (br.error ? esc(br.error) : "Needed for some job sources. Downloaded once."), br.ready ? badge("Ready", "good") : br.installing ? badge("Installing", "accent") : '<button class="btn" data-act="install-browser">' + icon("download") + "Install</button>") +
      "</section>" +
      '<div class="sect-title">About</div><section class="card">' +
        row("Job Finder " + esc(i.version), S.update && S.update.newer ? "Version " + esc(S.update.latest) + " is available." : S.update ? "You are up to date." : "Check for a newer version.", '<button class="btn" data-act="check-update">Check for updates</button>' + (S.update && S.update.newer ? '<button class="btn primary" data-url="' + esc(S.update.url) + '">Download</button>' : "")) +
        row("Guided tour", "A short walk through the fields that need filling in.", '<button class="btn" data-act="start-tour">Take the tour</button>') +
        row("Report a problem", "Copies a short report (version, settings, recent log; keys and your folder path are removed) and opens an email to hello@job-finder.space. Nothing is sent until you press send.", '<button class="btn" data-act="report">Report…</button>') +
        row("Log files", "For troubleshooting. Each run is saved separately.", '<button class="btn" data-act="open-logs">Open</button>') +
      "</section></div></div>";
  }
  function keyEditor(id) {
    const name = (PROVIDERS.find((p) => p[0] === id) || [])[1];
    const ctl = $("#c-" + id); if (!ctl) return;
    ctl.innerHTML = '<span class="keybox"><input class="input" type="password" id="ki-' + id + '" placeholder="Paste your ' + esc(name) + ' key" autocomplete="off" spellcheck="false" aria-label="' + esc(name) + ' API key"><button class="btn primary" data-savekey="' + id + '">Save</button><button class="btn" data-act="cancel-key">Cancel</button></span>';
    $("#ki-" + id).focus();
  }

  /* ── Events ──────────────────────────────────────────────────────────────── */
  function saveFormSoon() { clearTimeout(saveTimer); saveTimer = setTimeout(() => call("save_prefs", payload()), 600); }
  function addTag(id, raw) {
    const vals = raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean); if (!vals.length) return;
    for (const v of vals) if (!S.form[id].some((x) => x.toLowerCase() === v.toLowerCase())) S.form[id].push(v);
    renderRun(); saveFormSoon(); const el = $('[data-tags="' + id + '"] input'); if (el) el.focus();
  }
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.matches && t.matches('.tags input')) {
      const id = t.closest("[data-tags]").dataset.tags;
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(id, t.value); }
      else if (e.key === "Backspace" && !t.value && S.form[id].length) { S.form[id].pop(); renderRun(); saveFormSoon(); const el = $('[data-tags="' + id + '"] input'); if (el) el.focus(); }
    }
    if (isMod(e) && e.key === "Enter") { e.preventDefault(); S.run.running ? call("stop_scan") : startRun(); }
    else if (isMod(e) && e.key === ".") { e.preventDefault(); call("stop_scan"); }
    else if (isMod(e) && ["1", "2", "3"].includes(e.key)) { e.preventDefault(); go(NAV[Number(e.key) - 1][0]); }
    else if (isMod(e) && e.key === ",") { e.preventDefault(); go("settings"); }
  });
  document.addEventListener("focusout", (e) => { const t = e.target; if (t.matches && t.matches(".tags input") && t.value.trim()) addTag(t.closest("[data-tags]").dataset.tags, t.value); });
  document.addEventListener("input", (e) => {
    const t = e.target, f = S.form;
    if (t.id === "f-location") f.location = t.value; else if (t.id === "f-ats") f.min_ats = t.value; else if (t.id === "f-limit") f.limit = t.value;
    else if (t.id === "a-q") { S.apps.query = t.value; renderAppsBody(); return; } else return;
    saveFormSoon();
  });
  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset && t.dataset.stage) { const url = t.dataset.stage, v = t.value; t.value = ""; if (!v) return;
      call("set_status", url, v).then(async (r) => { if (r && r.ok) { toast("Status updated."); await loadApps(true); await refreshInfo(); } else toast((r && r.error) || "Could not update.", "bad"); }); return; }
    if (t.id === "f-ai") { S.form.primary_ai = t.value; call("save_app_prefs", { primary_ai: t.value }); }
    else if (t.id === "f-headless") { S.form.headless = t.checked; call("save_app_prefs", { headless: t.checked }); }
  });
  document.addEventListener("toggle", (e) => { if (e.target.classList && e.target.classList.contains("disclosure")) S.advOpen = e.target.open; }, true);
  $("#log") || document.addEventListener("scroll", (e) => { if (e.target.id === "log") { const l = e.target; S.stick = l.scrollTop + l.clientHeight >= l.scrollHeight - 30; } }, true);

  document.addEventListener("click", async (e) => {
    const el = e.target.closest("button, [data-nav], th[data-sort]"); if (!el) return;
    const d = el.dataset;
    if (d.nav) return go(d.nav);
    if (d.rm) { const [id, idx] = d.rm.split(":"); S.form[id].splice(Number(idx), 1); renderRun(); saveFormSoon(); return; }
    if (d.time) { S.form.timeframe = d.time; renderRun(); saveFormSoon(); return; }
    if (d.mode) { S.form.mode = d.mode; renderRun(); return; }
    if (d.review) { toast("Opening the job in Chrome…"); const r = await call("review_in_chrome", d.review); toast(r && r.ok ? "Opened. Check the form and submit it there." : (r && r.error) || "Could not open Chrome.", r && r.ok ? undefined : "bad"); return; }
    if (d.detail) { const r = await call("review_info", d.detail); const has = r && r.screenshot;
      const ok = await dialog({ title: "Why it stopped", body: "<p>" + esc((r && r.reason) || "No reason was recorded for this job. Open the job and check the form yourself.") + "</p>", confirm: has ? "Open screenshot" : "OK" });
      if (ok && has) call("open_screenshot", d.detail); return; }
    if (d.filter) { S.apps.filter = d.filter; S.apps.limit = 100; renderApps(); return; }
    if (d.sort) { const s = S.apps.sort; s.dir = s.key === d.sort ? -s.dir : 1; s.key = d.sort; renderAppsBody(); return; }
    if (d.url) return void call("open_url", d.url);
    if (d.open) return void call("open_path", d.open);
    if (d.key) return keyEditor(d.key);
    if (d.savekey) {
      const v = $("#ki-" + d.savekey).value; const r = await call("save_key", d.savekey, v);
      if (r && r.ok) { toast("Key saved."); await refreshInfo(); renderSettings(); } return;
    }
    switch (d.act) {
      case "start": return startRun();
      case "cancel-key": return renderSettings();
      case "add-sync": { const ctl = $("#c-sync"); if (!ctl) return; ctl.innerHTML = '<span class="keybox"><input class="input" type="password" id="si-sync" placeholder="Your sync code" autocomplete="off" spellcheck="false" maxlength="16" aria-label="Sync code"><button class="btn primary" data-act="save-sync">Connect</button><button class="btn" data-act="cancel-key">Cancel</button></span>'; $("#si-sync").focus(); return; }
      case "save-sync": { const r = await call("save_sync_code", $("#si-sync").value); if (r && r.ok) { toast("Connected to job-finder.space."); await refreshInfo(); renderSettings(); } else toast((r && r.error) || "Could not connect.", "bad"); return; }
      case "disconnect-sync": { await call("disconnect_sync"); toast("Disconnected. Your applications stay on this Mac."); await refreshInfo(); renderSettings(); return; }
      case "sync-cloud": { const r = await call("sync_cloud_now"); if (r && r.ok) toast(r.pushed ? "Added " + plural(r.pushed, "application") + " to job-finder.space." : "job-finder.space is up to date."); else toast((r && r.error) || "Sync failed.", "bad"); await refreshInfo(); renderSettings(); return; }
      case "stop": return void call("stop_scan");
      case "goto-settings": return go("settings");
      case "choose-ws": { const r = await call("choose_workspace"); if (r && r.ok) { S.info = r.state; S.apps.rows = null; hydrateForm(); toast("Folder changed."); go(S.view); } return; }
      case "build-profile": { const r = await call("choose_resume_and_build_profile"); if (r && r.ok) { go("run"); Object.assign(S.run, { running: true, started: true, offset: 0, lines: [], exit: null }); renderRunStatus(); renderLog(true); watchRun(); } return; }
      case "import-profile": { const r = await call("choose_profile_and_import"); if (r && r.ok) { toast("Profile imported" + (r.name ? " for " + r.name : "") + "."); await refreshInfo(); hydrateForm(); renderView(); } else if (r && r.error) toast(r.error, "bad"); return; }
      case "open-signin": { toast("Opening Chrome…"); const r = await call("open_signin"); toast(r && r.ok ? "Chrome is open. Sign in, then close it before a run." : (r && r.error) || "Could not open Chrome.", r && r.ok ? undefined : "bad"); return; }
      case "report": { const r = await call("problem_report"); if (r && r.ok) { try { await navigator.clipboard.writeText(r.text); toast("Report copied. Paste it into the email."); } catch (_) { toast("Could not copy the report. Open the log files instead.", "bad"); } call("open_url", "mailto:hello@job-finder.space?subject=Job%20Finder%20problem"); } return; }
      case "sched-on": { const t = ($("#sched-time") || {}).value || "08:00"; const [h, m] = t.split(":").map(Number);
        const r = await call("set_schedule", true, h, m, false); if (r && r.ok) { toast("Daily practice run scheduled for " + t + "."); S.sched = await call("schedule_status"); renderSettings(); } else toast((r && r.error) || "Could not schedule.", "bad"); return; }
      case "sched-off": { await call("set_schedule", false); S.sched = await call("schedule_status"); toast("Daily run turned off."); renderSettings(); return; }
      case "add-mailbox": { const ctl = $("#c-mailbox"); if (!ctl) return; ctl.innerHTML = '<span class="keybox"><input class="input" id="mb-user" type="email" placeholder="you@gmail.com" autocomplete="off" aria-label="Mailbox address"><input class="input" id="mb-pass" type="password" placeholder="App password" autocomplete="off" aria-label="App password"><button class="btn primary" data-act="save-mailbox">Connect</button><button class="btn" data-act="cancel-key">Cancel</button></span>'; $("#mb-user").focus(); return; }
      case "save-mailbox": { const r = await call("save_mailbox", $("#mb-user").value, $("#mb-pass").value, ""); if (r && r.ok) { toast("Mailbox connected."); await refreshInfo(); renderSettings(); } else toast((r && r.error) || "Could not connect.", "bad"); return; }
      case "disconnect-mailbox": { await call("disconnect_mailbox"); toast("Mailbox disconnected."); await refreshInfo(); renderSettings(); return; }
      case "check-replies": { toast("Checking your mailbox…"); const r = await call("check_replies_now"); if (r && r.ok) { toast(r.updated ? plural(r.updated, "application") + " moved forward." : "No new replies found (" + r.checked + " messages read)."); await loadApps(true); await refreshInfo(); } else toast((r && r.error) || "Could not check.", "bad"); return; }
      case "edit-answers": return void openAnswersEditor();
      case "start-tour": return void startTour();
      case "install-browser": await call("ensure_browser"); await refreshInfo(); renderSettings(); watchBrowser(); return;
      case "sync": { if (S.apps.syncing) return; S.apps.syncing = true; renderView(); const r = await call("sync_now"); S.apps.syncing = false;
        if (r && r.ok) toast(r.pushed ? "Added " + plural(r.pushed, "application") + " to Supabase." : "Supabase is up to date."); await loadApps(true); await refreshInfo(); renderView(); return; }
      case "more": S.apps.limit += 200; renderAppsBody(); return;
      case "copy-log": { try { await navigator.clipboard.writeText(S.run.lines.join("\n")); toast("Log copied."); } catch (_) { toast("Could not copy the log.", "bad"); } return; }
      case "open-logs": return void call("open_path", "logs");
      case "check-update": { const r = await call("check_update"); S.update = r && r.ok ? r : S.update; renderShell(); if (S.view === "settings") renderSettings(); if (r && r.ok && !r.newer) toast("You are on the latest version."); return; }
    }
  });
  const renderView = () => ({ run: renderRun, apps: renderApps, settings: renderSettings }[S.view])();
  $("#update-chip").addEventListener("click", () => S.update && call("open_url", S.update.url));

  /* ── Start-up ────────────────────────────────────────────────────────────── */
  // Pick up changes made outside the window (the .env file, a new profile) when the user comes back to it.
  let lastFocusRefresh = 0;
  window.addEventListener("focus", () => { if (Date.now() - lastFocusRefresh > 1500) { lastFocusRefresh = Date.now(); refreshInfo().then(() => { if (S.view === "settings") renderSettings(); }); } });
  async function refreshInfo() { const s = await call("get_state"); if (s && s.workspace) { S.info = s; renderShell(); } return s; }
  function hydrateForm() {
    const p = S.info.prefs;
    Object.assign(S.form, { roles: p.roles, location: p.location, timeframe: ["24h", "48h", "1w"].includes(p.timeframe) ? p.timeframe : "24h", min_ats: p.min_ats,
      title_keywords: p.title_keywords, skip_portals: p.skip_portals, primary_ai: (S.info.app_prefs || {}).primary_ai || "auto", headless: !!(S.info.app_prefs || {}).headless });
  }
  function watchBrowser() {
    if (S._bt) return;
    S._bt = setInterval(async () => { const s = await refreshInfo(); if (S.view === "settings") renderSettings(); if (!s || !s.browser.installing) { clearInterval(S._bt); S._bt = null; } }, 3000);
  }


  /* ── Saved answers: a form instead of a JSON file ────────────────────────── */
  async function openAnswersEditor() {
    const data = await call("get_saved_answers");
    if (!data || !data.ok) { toast("Could not open your saved answers.", "bad"); return; }
    const max = data.max_entries, maxChars = data.max_chars;
    const items = data.items.length ? data.items.slice() : [{ question: "", answer: "" }];
    const wrap = document.createElement("div"); wrap.className = "scrim";
    const rowHtml = (it, i) => '<div class="aa-item" data-i="' + i + '"><div class="aa-head"><label for="aa-q-' + i + '">Question</label>' +
      '<button type="button" class="btn quiet" data-aa="delete" data-i="' + i + '" aria-label="Delete this answer">Delete</button></div>' +
      '<input class="input" id="aa-q-' + i + '" data-aa-q="' + i + '" maxlength="200" value="' + esc(it.question) + '" placeholder="e.g. Why do you want to work here?">' +
      '<label for="aa-a-' + i + '">Your answer</label>' +
      '<textarea class="input" id="aa-a-' + i + '" data-aa-a="' + i + '" rows="3" maxlength="' + maxChars + '" placeholder="Write it the way you want it typed">' + esc(it.answer) + "</textarea></div>";
    const draw = () => {
      const unused = data.suggestions.filter((q) => !items.some((it) => it.question.trim().toLowerCase() === q.toLowerCase()));
      wrap.innerHTML = '<div class="dialog wide" role="dialog" aria-modal="true" aria-labelledby="aa-title"><h2 id="aa-title">Saved answers</h2>' +
        "<p>Answers to questions your profile does not cover. When a form asks the same thing, the agent types your answer exactly as written instead of guessing.</p>" +
        '<div class="aa-list">' + items.map(rowHtml).join("") + "</div>" +
        '<div class="aa-add">' + (items.length < max ? '<button type="button" class="btn" data-aa="add">+ Add an answer</button>' : '<span class="d">You have reached the limit of ' + max + ".</span>") +
        unused.slice(0, 4).map((q) => '<button type="button" class="chip" data-aa="suggest" data-q="' + esc(q) + '">' + esc(q) + "</button>").join("") + "</div>" +
        '<div class="btns"><button type="button" class="btn" data-aa="cancel">Cancel</button><button type="button" class="btn primary" data-aa="save">Save</button></div></div>';
    };
    const collect = () => $all(".aa-item", wrap).forEach((el) => { items[Number(el.dataset.i)] = { question: $("[data-aa-q]", el).value, answer: $("[data-aa-a]", el).value }; });
    const close = () => { document.removeEventListener("keydown", onKey, true); wrap.remove(); };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
    wrap.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-aa]");
      if (!b) { if (e.target === wrap) close(); return; }
      collect();
      const act = b.dataset.aa;
      if (act === "cancel") return close();
      if (act === "add") { items.push({ question: "", answer: "" }); draw(); const last = $all(".aa-item", wrap).pop(); if (last) $("[data-aa-q]", last).focus(); return; }
      if (act === "suggest") {
        const entry = { question: b.dataset.q, answer: "" }, blank = items.findIndex((it) => !it.question.trim() && !it.answer.trim());
        if (blank >= 0) items[blank] = entry; else items.push(entry);
        draw(); const el = $('[data-aa-a="' + items.indexOf(entry) + '"]', wrap); if (el) el.focus(); return;
      }
      if (act === "delete") { items.splice(Number(b.dataset.i), 1); if (!items.length) items.push({ question: "", answer: "" }); draw(); return; }
      if (act === "save") {
        if (items.some((it) => Boolean(it.question.trim()) !== Boolean(it.answer.trim()))) { toast("Each answer needs both a question and an answer.", "bad"); return; }
        const r = await call("save_saved_answers", items);
        if (r && r.ok) { close(); toast(r.saved ? plural(r.saved, "answer") + " saved." : "Saved answers cleared."); } else toast("Could not save.", "bad");
      }
    });
    document.addEventListener("keydown", onKey, true); draw(); $("#overlay").appendChild(wrap);
    const first = $("[data-aa-q]", wrap); if (first) first.focus();
  }

  /* ── Moving the window by its top bar ───────────────────────────────────── */
  // Elements marked data-drag (the empty top bar and the logo area) move the window. Buttons inside them still click.
  (function enableWindowDrag() {
    let start = null, pending = null, raf = 0;
    const flush = () => { raf = 0; if (pending && start) { call("drag_to", pending.dx, pending.dy); pending = null; } };
    document.addEventListener("mousedown", (e) => {
      if (e.button !== 0 || !e.target.closest("[data-drag]") || e.target.closest("button, a, input, select, textarea, [data-nav]")) return;
      if (e.detail === 2) { call("zoom_window"); return; }
      start = { x: e.screenX, y: e.screenY }; call("drag_start"); e.preventDefault();
    });
    document.addEventListener("mousemove", (e) => {
      if (!start) return;
      if (e.buttons !== 1) { start = null; return; }
      pending = { dx: e.screenX - start.x, dy: e.screenY - start.y };
      if (!raf) raf = requestAnimationFrame(flush);
    });
    const stop = () => { start = null; pending = null; };
    document.addEventListener("mouseup", stop); window.addEventListener("blur", stop);
  })();

  /* ── Guided tour ─────────────────────────────────────────────────────────── */
  const TOUR = [
    { view: "settings", sel: "#c-gemini", title: "Add an AI key", text: "The agent needs one provider to read job pages and fill forms. Gemini has a free tier. Claude and OpenAI work too. Keys stay in a file on this Mac." },
    { view: "settings", sel: '[data-act="build-profile"], [data-act="import-profile"]', title: "Create your profile", text: "Build it from your resume, or import a profile.json you already have. Every form is filled from it, so details like work authorisation matter." },
    { view: "settings", sel: '[data-act="open-signin"]', title: "Sign in to job sites", text: "LinkedIn, Indeed and Reed work best when you are signed in. This opens the agent's own Chrome once. Sign in, close it, and every run reuses the sign-ins." },
    { view: "settings", sel: "#c-sync", title: "Save applications to your account", text: "Optional. Paste your sync code from job-finder.space and every application is saved to your account, so it shows on the website and in the extension too. API keys and your resume file never leave this computer." },
    { view: "settings", sel: "#c-mailbox", title: "See replies automatically", text: "Optional. Connect your mailbox with an app password and employer replies, interviews and rejections are marked for you. It only reads, and ignores automatic 'we got your application' emails." },
    { view: "settings", sel: '[data-act="edit-answers"]', title: "Write answers once", text: "For questions your profile cannot answer, such as why you want the job. The agent types your answer word for word instead of guessing." },
    { view: "settings", sel: "#sched-time", title: "Run every morning", text: "Optional. Pick a time and a practice run starts by itself, even when the app is closed. The computer must be awake." },
    { view: "run", sel: "#profile-check", title: "Fill what is missing", text: "This list shows profile fields that are still empty. Edit the profile, save, and come back. The list updates by itself." },
    { view: "run", sel: '[data-tags="roles"]', title: "Choose roles", text: "One search runs per role. Leave it empty to use the roles from your profile." },
    { view: "run", sel: "#f-location", title: "Set the location", text: "Where to look for jobs, for example London, UK." },
    { view: "run", sel: "#run-btn", title: "Start with a practice run", text: "A practice run fills every form but never presses Submit, so you can check the result. Switch to Apply for real only when you trust it." },
    { view: "apps", sel: '[data-nav="apps"]', title: "Check your applications", text: "Every job the agent handled is listed here with its status. Rows marked Needs review are waiting for you." },
  ];
  async function startTour() {
    // A step about missing profile fields only makes sense when there are some.
    const pc = S.info && S.info.profile_check, hasGaps = !!(pc && pc.exists && pc.missing.length);
    const STEPS = TOUR.filter((t) => t.sel !== "#profile-check" || hasGaps);
    const steps = []; let i = 0;
    const layer = document.createElement("div"); layer.className = "tour"; $("#overlay").appendChild(layer);
    const finish = () => { layer.remove(); document.removeEventListener("keydown", onKey, true); window.removeEventListener("resize", place); call("save_app_prefs", { tour_done: true }); go("run"); };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); finish(); } else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); } else if (e.key === "ArrowLeft") { e.preventDefault(); back(); } };
    document.addEventListener("keydown", onKey, true);
    let current = null;
    function place() {
      if (!current) return; const r = current.el.getBoundingClientRect(), pad = 6;
      const hole = $(".tour-hole", layer), card = $(".tour-card", layer);
      Object.assign(hole.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
      const cw = 320, ch = card.offsetHeight || 170;
      let left = Math.min(Math.max(12, r.left), window.innerWidth - cw - 12), top = r.bottom + 16;
      if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 16);
      Object.assign(card.style, { left: left + "px", top: top + "px", width: cw + "px" });
    }
    async function show(n) {
      const step = STEPS[n]; go(step.view); await new Promise((res) => setTimeout(res, 90));
      const el = document.querySelector(step.sel);
      if (!el) return n >= i ? next(n + 1) : back(n - 1);
      el.scrollIntoView({ block: "center" }); current = { el, step, n };
      const total = STEPS.length;
      layer.innerHTML = '<div class="tour-hole"></div><div class="tour-card" role="dialog" aria-label="Guided tour"><div class="tour-n">Step ' + (n + 1) + " of " + total + "</div><h3>" + esc(step.title) + "</h3><p>" + esc(step.text) + '</p><div class="tour-btns"><button class="btn quiet" data-t="skip">Skip tour</button><span class="grow"></span>' +
        (n > 0 ? '<button class="btn" data-t="back">Back</button>' : "") + '<button class="btn primary" data-t="next">' + (n === total - 1 ? "Done" : "Next") + "</button></div></div>";
      i = n; place();
      $('[data-t="next"]', layer).focus();
    }
    function next(n) { const to = typeof n === "number" ? n : i + 1; if (to >= STEPS.length) return finish(); show(to); }
    function back(n) { const to = typeof n === "number" ? n : i - 1; if (to < 0) return; show(to); }
    layer.addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (!b) return; ({ next, back, skip: finish })[b.dataset.t](); });
    window.addEventListener("resize", place);
    show(0);
  }
  async function init() {
    renderShell(); go("run");
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme); applyTheme();
    const s = await refreshInfo(); if (!s || !s.workspace) return;
    hydrateForm(); if (s.running) { S.run.running = true; S.run.started = true; watchRun(); }
    go("run"); if (s.browser && s.browser.installing) watchBrowser();
    call("check_update").then((r) => { if (r && r.ok) { S.update = r; renderShell(); } });
    loadApps(true);
    if (!(s.app_prefs || {}).tour_done) setTimeout(() => { if (!document.querySelector(".tour")) startTour(); }, 900);
  }
  window.__jf = { hasInfo: () => !!(S.info && S.info.workspace), go, checkUpdate: () => { go('settings'); const b = document.querySelector('[data-act="check-update"]'); if (b) b.click(); } };
  init();
})();
