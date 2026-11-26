/* Job Finder window. Plain JavaScript, no build step. Python is reached through window.pywebview.api. */
(function () {
  "use strict";

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const plural = (n, one, many) => n + " " + (n === 1 ? one : many || one + "s");

  /* ── State ───────────────────────────────────────────────────────────────── */
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
  }
  function head(title, sub, actions) {
    return '<header class="page-head"><div><h1>' + esc(title) + '</h1><div class="sub">' + esc(sub) + '</div></div><div class="actions">' + (actions || "") + "</div></header>";
  }

  /* ── Run screen ──────────────────────────────────────────────────────────── */
  function runButton() {
    return S.run.running
      ? '<button class="btn danger lg" data-act="stop">' + icon("stop") + "Stop<kbd>⌘.</kbd></button>"
      : '<button class="btn primary lg" data-act="start">' + icon("play") + (S.form.mode === "auto_apply" ? "Start applying" : "Start practice run") + "<kbd>⌘↵</kbd></button>";
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
  function renderRun() {
    const f = S.form;
    $("#view").innerHTML = head("Run", "Find jobs, tailor your resume and fill applications.", '<span id="run-btn">' + runButton() + "</span>") +
      '<div class="scroll"><div class="stack">' + checklist() + '<div class="cols">' +
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
      '<section class="card" aria-label="Activity"><div class="card-head"><h2>Activity</h2><div class="right"><button class="btn quiet" data-act="copy-log">Copy</button><button class="btn quiet" data-act="open-logs">Open log files</button></div></div>' +
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
  const FILTERS = [["all", "All"], ["applied", "Applied"], ["review", "Needs review"], ["other", "Other"]];
  const statusLabel = (s) => ({ applied: "Applied", review: "Needs review" }[statusKind(s)] || (/ready|tailored/i.test(s) ? "Ready" : (s || "—")));
  const statusKind = (s) => (/appl|submitted/i.test(s) ? "applied" : /review|fail|unsub/i.test(s) ? "review" : "other");
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
  function renderApps() {
    const c = S.info && S.info.supabase, a = S.apps;
    const sync = c && c.configured ? '<button class="btn" data-act="sync">' + icon("refresh") + (a.syncing ? "Syncing…" : "Sync now") + "</button>" : "";
    $("#view").innerHTML = head("Applications", a.rows ? plural(a.rows.length, "job") + " recorded" + (c && c.configured ? " · your Supabase project is included" : "") : "Loading…", sync) +
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
          '<td title="' + (r.synced ? "In your Supabase project" : "Only on this Mac") + '">' + icon(r.synced ? "cloud" : "cloudOff", ' class="cloud-ic' + (r.synced ? "" : " off") + '"') + "</td>" +
          "<td>" + (r.url ? '<button class="btn quiet" data-url="' + esc(r.url) + '" aria-label="Open ' + esc(r.title) + '">Open</button>' : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="foot">Showing ' + shown.length + " of " + rows.length + (rows.length > shown.length ? '&nbsp;·&nbsp;<button class="btn quiet" data-act="more">Show more</button>' : "") + "</div>";
  }

  /* ── Settings screen ─────────────────────────────────────────────────────── */
  const PROVIDERS = [["gemini", "Gemini", "Free tier available"], ["anthropic", "Claude", "Anthropic"], ["openai", "OpenAI", "GPT models"]];
  function renderSettings() {
    const i = S.info; if (!i) { $("#view").innerHTML = head("Settings", "") + '<div class="scroll"><div class="skeleton"></div></div>'; return; }
    const sb = i.supabase, br = i.browser, cl = i.cloud || {};
    const row = (t, d, ctl, id) => '<div class="setting"><div class="info"><div class="t">' + t + '</div><div class="d">' + d + '</div></div><div class="ctl"' + (id ? ' id="' + id + '"' : "") + ">" + ctl + "</div></div>";
    $("#view").innerHTML = head("Settings", "Your folder, AI providers and connections.") + '<div class="scroll"><div class="stack" style="max-width:820px">' +
      '<div class="sect-title">General</div><section class="card">' +
        row("Job Finder folder", esc(i.workspace), '<button class="btn" data-act="choose-ws">Change…</button><button class="btn" data-open="workspace">' + icon("folder") + "Show</button>") +
        row("Profile", i.prefs.profile_exists ? esc(i.prefs.candidate_name || "Profile found") : "No profile in this folder yet", i.prefs.profile_exists ? '<button class="btn" data-open="profile">Edit</button><button class="btn" data-act="build-profile">Rebuild from resume…</button>' : '<button class="btn primary" data-act="build-profile">Build from resume…</button>') +
        row("Google Chrome", i.chrome_found ? "Found. The agent drives it to fill applications." : "Not found. Install Google Chrome to let the agent fill applications.", badge(i.chrome_found ? "Installed" : "Missing", i.chrome_found ? "good" : "bad")) +
      "</section>" +
      '<div class="sect-title">AI providers</div><section class="card">' +
        PROVIDERS.map(([id, name, d]) => row(name, d, (i.keys[id].set ? badge("Saved" + (i.keys[id].hint ? " ···" + i.keys[id].hint : ""), "good") : badge("Not set")) + '<button class="btn" data-key="' + id + '">' + (i.keys[id].set ? "Replace…" : "Add key…") + "</button>", "c-" + id)).join("") +
        '<div class="setting"><div class="info"><div class="t">Keys are stored privately</div><div class="d">In the .env file inside your folder, readable only by you. They never leave this Mac except to call the provider.</div></div><div class="ctl"><button class="btn" data-open="env">Open .env</button></div></div>' +
      "</section>" +
      '<div class="sect-title">Connections</div><section class="card">' +
        row("Supabase", sb.configured ? esc(sb.host || "Configured") + (sb.reachable ? " · connected" : " · cannot be reached") : "Not set up. Add SUPABASE_URL and a key to your .env to keep applications in your own project.",
          sb.configured ? badge(sb.reachable ? "Connected" : "Unreachable", sb.reachable ? "good" : "warn") + '<button class="btn" data-act="sync">' + icon("refresh") + "Sync now</button>" : '<button class="btn" data-open="env">Open .env</button>') +
        row("job-finder.space", cl.configured ? (cl.connected ? "Applications are saved to your account" + (cl.email ? " (" + esc(cl.email) + ")" : "") + " and show on the website and in the extension." : esc(cl.error || "Cannot be reached right now.")) : "Save your applications to your job-finder.space account with your sync code. API keys never leave this Mac.",
          cl.configured ? badge(cl.connected ? "Connected" : "Unreachable", cl.connected ? "good" : "warn") + '<button class="btn" data-act="sync-cloud">' + icon("refresh") + 'Sync now</button><button class="btn" data-act="disconnect-sync">Disconnect</button>' : '<button class="btn primary" data-act="add-sync">Add sync code…</button>', "c-sync") +
        row("Page scraper browser", br.ready ? "Installed" : br.installing ? "Downloading, about 150 MB…" : (br.error ? esc(br.error) : "Needed for some job sources. Downloaded once."), br.ready ? badge("Ready", "good") : br.installing ? badge("Installing", "accent") : '<button class="btn" data-act="install-browser">' + icon("download") + "Install</button>") +
      "</section>" +
      '<div class="sect-title">About</div><section class="card">' +
        row("Job Finder " + esc(i.version), S.update && S.update.newer ? "Version " + esc(S.update.latest) + " is available." : S.update ? "You are up to date." : "Check for a newer version.", '<button class="btn" data-act="check-update">Check for updates</button>' + (S.update && S.update.newer ? '<button class="btn primary" data-url="' + esc(S.update.url) + '">Download</button>' : "")) +
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
    if (e.metaKey && e.key === "Enter") { e.preventDefault(); S.run.running ? call("stop_scan") : startRun(); }
    else if (e.metaKey && e.key === ".") { e.preventDefault(); call("stop_scan"); }
    else if (e.metaKey && ["1", "2", "3"].includes(e.key)) { e.preventDefault(); go(NAV[Number(e.key) - 1][0]); }
    else if (e.metaKey && e.key === ",") { e.preventDefault(); go("settings"); }
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
  async function init() {
    renderShell(); go("run");
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme); applyTheme();
    const s = await refreshInfo(); if (!s || !s.workspace) return;
    hydrateForm(); if (s.running) { S.run.running = true; S.run.started = true; watchRun(); }
    go("run"); if (s.browser && s.browser.installing) watchBrowser();
    call("check_update").then((r) => { if (r && r.ok) { S.update = r; renderShell(); } });
    loadApps(true);
  }
  window.__jf = { hasInfo: () => !!(S.info && S.info.workspace), go, checkUpdate: () => { go('settings'); const b = document.querySelector('[data-act="check-update"]'); if (b) b.click(); } };
  init();
})();
