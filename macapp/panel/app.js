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
    view: "search",
    info: null,           // from api.get_state()
    next: null,           // from api.next_step()
    searches: [],         // from api.list_searches()
    currentSearch: "",
    form: {
      topic: "", topics: [], level: "all", search: "", into: "",
      roles: [], location: "", timeframe: "1m", min_ats: 65, limit: 0,
      title_keywords: [], skip_portals: ["indeed", "jobserve"], primary_ai: "auto", headless: false, score_all: true, mode: "scan",
    },
    run: {
      kind: "scan",       // "scan" | "prepare" | "apply"
      running: false, offset: 0, lines: [],
      counts: { found: 0, position: 0, submitted: 0, needs_review: 0, skipped: 0 },
      exit: null, started: false, appliedRows: [],
    },
    review: { jobs: null, loading: false, filter: "all", query: "", selected: new Set(), minAts: 75, search: "" },
    packs: { list: null, loading: false, selected: new Set() },
    docs: { packs: null, selectedId: null, tab: "review", data: null, loading: false },
    apply: { jobs: null, cap: { used: 0, limit: 20 }, loading: false, mode: "preview", limit: 5, headless: false, results: [] },
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
      const fn = window.pywebview.api[name];
      if (!fn) return { ok: false, error: "Method not available: " + name };
      const result = await fn(...args);
      if (result && result.signed_out && S.info && S.info.session && S.info.session.signed_in) {
        S.info.session = { signed_in: false, reason: "expired" };
        renderShell();
      }
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
  function dialog({ title, body, confirm, danger, icon: ic, collect }) {
    return new Promise((resolve) => {
      const wrap = document.createElement("div");
      wrap.className = "scrim";
      wrap.innerHTML = '<div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-t">' +
        (ic ? '<div class="ic">' + icon(ic) + "</div>" : "") + '<h2 id="dlg-t">' + esc(title) + "</h2>" + body +
        '<div class="btns"><button class="btn" data-r="0">Cancel</button><button class="btn ' + (danger ? "danger" : "primary") + '" data-r="1">' + esc(confirm) + "</button></div></div>";
      const done = (v) => { if (v && collect) v = collect(wrap); document.removeEventListener("keydown", onKey, true); wrap.remove(); resolve(v); };
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

  function renderInlineMd(text) {
    return esc(text)
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }

  function renderMarkdown(md) {
    const lines = String(md || "").split(/\r?\n/);
    let out = "", listTag = "";
    const closeList = () => { if (listTag) { out += "</" + listTag + ">"; listTag = ""; } };
    let i = 0;
    while (i < lines.length) {
      const line = lines[i].trimEnd();
      if (/^\|/.test(line) && i + 1 < lines.length && /^\|[\s:-]+\|/.test(lines[i + 1].trim())) {
        closeList();
        const parseRow = (r) => r.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
        const headers = parseRow(line);
        i += 2;
        out += '<table style="margin:10px 0;font-size:12px"><thead><tr>' + headers.map((h) => "<th>" + renderInlineMd(h) + "</th>").join("") + "</tr></thead><tbody>";
        while (i < lines.length && /^\|/.test(lines[i].trim())) {
          const cells = parseRow(lines[i]);
          out += "<tr>" + cells.map((c) => "<td>" + renderInlineMd(c) + "</td>").join("") + "</tr>";
          i++;
        }
        out += "</tbody></table>";
        continue;
      }
      if (/^###\s+/.test(line)) { closeList(); out += "<h3>" + renderInlineMd(line.replace(/^###\s+/, "")) + "</h3>"; }
      else if (/^##\s+/.test(line)) { closeList(); out += "<h2>" + renderInlineMd(line.replace(/^##\s+/, "")) + "</h2>"; }
      else if (/^#\s+/.test(line)) { closeList(); out += "<h1>" + renderInlineMd(line.replace(/^#\s+/, "")) + "</h1>"; }
      else if (/^[-*]\s+/.test(line)) {
        if (listTag !== "ul") { closeList(); out += "<ul>"; listTag = "ul"; }
        out += "<li>" + renderInlineMd(line.replace(/^[-*]\s+/, "")) + "</li>";
      } else if (/^\d+\.\s+/.test(line)) {
        if (listTag !== "ol") { closeList(); out += "<ol>"; listTag = "ol"; }
        out += "<li>" + renderInlineMd(line.replace(/^\d+\.\s+/, "")) + "</li>";
      } else if (!line.trim()) {
        closeList();
      } else {
        closeList();
        out += "<p>" + renderInlineMd(line) + "</p>";
      }
      i++;
    }
    closeList();
    return out || '<p class="help">Empty.</p>';
  }

  /* ── Shell: sidebar, status, theme, next-step banner ─────────────────────── */
  const NAV = [
    ["search", "Search", "search"],
    ["review", "Review", "check"],
    ["packs", "Packs", "folder"],
    ["documents", "Documents", "logo"],
    ["apply", "Apply", "play"],
    ["apps", "Applications", "list"],
    ["settings", "Settings", "sliders"],
  ];

  function navCount(id) {
    const c = S.next && S.next.counts;
    if (id === "apps" && S.apps.rows) return S.apps.rows.length;
    if (!c) return 0;
    if (id === "review") return c.scanned || 0;
    if (id === "packs") return c.approved || 0;
    if (id === "documents") return c.needs_signoff || 0;
    if (id === "apply") return c.ready_to_apply || 0;
    if (id === "apps") return c.applied || 0;
    return 0;
  }

  function renderShell() {
    renderGate();
    $("#brand-logo").innerHTML = icon("logo");
    $("#nav").innerHTML = NAV.map(([id, label, ic]) => {
      const n = navCount(id);
      return '<button data-nav="' + id + '"' + (S.view === id ? ' aria-current="page"' : "") + ">" +
        icon(ic) + "<span>" + label + "</span>" +
        (n > 0 ? '<span class="count num">' + n + "</span>" : "") + "</button>";
    }).join("");
    const i = S.info, c = i && i.cloud;
    const cloud = !c ? ["", "Checking…"] : c.connected ? ["good", "Synced with job-finder.space"] : ["warn", "job-finder.space unreachable"];
    $("#conn").innerHTML = '<div class="row"><span class="dot ' + cloud[0] + '"></span>' + esc(cloud[1]) + "</div>" +
      '<div class="row"><span class="dot ' + (S.run.running ? "good pulse" : "") + '"></span>' + (S.run.running ? "Running" : "Idle") + "</div>" +
      (i ? '<div class="row" style="color:var(--text-3)">Version ' + esc(i.version) + "</div>" : "");
    const chip = $("#update-chip");
    chip.hidden = !(S.update && S.update.newer);
    if (S.update && S.update.newer) chip.textContent = "Version " + S.update.latest + " is available";
  }

  function nextBannerHtml() {
    const ns = S.next;
    if (!ns || !ns.ok) return "";
    const c = ns.counts || {};
    const bits = [];
    if (c.scanned) bits.push(c.scanned + " scanned");
    if (c.approved) bits.push(c.approved + " approved");
    if (c.needs_signoff) bits.push(c.needs_signoff + " need sign-off");
    if (c.ready_to_apply) bits.push(c.ready_to_apply + " ready");
    if (c.applied) bits.push(c.applied + " applied");
    const showBtn = ns.button && ns.goto && ns.goto !== S.view;
    return '<div class="next-banner' + (ns.stage === "done" ? " done" : "") + '" role="region" aria-label="Next step">' +
      '<span class="nb-dot"></span>' +
      '<div class="nb-body"><span class="nb-title">' + esc(ns.title) + "</span>" +
      (bits.length ? '<span class="nb-counts num">' + esc(bits.join(" · ")) + "</span>" : "") + "</div>" +
      (showBtn ? '<button class="btn primary" data-goto="' + esc(ns.goto) + '">' + esc(ns.button) + "</button>" : "") +
      "</div>";
  }

  async function refreshNextStep() {
    const r = await call("next_step");
    if (r && r.ok) {
      S.next = r;
      renderShell();
      const existing = $(".next-banner");
      if (existing) existing.outerHTML = nextBannerHtml();
    }
    return r;
  }

  function applyTheme() {
    const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    call("set_theme", dark);
  }

  function go(view) {
    S.view = view;
    renderShell();
    renderView();
    if (view === "search") loadSearches();
    if (view === "review") { loadSearches(); loadReview(); }
    if (view === "packs") loadPacks();
    if (view === "documents") loadDocuments();
    if (view === "apply") loadApply();
    if (view === "apps" && S.apps.rows === null) loadApps();
    if (view === "settings" && S.sched === undefined) loadSchedule();
    refreshNextStep();
  }

  function renderView() {
    const map = {
      search: renderSearch,
      review: renderReview,
      packs: renderPacks,
      documents: renderDocuments,
      apply: renderApply,
      apps: renderApps,
      settings: renderSettings,
    };
    (map[S.view] || renderSearch)();
  }

  function head(title, sub, actions) {
    return '<header class="page-head"><div><h1>' + esc(title) + '</h1><div class="sub">' + esc(sub) + '</div></div><div class="actions">' + (actions || "") + "</div></header>";
  }

  /* ── Search screen ───────────────────────────────────────────────────────── */
  function scanButton() {
    const busy = S.run.running && S.run.kind === "scan";
    return busy
      ? '<button class="btn danger lg" data-act="stop">' + icon("stop") + "Stop<kbd>" + MOD + ".</kbd></button>"
      : '<button class="btn primary lg" data-act="start-scan">' + icon("play") + (S.form.mode === "practice" ? "Dry-run" : "Run search") + "<kbd>" + MOD + "↵</kbd></button>";
  }
  function checklist() {
    const i = S.info; if (!i) return "";
    const hasKey = Object.values(i.keys).some((k) => k.set), hasProfile = i.prefs.profile_exists;
    if (hasKey && hasProfile) return "";
    const step = (done, t, d, action, label) => '<div class="check ' + (done ? "done" : "") + '"><span class="tick">' + icon("check") + '</span><div><div class="t">' + t + '</div><div class="d">' + d + "</div></div>" +
      (done ? "" : '<button class="btn" data-act="' + action + '">' + label + "</button>") + "</div>";
    return '<section class="card"><div class="card-head"><h2>Get ready</h2><span class="sub">Two quick steps before your first search</span></div><div class="checklist">' +
      step(hasKey, "Add an AI key", "Gemini, Claude or OpenAI. Gemini has a free tier.", "goto-settings", "Add a key") +
      step(hasProfile, "Create your profile", "Built from your resume. The agent fills forms with it.", "build-profile", "Choose resume…") + "</div></section>";
  }
  function profileCard() {
    const pc = S.info && S.info.profile_check; if (!pc || !pc.exists || !pc.missing.length) return "";
    const needed = pc.missing.filter((m) => m.needed), shown = (needed.length ? needed : pc.missing).slice(0, 6);
    return '<section class="card" id="profile-check"><div class="card-head"><h2>' + (needed.length ? "Finish your profile" : "Optional profile details") + '</h2><span class="sub">' + pc.filled + " of " + pc.total + ' filled</span></div>' +
      '<div class="checklist">' + shown.map((m) => '<div class="check"><span class="tick">' + icon("alert") + '</span><div><div class="t">' + esc(m.label) + '</div><div class="d">' + esc(m.why) + "</div></div></div>").join("") +
      (pc.missing.length > shown.length ? '<div class="d" style="padding:4px 2px">and ' + (pc.missing.length - shown.length) + " more</div>" : "") +
      '<div class="d" style="padding:6px 2px">Open the profile, fill these in, save, then come back. This page updates by itself.</div></div>' +
      '<div style="padding:0 16px 14px;display:flex;gap:8px"><button class="btn primary" data-act="edit-about">Answer the questions</button><button class="btn" data-open="profile">Edit profile</button><button class="btn" data-act="import-profile">Import profile.json…</button></div></section>';
  }

  async function loadSearches() {
    const r = await call("list_searches");
    if (r && r.ok) {
      S.searches = r.searches || [];
      S.currentSearch = r.current || "";
      if (!S.form.topics.length && !S.form.topic && S.searches.length) {
        const cur = S.searches.find((s) => s.name === S.currentSearch) || S.searches[0];
        if (cur) {
          S.form.search = cur.name;
          S.form.topic = cur.topic || "";
          S.form.topics = (cur.topic || "").split(",").map((x) => x.trim()).filter(Boolean);
          S.form.level = cur.level || "all";
          if (!S.form.location && cur.location) S.form.location = cur.location;
        }
      }
      if (S.view === "search") renderSearch();
      if (S.view === "review") renderReview();
    }
  }

  function renderSearch() {
    const f = S.form;
    const savedChips = S.searches.length
      ? '<div class="field"><span class="label">Saved searches</span><div class="saved-searches">' +
        S.searches.map((s) => '<button type="button" class="chip' + (f.search === s.name ? " active" : "") + '" data-search="' + esc(s.name) + '">' + esc(s.name) + " (" + s.jobs + ")</button>").join("") +
        '<button type="button" class="chip' + (!f.search ? " active" : "") + '" data-search="">+ New search</button></div></div>'
      : "";

    $("#view").innerHTML = head("Search", "Discover and score jobs into your search workbook." + usageNote(), '<span id="run-btn">' + scanButton() + "</span>") +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack">' + checklist() + profileCard() + '<div class="cols">' +
      '<section class="card card-pad form" aria-label="Search settings">' +
        savedChips +
        '<div class="field"><label>Topics or roles</label>' + tagsInput("topics", f.topics, "Add a topic or role and press Return") + '<div class="help">Add one or more roles/topics. Every search gets its own Excel workbook.</div></div>' +
        '<div class="field"><span class="label">Level</span><div class="seg" role="group" aria-label="Level">' +
          [["all", "All"], ["intern", "Intern"], ["graduate", "Graduate"], ["experienced", "Experienced"]].map(([v, l]) => '<button type="button" data-level="' + v + '" aria-pressed="' + (f.level === v) + '">' + l + "</button>").join("") + "</div></div>" +
        '<div class="two"><div class="field"><label for="f-location">Location</label><input class="input" id="f-location" value="' + esc(f.location) + '" placeholder="London, UK" autocomplete="off"></div>' +
        '<div class="field"><span class="label">Posted within</span><div class="seg" role="group" aria-label="Posted within">' +
          [["24h", "24h"], ["48h", "2d"], ["1w", "1w"], ["1m", "1m"]].map(([v, l]) => '<button type="button" data-time="' + v + '" aria-pressed="' + (f.timeframe === v) + '">' + l + "</button>").join("") + "</div></div></div>" +
        '<div class="field"><span class="label">Mode</span><div class="seg" role="group" aria-label="Scan mode">' +
          '<button type="button" data-scan-mode="scan" aria-pressed="' + (f.mode !== "practice") + '">Run (save to Excel)</button><button type="button" data-scan-mode="practice" aria-pressed="' + (f.mode === "practice") + '">Dry-run (funnel test)</button></div>' +
          '<div class="help" id="mode-help"></div></div>' +
        '<details class="disclosure"' + (S.advOpen ? " open" : "") + '><summary>' + icon("chevron") + 'Advanced</summary><div class="inner">' +
          '<div class="field"><label for="f-into">Add into existing search</label><input class="input" id="f-into" value="' + esc(f.into) + '" placeholder="Optional search name (e.g. ai-intern)" autocomplete="off"></div>' +
          '<div class="field"><label>Extra role titles</label>' + tagsInput("roles", f.roles, "Add a role and press Return") + '</div>' +
          '<div class="two"><div class="field"><label for="f-ats">Minimum ATS score</label><input class="input num" id="f-ats" type="number" min="0" max="100" value="' + esc(f.min_ats) + '"></div>' +
          '<div class="field"><label for="f-limit">Max jobs</label><input class="input num" id="f-limit" type="number" min="0" value="' + esc(f.limit) + '"><div class="help">0 means no limit.</div></div></div>' +
          '<div class="field"><label>Job title must contain</label>' + tagsInput("title_keywords", f.title_keywords, "e.g. intern") + "</div>" +
          '<div class="field"><label>Skip these job sites</label>' + tagsInput("skip_portals", f.skip_portals, "e.g. workday") + "</div>" +
          '<div class="two"><div class="field"><label for="f-ai">AI model</label><select class="select" id="f-ai">' +
            [["auto", "Automatic"], ["gemini", "Gemini"], ["anthropic", "Claude"], ["openai", "OpenAI"]].map(([v, l]) => '<option value="' + v + '"' + (f.primary_ai === v ? " selected" : "") + ">" + l + "</option>").join("") + "</select></div>" +
          '<div class="field"><span class="label">Browser window</span><label class="row-between" style="font-weight:400;color:var(--text)"><span>Hide while running</span><span class="switch"><input type="checkbox" id="f-headless"' + (f.headless ? " checked" : "") + '><i></i></span></label>' +
            '<label class="row-between" style="font-weight:400;color:var(--text)"><span>AI-score all levels</span><span class="switch"><input type="checkbox" id="f-score-all"' + (f.score_all ? " checked" : "") + '><i></i></span></label></div></div>' +
        "</div></details>" +
      "</section>" +
      '<section class="card act-card" aria-label="Activity"><div class="card-head"><h2>Activity</h2><span id="rate-badge"></span><div class="right"><button class="btn quiet" data-act="copy-log">Copy</button><button class="btn quiet" data-act="open-logs">Open log files</button></div></div>' +
        '<div class="card-pad"><div class="status-line" aria-live="polite"><span class="dot" id="run-dot"></span><span class="state" id="run-state"></span><span class="detail" id="run-detail"></span></div>' +
        '<div class="progress" id="run-bar"><i></i></div>' +
        '<div class="tiles"><div class="tile"><b class="num" id="t-found">0</b><span>Found</span></div><div class="tile"><b class="num" id="t-checked">0</b><span>Checked</span></div>' +
          '<div class="tile"><b class="num" id="t-skip">0</b><span>Dropped</span></div><div class="tile warn"><b class="num" id="t-rev">0</b><span>Errors</span></div></div>' +
        '<div class="live" id="live" hidden><div class="live-bar"><span class="live-title" id="live-title"></span><span class="live-url" id="live-url"></span></div><img id="live-img" alt="Browser preview"></div>' +
        '<div class="log-wrap"><div class="log" id="log" role="log" aria-label="Run log" tabindex="0"></div></div></div></section>' +
      "</div></div></div>";
    updateModeHelp(); renderRunStatus(); renderLog(true);
  }

  function updateModeHelp() {
    const el = $("#mode-help"); if (!el) return;
    el.textContent = S.form.mode === "practice"
      ? "Runs scan --dry-run: writes nothing, prints funnel counts and dropped titles."
      : "Discovers and scores jobs into your Excel workbook. Never auto-applies.";
  }

  function renderRunStatus() {
    const r = S.run, c = r.counts;
    const expectedKind = S.view === "apply" ? "apply" : S.view === "packs" ? "prepare" : "scan";
    const active = r.kind === expectedKind;
    if (!$("#run-state")) return;
    const dot = $("#run-dot"); dot.className = "dot" + (active && r.running ? " good pulse" : "");
    $("#run-state").textContent = !active ? "Ready" : r.running ? "Running" : r.started ? (r.exit === 0 || r.exit === null ? "Finished" : "Ended with an error") : "Ready";
    $("#run-detail").textContent = !active ? "Nothing is running." : r.running
      ? (c.found ? "Item " + c.position + " of " + c.found : "Working…")
      : r.started ? (r.kind === "apply" ? (S.apply.mode === "preview" ? "Preview complete (stopped before Submit)" : plural(c.submitted, "application") + " submitted") : "Complete") : "Nothing is running.";
    const bar = $("#run-bar");
    if (bar) {
      bar.classList.toggle("indeterminate", active && r.running && !c.found);
      if (active && !r.running && r.started) $("i", bar).style.width = "100%";
      else if (active && c.found) $("i", bar).style.width = Math.min(100, Math.round((c.position / c.found) * 100)) + "%";
      else $("i", bar).style.width = "0";
    }
    if ($("#t-found")) $("#t-found").textContent = active ? c.found : 0;
    if ($("#t-checked")) $("#t-checked").textContent = active ? c.position : 0;
    if ($("#t-skip")) $("#t-skip").textContent = active ? c.skipped : 0;
    if ($("#t-rev")) $("#t-rev").textContent = active ? c.needs_review : 0;
    if ($("#t-sub")) $("#t-sub").textContent = active ? c.submitted : 0;
    const rb = $("#rate-badge");
    if (rb) {
      const limited = active && r.lines.some((ln) => /quota limit reached|429/i.test(ln));
      rb.innerHTML = limited ? badge("Rate-limited — rotating keys", "warn") : "";
    }
    const btn = $("#run-btn");
    if (btn) btn.innerHTML = S.view === "apply" ? applyButton() : scanButton();
  }

  function lineClass(t) {
    if (/verified & submitted|SUBMISSION_CONFIRMED|Saved \d+ jobs|Pack ready|Preview complete/.test(t)) return "ok";
    if (/Traceback|Error|failed|Failed/.test(t)) return "bad";
    if (/^\s*\[\d+\/\d+\]\s+(Skipping|⏭)/.test(t) || /Skipping|Removed|Dropped/.test(t)) return "skip";
    if (/^\[\d+\/\d+\]|^\[Scanner\]|^\[Dry-run\]|^\[Prepare\]|^\[Apply\]/.test(t)) return "head";
    if (/^—|^Found per source:/.test(t)) return "note";
    return "";
  }
  function renderLog(full) {
    const el = $("#log"); if (!el) return;
    const expectedKind = S.view === "apply" ? "apply" : S.view === "packs" ? "prepare" : "scan";
    if (S.run.kind !== expectedKind) {
      el.innerHTML = '<div class="empty">The activity log appears here.</div>';
      return;
    }
    if (full) el.innerHTML = S.run.lines.length ? S.run.lines.map(lineHtml).join("") : '<div class="empty">The activity log appears here.</div>';
    else if (S._newLines && S._newLines.length) { if ($(".empty", el)) el.innerHTML = ""; el.insertAdjacentHTML("beforeend", S._newLines.map(lineHtml).join("")); }
    S._newLines = [];
    if (S.stick !== false) el.scrollTop = el.scrollHeight;
  }
  const lineHtml = (t) => '<div class="ln ' + lineClass(t) + '">' + esc(t) + "</div>";

  /* ── Running tasks & polling ─────────────────────────────────────────────── */
  async function startScan() {
    const f = S.form;
    if (!f.topics.length && !f.topic.trim() && !f.roles.length && !f.search) {
      toast("Add a topic/role, or pick a saved search.", "bad"); return;
    }
    const res = await call("start_scan", payload());
    if (!res || !res.ok) return;
    Object.assign(S.run, { kind: "scan", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 0, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
    S.stick = true; renderRunStatus(); renderLog(true); renderShell(); watchRun();
  }

  const payload = () => ({
    ...S.form,
    topic: S.form.topics.length ? S.form.topics.join(", ") : S.form.topic,
    roles: S.form.roles.join("\n"),
    title_keywords: S.form.title_keywords.join(","),
    skip_portals: S.form.skip_portals.join(","),
  });

  function watchRun() { if (!S.pollTimer) S.pollTimer = setInterval(pollRun, 750); pollRun(); }

  async function refreshLive(ended) {
    const el = $("#live"); if (!el) return;
    if (ended) { el.hidden = true; return; }
    const now = Date.now(); if (S._liveBusy || now - (S._liveAt || 0) < 2500) return;
    S._liveBusy = true; S._liveAt = now;
    try {
      const v = await call("live_view");
      if (v && v.ok && $("#live")) { $("#live-img").src = v.image; $("#live-title").textContent = v.title || "Browser"; $("#live-url").textContent = v.url; $("#live").hidden = false; }
    } finally { S._liveBusy = false; }
  }

  async function pollRun() {
    const r = await call("poll", S.run.offset);
    if (!r || r.lines === undefined) return;
    S.run.offset = r.next; S._newLines = r.lines; S.run.lines.push(...r.lines); S.run.counts = r.counts || S.run.counts;
    const was = S.run.running; S.run.running = r.running; S.run.exit = r.exit_code;
    if (Array.isArray(r.applied_rows) && r.applied_rows.length) {
      S.apply.results = r.applied_rows;
    }
    if (S.view === "search" || S.view === "packs" || S.view === "apply") { renderLog(false); renderRunStatus(); }
    if (r.running || was) refreshLive(!r.running);
    if (was && !r.running) {
      clearInterval(S.pollTimer); S.pollTimer = null; renderShell();
      const c = S.run.counts;
      if (S.run.kind === "prepare") {
        toast("Packs prepared.");
        await loadPacks();
      } else if (S.run.kind === "apply") {
        toast(r.exit_code === 0 || r.exit_code === null ? "Apply finished: " + plural(c.submitted, "application") + " submitted." : "Apply ended with an error.", r.exit_code ? "bad" : "");
        await loadApply();
        S.apps.rows = null;
      } else {
        toast(r.exit_code === 0 || r.exit_code === null ? "Search finished." : "Search ended with an error.", r.exit_code ? "bad" : "");
        loadSearches();
        S.review.jobs = null;
      }
      await refreshNextStep();
    }
  }

  /* ── Review screen ───────────────────────────────────────────────────────── */
  async function loadReview() {
    S.review.loading = true;
    if (S.view === "review") renderReview();
    const r = await call("list_jobs", S.review.search || null);
    S.review.jobs = r && r.ok && Array.isArray(r.jobs) ? r.jobs : [];
    S.review.loading = false;
    if (S.view === "review") renderReview();
  }

  function filteredReviewJobs() {
    const rv = S.review;
    let jobs = rv.jobs || [];
    if (rv.filter === "pending") jobs = jobs.filter((j) => !j.approved);
    else if (rv.filter === "approved") jobs = jobs.filter((j) => j.approved);
    const q = rv.query.trim().toLowerCase();
    if (q) jobs = jobs.filter((j) => (j.company + " " + j.role + " " + j.level).toLowerCase().includes(q));
    return jobs;
  }

  function renderReview() {
    const rv = S.review;
    const total = rv.jobs ? rv.jobs.length : 0;
    const approvedCount = rv.jobs ? rv.jobs.filter((j) => j.approved).length : 0;
    const searchSel = S.searches.length
      ? '<select class="select" id="rev-search" aria-label="Select search" style="width:auto;min-width:150px">' +
        '<option value="">Current search</option>' +
        S.searches.map((s) => '<option value="' + esc(s.name) + '"' + (rv.search === s.name ? " selected" : "") + ">" + esc(s.name) + " (" + s.jobs + ")</option>").join("") +
        "</select>"
      : "";
    const actions = searchSel +
      '<div style="display:flex;align-items:center;gap:6px"><input class="input num inline-num" id="rev-min-ats" type="number" min="0" max="100" value="' + esc(rv.minAts) + '" aria-label="Minimum ATS percent">' +
      '<button class="btn primary" data-act="approve-min">Approve ≥ ' + esc(rv.minAts) + "%</button></div>";

    $("#view").innerHTML = head("Review", rv.jobs ? plural(total, "job") + " · " + approvedCount + " approved" : "Loading…", actions) +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack"><section class="card">' +
      '<div class="toolbar">' +
        '<div class="search">' + icon("search") + '<input class="input" id="rev-q" type="search" placeholder="Filter company or role" value="' + esc(rv.query) + '" aria-label="Filter jobs"></div>' +
        '<div class="seg" role="group" aria-label="Filter">' +
          [["all", "All"], ["pending", "Pending"], ["approved", "Approved"]].map(([v, l]) => '<button type="button" data-rev-filter="' + v + '" aria-pressed="' + (rv.filter === v) + '">' + l + "</button>").join("") +
        "</div>" +
        '<div style="margin-left:auto;display:flex;gap:8px">' +
          '<button class="btn" data-act="approve-selected"' + (rv.selected.size ? "" : " disabled") + ">Approve selected</button>" +
          '<button class="btn" data-act="revoke-selected"' + (rv.selected.size ? "" : " disabled") + ">Revoke selected</button>" +
        "</div>" +
      "</div>" +
      '<div id="rev-body"></div></section></div></div>';
    renderReviewBody();
  }

  function renderReviewBody() {
    const body = $("#rev-body"); if (!body) return;
    const rv = S.review;
    if (rv.loading || rv.jobs === null) {
      body.innerHTML = '<div class="card-pad">' + [1, 2, 3, 4].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</div>";
      return;
    }
    if (!rv.jobs.length) {
      body.innerHTML = '<div class="empty-state">' + icon("search") + '<h3>Nothing scanned yet</h3><p>Run a search first to discover and score jobs.</p><button class="btn primary" data-goto="search" style="margin-top:8px">Go to Search</button></div>';
      return;
    }
    const jobs = filteredReviewJobs();
    if (!jobs.length) {
      body.innerHTML = '<div class="empty-state">' + icon("search") + "<h3>No matches</h3><p>Try a different search or filter.</p></div>";
      return;
    }
    const allChecked = jobs.length > 0 && jobs.every((j) => rv.selected.has(j.id));
    body.innerHTML = '<div class="table-wrap"><table><thead><tr>' +
      '<th class="chk-col"><input type="checkbox" id="rev-all"' + (allChecked ? " checked" : "") + ' aria-label="Select all"></th>' +
      '<th>Job</th><th>Match</th><th>Fit</th><th>Closing</th><th>Status</th><th aria-label="Actions"></th></tr></thead><tbody>' +
      jobs.map((j) => {
        const fit = Number(j.fit) || 0;
        const matchKind = /core/i.test(j.match) ? "accent" : "";
        return "<tr>" +
          '<td class="chk-col"><input type="checkbox" data-rev-chk="' + esc(j.id) + '"' + (rv.selected.has(j.id) ? " checked" : "") + ' aria-label="Select ' + esc(j.role) + '"></td>' +
          '<td class="job"><div class="co">' + esc(j.company) + '</div><div class="ro">' + esc(j.role) + '<span class="src"> · ' + esc(j.level) + (j.years && j.years !== "not stated" ? " · " + esc(j.years) + " yrs" : "") + "</span></div></td>" +
          "<td>" + (j.match ? badge(j.match, matchKind) : "—") + "</td>" +
          '<td><span class="score num"><span class="bar"><i style="width:' + Math.min(100, fit) + '%"></i></span>' + fit + "%" + (j.scored_by ? '<span class="src' + (j.scored_by === "AI" ? " ai" : "") + '">' + esc(j.scored_by) + "</span>" : "") + "</span></td>" +
          '<td class="num">' + (j.closing ? esc(j.closing) : "—") + "</td>" +
          "<td>" + badge(j.approved ? "Approved" : "Pending", j.approved ? "good" : "") + "</td>" +
          '<td class="acts">' +
            (j.url ? '<button class="btn quiet" data-url="' + esc(j.url) + '">Open</button>' : "") +
            (j.approved
              ? '<button class="btn quiet" data-revoke-one="' + esc(j.id) + '">Revoke</button>'
              : '<button class="btn quiet" data-approve-one="' + esc(j.id) + '">Approve</button>') +
          "</td></tr>";
      }).join("") +
      '</tbody></table></div><div class="foot">Showing ' + jobs.length + " of " + rv.jobs.length + "</div>";
  }

  /* ── Packs screen ────────────────────────────────────────────────────────── */
  async function loadPacks() {
    S.packs.loading = true;
    if (S.view === "packs") renderPacks();
    const r = await call("list_packs");
    S.packs.list = r && r.ok && Array.isArray(r.packs) ? r.packs : [];
    S.packs.loading = false;
    if (S.view === "packs") renderPacks();
  }

  function packBadge(state) {
    const map = {
      not_started: ["Not started", ""],
      preparing: ["Preparing…", "accent"],
      ready: ["Ready", "good"],
      needs_signoff: ["Needs sign-off", "warn"],
      signed_off: ["Signed off", "good"],
    };
    const [label, kind] = map[state] || [state || "—", ""];
    return badge(label, kind);
  }

  function renderPacks() {
    const pk = S.packs;
    const list = pk.list || [];
    const prepBusy = S.run.running && S.run.kind === "prepare";
    const prepBtn = '<button class="btn primary" data-act="prepare-packs"' + (!list.length || prepBusy ? " disabled" : "") + ">" +
      icon("play") + (pk.selected.size ? "Prepare selected (" + pk.selected.size + ")" : "Prepare packs") + "</button>";

    const progressCard = (prepBusy || (S.run.started && S.run.kind === "prepare"))
      ? '<section class="card card-pad"><div class="status-line"><span class="dot" id="run-dot"></span><span class="state" id="run-state"></span><span class="detail" id="run-detail"></span></div>' +
        '<div class="progress" id="run-bar"><i></i></div>' +
        '<div class="log-wrap"><div class="log" id="log" style="height:140px" role="log" aria-label="Pack log" tabindex="0"></div></div></section>'
      : "";

    $("#view").innerHTML = head("Packs", pk.list ? plural(list.length, "approved job") : "Loading…", prepBtn) +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack">' + progressCard + '<section class="card"><div id="pk-body"></div></section></div></div>';
    renderPacksBody();
    if (progressCard) { renderRunStatus(); renderLog(true); }
  }

  function renderPacksBody() {
    const body = $("#pk-body"); if (!body) return;
    const pk = S.packs;
    if (pk.loading || pk.list === null) {
      body.innerHTML = '<div class="card-pad">' + [1, 2, 3].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</div>";
      return;
    }
    if (!pk.list.length) {
      body.innerHTML = '<div class="empty-state">' + icon("folder") + '<h3>Nothing approved yet</h3><p>Approve jobs on the Review tab first, then prepare their tailored CV and review checklist here.</p><button class="btn primary" data-goto="review" style="margin-top:8px">Review jobs</button></div>';
      return;
    }
    const allChecked = pk.list.every((p) => pk.selected.has(p.id));
    body.innerHTML = '<div class="table-wrap"><table><thead><tr>' +
      '<th class="chk-col"><input type="checkbox" id="pk-all"' + (allChecked ? " checked" : "") + ' aria-label="Select all packs"></th>' +
      '<th>Job</th><th>State</th><th>Error</th><th aria-label="Actions"></th></tr></thead><tbody>' +
      pk.list.map((p) => "<tr>" +
        '<td class="chk-col"><input type="checkbox" data-pk-chk="' + esc(p.id) + '"' + (pk.selected.has(p.id) ? " checked" : "") + ' aria-label="Select ' + esc(p.role) + '"></td>' +
        '<td class="job"><div class="co">' + esc(p.company) + '</div><div class="ro">' + esc(p.role) + '<span class="src"> · #' + esc(p.id) + "</span></div></td>" +
        "<td>" + packBadge(p.state) + (p.cv_edited ? ' <span class="badge warn" title="Uses your hand-edited LaTeX PDF">Hand-edited CV</span>' : "") + "</td>" +
        '<td style="color:var(--bad);font-size:12px">' + (p.error ? esc(p.error) : "—") + "</td>" +
        '<td class="acts">' +
          (p.state === "not_started" || p.error ? '<button class="btn quiet" data-prep-one="' + esc(p.id) + '">Prepare</button>' : "") +
          (p.state !== "not_started" && p.state !== "preparing" ? '<button class="btn quiet" data-view-doc="' + esc(p.id) + '">View documents</button>' : "") +
        "</td></tr>").join("") +
      "</tbody></table></div>";
  }

  /* ── Documents screen ────────────────────────────────────────────────────── */
  async function loadDocuments(selectId) {
    const r = await call("list_packs");
    const all = r && r.ok && Array.isArray(r.packs) ? r.packs : [];
    const ready = all.filter((p) => p.state !== "not_started" && p.state !== "preparing");
    S.docs.packs = ready;
    if (selectId) S.docs.selectedId = selectId;
    else if (!S.docs.selectedId || !ready.some((p) => p.id === S.docs.selectedId)) {
      const need = ready.find((p) => p.state === "needs_signoff" || p.state === "ready");
      S.docs.selectedId = (need || ready[0] || {}).id || null;
    }
    if (S.docs.selectedId) {
      await loadPackDocs(S.docs.selectedId);
    } else {
      S.docs.data = null;
      if (S.view === "documents") renderDocuments();
    }
  }

  async function loadPackDocs(id) {
    S.docs.loading = true;
    if (S.view === "documents") renderDocuments();
    const r = await call("pack_documents", id);
    S.docs.data = r && r.ok ? r : null;
    const gp = await call("check_resume_gaps");
    S.docs.gaps = gp && gp.ok && gp.has_resume ? { numbers: gp.numbers || [], names: gp.names || [] } : null;
    const cf = await call("list_confirmed_experience");
    S.docs.confirmed = cf && cf.ok ? cf.items || [] : [];
    S.docs.loading = false;
    if (S.view === "documents") renderDocuments();
  }

  function renderDocuments() {
    const d = S.docs;
    const packs = d.packs;
    let bodyHtml = "";
    if (!packs) {
      bodyHtml = '<section class="card card-pad">' + [1, 2, 3].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</section>";
    } else if (!packs.length) {
      bodyHtml = '<section class="card"><div class="empty-state">' + icon("logo") + '<h3>No prepared packs yet</h3><p>Prepare packs for your approved jobs first, then review the tailored CV and cover letter here.</p><button class="btn primary" data-goto="packs" style="margin-top:8px">Go to Packs</button></div></section>';
    } else {
      const sel = packs.find((p) => p.id === d.selectedId) || packs[0];
      const doc = d.data;
      const isSigned = sel && sel.state === "signed_off";
      const signoffBlocked = doc && doc.signoff_allowed === false;
      const tabs = [["review", "REVIEW.md"], ["evidence", "Evidence & Risk"], ["diff", "Diff & Revert"], ["cover", "Cover Letter"], ["fit", "Fit Analysis"], ["cv", "Tailored CV"]];
      let content = "";
      if (d.loading) {
        content = '<div class="skeleton" style="margin:12px 0"></div><div class="skeleton" style="margin:12px 0;width:70%"></div>';
      } else if (!doc) {
        content = '<p class="help">Could not load pack documents.</p>';
      } else if (d.tab === "review") {
        content = '<div class="doc-md">' + renderMarkdown(doc.review_md) + "</div>";
      } else if (d.tab === "evidence") {
        const ev = doc.evidence_panel || {};
        const sc = doc.scores || {};
        const scoreHtml = '<div class="score-strip">' +
          '<span class="score-pill">Master score: <strong>' + esc(sc.master_score ?? "—") + "</strong></span>" +
          '<span class="score-pill">Tailored score: <strong>' + esc(sc.tailored_score ?? "—") + "</strong></span>" +
          '<span class="score-pill">Keywords: <strong>' + esc(sc.coverage_before ?? "—") + " → " + esc(sc.coverage_after ?? "—") + "</strong></span>" +
          (sc.regression_blocked ? '<span class="score-pill">Regression blocked: <strong>' + esc(sc.regression_blocked) + "</strong></span>" : "") +
          "</div>";
        const flagsHtml = (doc.unresolved_flags && doc.unresolved_flags.length)
          ? '<div class="flag-banner"><strong>Sign-off blocked:</strong> ' + esc(doc.unresolved_flags.join(", ")) + "</div>"
          : "";
        const evCards = [
          ["Keywords Found", ev.keywords_found],
          ["Confirmed by you", ev.keywords_confirmed],
          ["No Evidence (Never Added)", ev.keywords_missing],
          ["Requirements Gap", ev.requirements_gap],
          ["Knockouts", ev.knockouts],
          ["Alias Matches", ev.alias_matches],
          ["Entailment Results", ev.entailment_results],
        ].map(([lbl, items]) => lbl === "No Evidence (Never Added)"
          ? '<div class="ev-card"><h4>' + lbl + '</h4><p class="help">These are not on your CV. If you really have one, say where you used it and it can be listed.</p>' +
            (Array.isArray(items) && items.length ? "<ul>" + items.map((x) => '<li>' + esc(x) + ' <button class="btn quiet" data-act="confirm-skill" data-skill="' + esc(x) + '" data-id="' + esc(sel.id) + '">I have this</button></li>').join("") + "</ul>" : '<span class="help">None</span>') + "</div>"
          : '<div class="ev-card"><h4>' + lbl + "</h4>" +
          (Array.isArray(items) && items.length ? "<ul>" + items.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ul>" : '<span class="help">None</span>') +
          "</div>").join("");
        const mine = (S.docs.confirmed || []).length
          ? '<div class="ev-card"><h4>Skills you confirmed (all CVs)</h4><ul>' + S.docs.confirmed.map((c) => "<li><strong>" + esc(c.skill) + "</strong> <span class=\"help\">" + esc(c.evidence) + "</span> " +
              '<button class="btn quiet" data-act="unconfirm-skill" data-skill="' + esc(c.skill) + '" data-id="' + esc(sel.id) + '">Remove</button></li>').join("") + "</ul></div>" : "";
        const g = S.docs.gaps;
        const gapHtml = g && (g.numbers.length || g.names.length)
          ? '<div class="flag-banner"><strong>Your resume file has facts that are missing from your CV data:</strong> ' + esc(g.numbers.concat(g.names).slice(0, 12).join(", ")) +
            '. Add them to your profile (Settings, Build profile from resume) or they will not appear on any CV.</div>' : "";
        content = gapHtml + scoreHtml + flagsHtml + '<div class="evidence-grid">' + evCards + mine + "</div>";
      } else if (d.tab === "diff") {
        const chgs = doc.changes || [];
        content = chgs.length
          ? '<div class="diff-list">' + chgs.map((c) => '<div class="diff-card">' +
              '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">' +
              '<strong>' + esc(c.section || "change") + " — " + esc(c.reason || "") + "</strong>" +
              (c.reverted
                ? '<span class="badge">Reverted</span>'
                : '<button class="btn" data-act="revert-change" data-id="' + esc(sel.id) + '" data-chg="' + esc(c.id) + '">Revert</button>') +
              '</div><div class="diff-grid"><div class="diff-col"><div class="help">Master</div>' + esc(c.original || "") + '</div>' +
              '<div class="diff-col"><div class="help">Tailored</div>' + esc(c.new_text || "") + "</div></div></div>").join("") + "</div>"
          : '<p class="help">' + esc(doc.tailoring_message || "No rewrites recorded for this pack.") + "</p>";
      } else if (d.tab === "cover") {
        content = doc.cover_letter
          ? '<div class="doc-pre">' + esc(doc.cover_letter) + "</div>"
          : '<p class="help">' + esc(doc.cover_letter_message || "Cover letter has not been generated yet.") + "</p>";
      } else if (d.tab === "fit") {
        content = '<div class="doc-md">' + renderMarkdown(doc.fit || "No fit analysis recorded.") + "</div>";
      } else if (d.tab === "cv") {
        const cj = doc.cv_json;
        const editorHtml = cj ? '<details class="disclosure" style="margin-bottom:12px"><summary>' + icon("chevron") + 'Edit summary &amp; bullets (cv.json)</summary><div class="inner">' +
          '<div class="field"><label for="cv-sum">Professional Summary</label><textarea class="input" id="cv-sum" rows="3">' + esc(cj.summary || "") + '</textarea></div>' +
          (cj.experience || []).map((ex, idx) => '<div class="field"><label>' + esc((ex.role || "") + " @ " + (ex.company || "")) + ' (one bullet per line)</label><textarea class="input" data-cv-exp="' + idx + '" rows="3">' + esc((ex.description || []).join("\n")) + '</textarea></div>').join("") +
          '<div><button class="btn primary" data-act="save-cv-json" data-id="' + esc(sel.id) + '">Save &amp; Re-render PDF</button></div></div></details>' : "";
        const lt = S.docs.latex && S.docs.latex.id === sel.id ? S.docs.latex : null;
        const latexHtml = '<details class="disclosure" style="margin-bottom:12px"' + (lt ? " open" : "") + '><summary>' + icon("chevron") + 'LaTeX source (advanced): edit, compile, preview</summary><div class="inner">' +
          (!lt ? '<p class="help">Opens the CV as LaTeX in your resume style. You can change any line, compile it and use that PDF for applications.</p><div><button class="btn" data-act="latex-open" data-id="' + esc(sel.id) + '">Open LaTeX</button></div>'
            : (lt.error ? '<div class="banner bad" role="alert">' + esc(lt.error) + "</div>" : "") +
              (lt.available === false ? '<p class="help">LaTeX is not installed on this computer, so it cannot be compiled. The standard CV keeps working.</p>' : "") +
              '<textarea class="input" id="cv-tex" spellcheck="false" rows="16" style="font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;white-space:pre">' + esc(lt.tex || "") + "</textarea>" +
              '<div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">' +
                '<button class="btn primary" data-act="latex-compile" data-id="' + esc(sel.id) + '"' + (lt.busy ? " disabled" : "") + ">" + (lt.busy ? "Compiling…" : "Compile preview") + "</button>" +
                '<button class="btn" data-act="latex-use" data-id="' + esc(sel.id) + '"' + (lt.pages && lt.pages.length ? "" : " disabled") + ">Use this PDF for applications</button>" +
                (lt.in_use ? '<button class="btn" data-act="latex-use-standard" data-id="' + esc(sel.id) + '">Use the standard CV again</button>' : "") +
                '<button class="btn quiet" data-act="latex-reset" data-id="' + esc(sel.id) + '">Reset to generated</button>' +
                (lt.in_use ? '<span class="badge">Used for applications</span>' : "") + "</div>" +
              (lt.warnings && lt.warnings.length ? '<div class="banner warn" role="status"><strong>Check these before you apply:</strong><ul>' + lt.warnings.map((w) => "<li>" + esc(w) + "</li>").join("") + "</ul></div>" : "") +
              (lt.meta ? '<p class="help">' + esc(lt.meta) + "</p>" : "") +
              (lt.pages && lt.pages.length ? '<div class="latex-preview">' + lt.pages.map((src, i) => '<img alt="CV page ' + (i + 1) + '" src="' + src + '">').join("") + "</div>" : "")) +
          "</div></details>";
        content = '<div class="doc-path" style="display:flex;align-items:center;justify-content:space-between;gap:10px"><span>' + esc(doc.cv_pdf || "No cv.pdf path") + '</span>' +
          '<button class="btn primary" data-open-pack="' + esc(sel.id) + ':cv" style="flex:none">' + icon("external") + "Open CV PDF</button></div>" +
          editorHtml + latexHtml +
          (doc.cv_html ? '<iframe title="Tailored CV preview" sandbox="" srcdoc="' + esc(doc.cv_html) + '" style="width:100%;height:520px;border:.5px solid var(--line);border-radius:8px;background:#fff"></iframe>' : "");
      }

      bodyHtml = '<div class="docs-layout">' +
        '<section class="card"><div class="doc-list" role="listbox" aria-label="Prepared packs">' +
          packs.map((p) => '<button class="doc-item" role="option" data-doc-sel="' + esc(p.id) + '" aria-selected="' + (sel && sel.id === p.id) + '">' +
            '<div class="di-role">' + esc(p.role) + '</div><div class="di-co"><span>' + esc(p.company) + "</span>" + packBadge(p.state) + "</div></button>").join("") +
        "</div></section>" +
        '<section class="card doc-viewer">' +
          '<div class="doc-head"><div class="dh-info"><div class="dh-title">' + esc(sel.role) + " @ " + esc(sel.company) + '</div><div class="dh-sub">Pack #' + esc(sel.id) + " · " + (isSigned ? "Signed off for Apply" : "Waiting for your sign-off") + "</div></div>" +
          '<div class="dh-acts">' +
            '<button class="btn" data-open-pack="' + esc(sel.id) + ':cv">' + icon("external") + "CV</button>" +
            (doc && doc.cover_letter ? '<button class="btn" data-open-pack="' + esc(sel.id) + ':cover">' + icon("external") + "Cover</button>" : "") +
            '<button class="btn" data-open-pack="' + esc(sel.id) + ':jd">' + icon("external") + "JD</button>" +
            '<button class="btn" data-open-pack="' + esc(sel.id) + ':review">' + icon("external") + "REVIEW</button>" +
            '<button class="btn" data-act="redo-pack" data-id="' + esc(sel.id) + '" title="Rebuild from the AI\'s saved answer (same result, picks up profile changes)">Regenerate</button>' +
            '<button class="btn" data-act="new-draft" data-id="' + esc(sel.id) + '" title="Ask the AI again for a different draft">New draft</button>' +
            '<button class="btn" data-act="revoke-pack" data-id="' + esc(sel.id) + '">Revoke</button>' +
            '<button class="btn ' + (isSigned ? "" : "primary") + '" data-act="signoff-pack" data-id="' + esc(sel.id) + '"' + (isSigned || signoffBlocked ? " disabled" : "") + ' title="' + esc((doc && doc.signoff_blocked_reason) || "") + '">' + icon("check") + (isSigned ? "Signed off" : "Docs OK") + "</button>" +
          "</div></div>" +
          '<div class="doc-tabs" role="tablist">' +
            tabs.map(([k, lbl]) => '<button role="tab" data-doc-tab="' + k + '" aria-selected="' + (d.tab === k) + '">' + lbl + "</button>").join("") +
          "</div>" +
          '<div class="doc-content">' + content + "</div>" +
        "</section></div>";
    }

    $("#view").innerHTML = head("Documents", "Inspect tailored CVs, cover letters, and checklists before signing off.") +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack">' + bodyHtml + "</div></div>";
  }

  /* ── Apply screen ────────────────────────────────────────────────────────── */
  function applyButton() {
    const busy = S.run.running && S.run.kind === "apply";
    if (busy) return '<button class="btn danger lg" data-act="stop">' + icon("stop") + "Stop<kbd>" + MOD + ".</kbd></button>";
    const dis = !(S.apply.jobs && S.apply.jobs.length) ? " disabled" : "";
    return S.apply.mode === "submit"
      ? '<button class="btn danger lg" data-act="start-apply"' + dis + ">" + icon("play") + "Submit applications</button>"
      : '<button class="btn primary lg" data-act="start-apply"' + dis + ">" + icon("play") + "Preview apply</button>";
  }

  async function loadApply() {
    S.apply.loading = true;
    if (S.view === "apply") renderApply();
    const r = await call("list_ready");
    if (r && r.ok) {
      S.apply.jobs = r.jobs || [];
      S.apply.cap = r.cap || { used: 0, limit: 20 };
    } else {
      S.apply.jobs = [];
    }
    S.apply.loading = false;
    if (S.view === "apply") renderApply();
  }

  function groundingAuditHtml(rows) {
    if (!rows || !rows.length) return "";
    return '<section class="card card-pad"><div class="card-head" style="padding:0 0 12px;margin-bottom:12px"><h2>Grounding audit &amp; form questions</h2></div><div class="audit-list">' +
      rows.map((r) => {
        const g = r.grounding || {};
        const qs = r.questions || [];
        return '<div class="audit-card">' +
          '<div class="audit-head"><b>' + esc(r.role) + " @ " + esc(r.company) + "</b>" +
          badge(g.verified ? "Verified" : "Needs check", g.verified ? "good" : "warn") +
          '<span class="num" style="font-size:12px;color:var(--text-2)">' + (g.answered_from_profile || 0) + " answered from profile</span></div>" +
          '<div class="audit-meta">' +
            (g.no_data && g.no_data.length ? "<span>No data: " + esc(g.no_data.join(", ")) + "</span>" : "") +
            (g.stopped && g.stopped.length ? "<span>Stopped: " + esc(g.stopped.join(", ")) + "</span>" : "") +
            (g.ungrounded && g.ungrounded.length ? '<span style="color:var(--bad)">Ungrounded: ' + esc(g.ungrounded.join(", ")) + "</span>" : "") +
          "</div>" +
          (qs.length ? '<ul class="audit-qs">' + qs.map((q) => "<li><b>" + esc(q.question) + ":</b> " + esc(q.answer) + "</li>").join("") + "</ul>" : "") +
          "</div>";
      }).join("") + "</div></section>";
  }

  function renderApply() {
    const ap = S.apply;
    const jobs = ap.jobs;
    const cap = ap.cap || { used: 0, limit: 20 };
    const pct = cap.limit ? Math.min(100, Math.round((cap.used / cap.limit) * 100)) : 0;

    let queueHtml = "";
    if (ap.loading || jobs === null) {
      queueHtml = '<div class="card-pad">' + [1, 2, 3].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</div>";
    } else if (!jobs.length) {
      queueHtml = '<div class="empty-state">' + icon("play") + '<h3>Nothing signed off yet</h3><p>Only packs marked Docs OK appear here. Review and sign off a pack first.</p><button class="btn primary" data-goto="documents" style="margin-top:8px">Review documents</button></div>';
    } else {
      queueHtml = '<div class="table-wrap"><table><thead><tr><th>Job</th><th>Fit</th><th>Closing</th><th aria-label="Open"></th></tr></thead><tbody>' +
        jobs.map((j) => '<tr><td class="job"><div class="co">' + esc(j.company) + '</div><div class="ro">' + esc(j.role) + "</div></td>" +
          '<td><span class="score num"><span class="bar"><i style="width:' + Math.min(100, Number(j.fit) || 0) + '%"></i></span>' + (Number(j.fit) || 0) + "%</span></td>" +
          '<td class="num">' + (j.closing ? esc(j.closing) : "—") + "</td>" +
          '<td class="acts">' + (j.url ? '<button class="btn quiet" data-url="' + esc(j.url) + '">Open</button>' : "") + "</td></tr>").join("") +
        "</tbody></table></div>";
    }

    $("#view").innerHTML = head("Apply", (jobs ? plural(jobs.length, "signed-off job") : "Loading…") + " · Daily cap " + cap.used + "/" + cap.limit, '<span id="run-btn">' + applyButton() + "</span>") +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack">' +
      '<section class="card card-pad form">' +
        '<div class="cap-bar"><span class="label">Daily cap</span><div class="progress"><i style="width:' + pct + '%"></i></div>' +
          '<span class="num" style="font-size:12px;color:var(--text-2);display:inline-flex;align-items:center;gap:6px">' + cap.used + " / " +
          '<input class="input num inline-num" id="ap-cap" type="number" min="1" max="200" value="' + esc(cap.limit) + '" aria-label="Daily cap limit" style="height:24px"> used today</span></div>' +
        '<div class="cols" style="align-items:center">' +
          '<div class="field"><span class="label">Mode</span><div class="seg real" role="group" aria-label="Apply mode">' +
            '<button type="button" data-apply-mode="preview" aria-pressed="' + (ap.mode === "preview") + '">Preview (stop before Submit)</button>' +
            '<button type="button" class="is-real" data-apply-mode="submit" aria-pressed="' + (ap.mode === "submit") + '">Submit (for real)</button>' +
          "</div></div>" +
          '<div class="two"><div class="field"><label for="ap-limit">Max this run</label><input class="input num" id="ap-limit" type="number" min="1" max="50" value="' + esc(ap.limit) + '"></div>' +
          '<div class="field"><span class="label">Browser</span><label class="row-between" style="font-weight:400;color:var(--text)"><span>Hide while running</span><span class="switch"><input type="checkbox" id="ap-headless"' + (ap.headless ? " checked" : "") + '><i></i></span></label></div></div>' +
        "</div>" +
      "</section>" +
      '<div class="cols">' +
        '<section class="card" aria-label="Signed-off queue"><div class="card-head"><h2>Ready to apply</h2><span class="sub">Signed-off jobs only</span></div>' + queueHtml + "</section>" +
        '<section class="card act-card" aria-label="Apply activity"><div class="card-head"><h2>Activity</h2><div class="right"><button class="btn quiet" data-act="copy-log">Copy</button></div></div>' +
          '<div class="card-pad"><div class="status-line"><span class="dot" id="run-dot"></span><span class="state" id="run-state"></span><span class="detail" id="run-detail"></span></div>' +
          '<div class="progress" id="run-bar"><i></i></div>' +
          '<div class="live" id="live" hidden><div class="live-bar"><span class="live-title" id="live-title"></span><span class="live-url" id="live-url"></span></div><img id="live-img" alt="Browser preview"></div>' +
          '<div class="log-wrap"><div class="log" id="log" role="log" aria-label="Apply log" tabindex="0"></div></div></div></section>' +
      "</div>" +
      groundingAuditHtml(ap.results) +
      "</div></div>";
    renderRunStatus(); renderLog(true);
  }

  async function startApply() {
    const ap = S.apply;
    if (!ap.jobs || !ap.jobs.length) { toast("No signed-off jobs ready.", "bad"); return; }
    if (ap.mode === "submit") {
      const ab = S.info && S.info.about_you;
      if (ab && ab.exists && ab.unanswered.some((k) => k === "work_authorization" || k === "requires_sponsorship" || k === "notice_period")) {
        toast("Before applying for real, answer the questions about work rights and your start date.", "bad");
        await openAboutYou(); await refreshInfo();
        const again = S.info && S.info.about_you;
        if (!again || again.unanswered.some((k) => k === "work_authorization" || k === "requires_sponsorship" || k === "notice_period")) return;
      }
      const count = Math.min(ap.jobs.length, Number(ap.limit) || ap.jobs.length);
      const ok = await dialog({
        title: "Submit " + plural(count, "application") + "?", icon: "alert", danger: true, confirm: "Submit now",
        body: "<p>The agent will fill in and submit applications using your signed-off CV and cover letter. This cannot be undone.</p><ul>" +
          "<li>Queued: <span>" + plural(count, "signed-off job") + "</span></li>" +
          "<li>Daily cap: <span>" + ap.cap.used + " of " + ap.cap.limit + " used today</span></li></ul>",
      });
      if (!ok) return;
    }
    const res = await call("start_apply", { mode: ap.mode, limit: Number(ap.limit) || 5, headless: !!ap.headless });
    if (!res || !res.ok) return;
    Object.assign(S.run, { kind: "apply", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: ap.jobs.length, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
    S.stick = true; renderRunStatus(); renderLog(true); renderShell(); watchRun();
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
    const a = S.apps;
    const sync = '<button class="btn" data-act="sync">' + icon("refresh") + (a.syncing ? "Syncing…" : "Sync now") + "</button>";
    $("#view").innerHTML = head("Applications", a.rows ? plural(a.rows.length, "job") + " recorded" + stageSummary() + " · saved to your account" : "Loading…", sync) +
      nextBannerHtml() +
      '<div class="scroll"><div class="stack"><section class="card"><div class="toolbar"><div class="search">' + icon("search") + '<input class="input" id="a-q" type="search" placeholder="Search company or role" value="' + esc(a.query) + '" aria-label="Search applications"></div>' +
      '<div class="seg" role="group" aria-label="Filter">' + FILTERS.map(([v, l]) => '<button type="button" data-filter="' + v + '" aria-pressed="' + (a.filter === v) + '">' + l + "</button>").join("") + '</div></div><div id="a-body"></div></section></div></div>';
    renderAppsBody();
  }
  function renderAppsBody() {
    const body = $("#a-body"); if (!body) return; const a = S.apps;
    if (a.loading || a.rows === null) { body.innerHTML = '<div class="card-pad">' + [1, 2, 3, 4, 5].map(() => '<div class="skeleton" style="margin:14px 0"></div>').join("") + "</div>"; return; }
    if (!a.rows.length) { body.innerHTML = '<div class="empty-state">' + icon("inbox") + "<h3>No applications yet</h3><p>Submit signed-off jobs from Apply and they will appear here.</p></div>"; return; }
    const rows = filteredApps();
    if (!rows.length) { body.innerHTML = '<div class="empty-state">' + icon("search") + "<h3>No matches</h3><p>Try a different search or filter.</p></div>"; return; }
    const arrow = (k) => (a.sort.key === k ? '<span class="arrow">' + (a.sort.dir > 0 ? "↑" : "↓") + "</span>" : "");
    const shown = rows.slice(0, a.limit);
    body.innerHTML = '<div class="table-wrap"><table><thead><tr><th data-sort="company">Job' + arrow("company") + '</th><th data-sort="status">Status' + arrow("status") + '</th><th data-sort="ats">ATS match' + arrow("ats") + '</th><th aria-label="Saved to your account"></th><th aria-label="Open"></th></tr></thead><tbody>' +
      shown.map((r, idx) => {
        const k = statusKind(r.status), ats = parseInt(r.ats) || 0;
        return '<tr><td class="job"><div class="co">' + esc(r.company) + '</div><div class="ro" title="' + esc(r.title) + '">' + esc(r.title) + (r.platform ? '<span class="src"> · ' + esc(r.platform) + "</span>" : "") + "</div></td>" +
          '<td title="' + esc(r.status) + '">' + badge(statusLabel(r.status), k === "applied" ? "good" : k === "review" ? "warn" : "") + "</td>" +
          '<td><span class="score num">' + (r.ats ? '<span class="bar"><i style="width:' + Math.min(100, ats) + '%"></i></span>' + esc(r.ats) : "—") + "</span></td>" +
          '<td title="' + (r.synced ? "Saved to your account" : "Only on this computer") + '">' + icon(r.synced ? "cloud" : "cloudOff", ' class="cloud-ic' + (r.synced ? "" : " off") + '"') + "</td>" +
          '<td class="acts">' + (r.grounding ? '<button class="btn quiet" data-audit-idx="' + idx + '">Audit</button>' : "") +
          (r.pack ? '<button class="btn quiet" data-pack-dir="' + esc(r.pack) + '">Pack</button>' : "") +
          (r.url ? '<button class="btn quiet" data-url="' + esc(r.url) + '" aria-label="Open ' + esc(r.title) + '">Open</button>' : "") +
          (r.url && k === "review" ? '<button class="btn quiet" data-detail="' + esc(r.url) + '">Why</button><button class="btn quiet" data-review="' + esc(r.url) + '">Review</button>' : "") +
          (r.url ? '<select class="select stage" data-stage="' + esc(r.url) + '" aria-label="Update status of ' + esc(r.title) + '"><option value="">Update…</option>' + STAGES.map(([v, l]) => '<option value="' + v + '">' + l + "</option>").join("") + "</select>" : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>" +
      '<div class="foot">Showing ' + shown.length + " of " + rows.length + (rows.length > shown.length ? '&nbsp;·&nbsp;<button class="btn quiet" data-act="more">Show more</button>' : "") + "</div>";
  }

  /* ── Settings screen ─────────────────────────────────────────────────────── */
  const PROVIDERS = [["gemini", "Gemini", "Free tier available"], ["anthropic", "Claude", "Anthropic"], ["openai", "OpenAI", "GPT models"]];
  function watchSignIn() {
    if (S._sw) return;
    S._sw = setInterval(async () => {
      const r = await call("google_sign_in_status"); if (!r || r.state === "waiting") return;
      clearInterval(S._sw); S._sw = null;
      if (r.state === "error") S.gateError = r.error || "Sign-in failed.";
      await refreshInfo(); renderShell();
      if (r.state === "done" && S.info && S.info.session && S.info.session.signed_in) { toast("Signed in as " + r.email + "."); onSignedIn(); }
    }, 1000);
  }
  async function onSignedIn() {
    hydrateForm(); go(S.view === "settings" ? "settings" : "search");
    call("check_update").then((x) => { if (x && x.ok) { S.update = x; renderShell(); } });
    loadApps(true);
    const s = S.info; if (s && !(s.app_prefs || {}).tour_done) setTimeout(() => { if (!document.querySelector(".tour")) startTour(); }, 900);
  }
  function renderGate() {
    const el = $("#gate"), ses = S.info && S.info.session; if (!el) return;
    if (!S.info) { el.hidden = false; el.innerHTML = '<div class="gate-card"><div class="gate-logo">' + icon("logo") + '</div><div class="gate-wait"><span class="spin"></span>Starting…</div></div>'; return; }
    const show = !(ses && ses.signed_in); el.hidden = !show; if (!show) { el.innerHTML = ""; return; }
    const waiting = ses && ses.signing_in, offline = ses && ses.reason === "offline", expired = ses && ses.reason === "expired";
    const err = S.gateError || (ses && ses.error) || "";
    el.innerHTML = '<div class="gate-card" role="dialog" aria-modal="true" aria-labelledby="gate-t"><div class="gate-logo">' + icon("logo") + '</div><h1 id="gate-t">' + (offline ? "Cannot reach job-finder.space" : expired ? "Please sign in again" : "Sign in to Job Finder") + "</h1>" +
      "<p>" + (offline ? "Check your internet connection and try again. You can use the app offline for up to a week after you last signed in." : waiting ? "Finish signing in with Google in your browser. This window continues by itself." : "Job Finder is free. Sign in with your Google account to keep your applications saved to your account and in sync with the website and extension.") + "</p>" +
      (err ? '<div class="gate-error" role="alert">' + esc(err) + "</div>" : "") +
      (waiting ? '<div class="gate-wait"><span class="spin"></span>Waiting for your browser…</div><button class="btn" data-act="cancel-signin">Cancel</button>' :
        offline ? '<button class="btn primary lg" data-act="retry-session">Try again</button>' : '<button class="btn primary lg" data-act="google-signin">Sign in with Google</button>') +
      '<div class="gate-fine">We only receive your name and email from Google. Your API keys and resume file stay on this computer.</div></div>';
  }
  async function loadSchedule() { const r = await call("schedule_status"); if (r && r.ok) { S.sched = r; if (S.view === "settings") renderSettings(); } }
  function renderSettings() {
    const i = S.info; if (!i) { $("#view").innerHTML = head("Settings", "") + '<div class="scroll"><div class="skeleton"></div></div>'; return; }
    const br = i.browser, cl = i.cloud || {}, mb = i.mailbox || {}, pp = i.portal_password || {};
    const row = (t, d, ctl, id) => '<div class="setting"><div class="info"><div class="t">' + t + '</div><div class="d">' + d + '</div></div><div class="ctl"' + (id ? ' id="' + id + '"' : "") + ">" + ctl + "</div></div>";
    $("#view").innerHTML = head("Settings", "Your folder, AI providers and connections.") + nextBannerHtml() + '<div class="scroll"><div class="stack" style="max-width:820px">' +
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
        row("Your account", cl.connected ? "Signed in with Google as " + esc(cl.email || (i.session || {}).email || "") + ". Your applications are saved to your job-finder.space account and show on the website and in the extension." : esc(cl.error || "Checking your sign-in…"),
          (cl.connected ? badge("Connected", "good") : badge("Unreachable", "warn")) + '<button class="btn" data-act="sync-cloud">' + icon("refresh") + 'Sync now</button><button class="btn" data-act="disconnect-sync">Sign out</button><button class="btn danger" data-act="delete-account">Delete account…</button>', "c-sync") +
        row("Reply detection", mb.configured ? "Reads the last 30 days of " + esc(mb.user) + " for replies from employers and marks them (reply, interview, rejected, offer). Read only: nothing is sent, deleted or marked read." : "Optional. Connect a mailbox with an app password and replies from employers are marked for you. Automated 'we got your application' mails are ignored.",
          badge("Beta", "accent") + (mb.configured ? '<button class="btn" data-act="check-replies">' + icon("refresh") + 'Check now</button><button class="btn" data-act="disconnect-mailbox">Disconnect</button>' : '<button class="btn" data-act="add-mailbox">Connect…</button>'), "c-mailbox") +
        row("Daily run", S.sched && S.sched.enabled ? "Runs every day at " + String(S.sched.hour).padStart(2, "0") + ":" + String(S.sched.minute).padStart(2, "0") + (S.sched.real ? ", applying for real." : " as a practice run (nothing is submitted).") + " The Mac must be awake; the app does not need to be open." : "Runs a search every day at a time you choose, without opening the app. Starts as a practice run.",
          '<input class="input" id="sched-time" type="time" value="' + (S.sched && S.sched.enabled ? String(S.sched.hour).padStart(2, "0") + ":" + String(S.sched.minute).padStart(2, "0") : "08:00") + '" style="width:110px" aria-label="Daily run time">' +
          (S.sched && S.sched.enabled ? '<button class="btn" data-act="sched-on">Change time</button><button class="btn" data-act="sched-off">Turn off</button>' : '<button class="btn primary" data-act="sched-on">Turn on</button>')) +
        row("About you", (i.about_you && i.about_you.unanswered && i.about_you.unanswered.length && i.about_you.exists) ? "Still needed: where you can work, visa sponsorship, when you can start and the levels you want. Without them the agent cannot answer those questions." : "Work rights, start date, salary and the levels you want. The agent types your answers instead of guessing.",
          ((i.about_you && i.about_you.exists && i.about_you.unanswered.length) ? badge("Needs answers", "warn") : "") + '<button class="btn" data-act="edit-about">' + ((i.about_you && i.about_you.exists && i.about_you.unanswered.length) ? "Answer…" : "Edit…") + "</button>") +
        row("Saved answers", "Answers to questions your profile does not cover, such as why you want the job. The agent uses them word for word instead of guessing.", '<button class="btn" data-act="edit-answers">Edit…</button>') +
        row("Job site sign-ins", "Opens the agent's Chrome so you can sign in to LinkedIn, Indeed, Reed and MyGreenhouse once. Runs reuse the sign-ins.", '<button class="btn" data-act="open-signin">Open Chrome to sign in</button>') +
        row("Portal sign-up password", "Optional. Used when a job portal (like Workday or Reed) requires creating an account or signing in with email + password. Stored in .env only.",
          (pp.set ? badge("Saved" + (pp.hint ? " ···" + pp.hint : ""), "good") : badge("Not set")) + '<button class="btn" data-act="edit-portal-pw">' + (pp.set ? "Replace…" : "Add password…") + "</button>", "c-portal-pw") +
        row("Page scraper browser", br.ready ? "Installed" : br.installing ? "Downloading, about 150 MB…" : (br.error ? esc(br.error) : "Needed for some job sources. Downloaded once."), br.ready ? badge("Ready", "good") : br.installing ? badge("Installing", "accent") : '<button class="btn" data-act="install-browser">' + icon("download") + "Install</button>") +
        row("Company boards index", (i.boards && i.boards.ready) ? "Indexed local Greenhouse/Lever/Ashby boards (updated " + esc(i.boards.updated) + ")." : "Not built yet. Indexes ~8,500 company boards for fast direct-link searches.", ((i.boards && i.boards.ready) ? badge("Ready", "good") : badge("Not built")) + '<button class="btn" data-act="refresh-boards">' + icon("refresh") + "Refresh</button>") +
      "</section>" +
      '<div class="sect-title">About</div><section class="card">' +
        row("Job Finder " + esc(i.version), S.update && S.update.newer ? "Version " + esc(S.update.latest) + " is available." : S.update ? "You are up to date." : "Check for a newer version.", '<button class="btn" data-act="check-update">Check for updates</button>' + (S.update && S.update.newer ? '<button class="btn primary" data-url="' + esc(S.update.url) + '">Download</button>' : "")) +
        row("Guided tour", "A short walk through the staged workflow.", '<button class="btn" data-act="start-tour">Take the tour</button>') +
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
    renderSearch(); saveFormSoon(); const el = $('[data-tags="' + id + '"] input'); if (el) el.focus();
  }

  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.matches && t.matches('.tags input')) {
      const id = t.closest("[data-tags]").dataset.tags;
      if (e.key === "Enter" || e.key === ",") { e.preventDefault(); addTag(id, t.value); }
      else if (e.key === "Backspace" && !t.value && S.form[id].length) { S.form[id].pop(); renderSearch(); saveFormSoon(); const el = $('[data-tags="' + id + '"] input'); if (el) el.focus(); }
    }
    if (isMod(e) && e.key === "Enter") {
      e.preventDefault();
      if (S.run.running) call("stop_scan");
      else if (S.view === "apply") startApply();
      else startScan();
    } else if (isMod(e) && e.key === ".") {
      e.preventDefault(); call("stop_scan");
    } else if (isMod(e) && ["1", "2", "3", "4", "5", "6", "7"].includes(e.key)) {
      e.preventDefault(); go(NAV[Number(e.key) - 1][0]);
    } else if (isMod(e) && e.key === ",") {
      e.preventDefault(); go("settings");
    }
  });

  document.addEventListener("focusout", (e) => {
    const t = e.target;
    if (t.matches && t.matches(".tags input") && t.value.trim()) addTag(t.closest("[data-tags]").dataset.tags, t.value);
  });

  document.addEventListener("input", (e) => {
    const t = e.target, f = S.form;
    if (t.id === "f-topic") { f.topic = t.value; return; }
    if (t.id === "f-into") { f.into = t.value; return; }
    if (t.id === "del-confirm-email") { S._delEmail = t.value; return; }
    if (t.id === "f-location") f.location = t.value;
    else if (t.id === "f-ats") f.min_ats = t.value;
    else if (t.id === "f-limit") f.limit = t.value;
    else if (t.id === "a-q") { S.apps.query = t.value; renderAppsBody(); return; }
    else if (t.id === "rev-q") { S.review.query = t.value; renderReviewBody(); return; }
    else if (t.id === "rev-min-ats") {
      S.review.minAts = Number(t.value) || 0;
      const btn = $('[data-act="approve-min"]');
      if (btn) btn.textContent = "Approve ≥ " + S.review.minAts + "%";
      return;
    } else if (t.id === "ap-limit") { S.apply.limit = Number(t.value) || 5; return; }
    else return;
    saveFormSoon();
  });

  document.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset && t.dataset.stage) {
      const url = t.dataset.stage, v = t.value; t.value = ""; if (!v) return;
      call("set_status", url, v).then(async (r) => { if (r && r.ok) { toast("Status updated."); await loadApps(true); await refreshInfo(); } else toast((r && r.error) || "Could not update.", "bad"); });
      return;
    }
    if (t.id === "rev-search") { S.review.search = t.value; S.review.selected.clear(); loadReview(); return; }
    if (t.id === "rev-all") {
      const jobs = filteredReviewJobs();
      if (t.checked) jobs.forEach((j) => S.review.selected.add(j.id));
      else S.review.selected.clear();
      renderReview(); return;
    }
    if (t.dataset && t.dataset.revChk) {
      const id = t.dataset.revChk;
      if (t.checked) S.review.selected.add(id); else S.review.selected.delete(id);
      renderReview(); return;
    }
    if (t.id === "pk-all") {
      const list = S.packs.list || [];
      if (t.checked) list.forEach((p) => S.packs.selected.add(p.id));
      else S.packs.selected.clear();
      renderPacks(); return;
    }
    if (t.dataset && t.dataset.pkChk) {
      const id = t.dataset.pkChk;
      if (t.checked) S.packs.selected.add(id); else S.packs.selected.delete(id);
      renderPacks(); return;
    }
    if (t.id === "f-ai") { S.form.primary_ai = t.value; call("save_app_prefs", { primary_ai: t.value }); }
    else if (t.id === "f-headless") { S.form.headless = t.checked; call("save_app_prefs", { headless: t.checked }); }
    else if (t.id === "f-score-all") { S.form.score_all = t.checked; }
    else if (t.id === "ap-headless") { S.apply.headless = t.checked; }
    else if (t.id === "ap-cap") {
      const val = Math.max(1, Math.min(200, Number(t.value) || 20));
      S.apply.cap.limit = val;
      call("save_app_prefs", { daily_cap: val }).then(() => loadApply());
    }
  });

  document.addEventListener("toggle", (e) => { if (e.target.classList && e.target.classList.contains("disclosure")) S.advOpen = e.target.open; }, true);
  document.addEventListener("scroll", (e) => { if (e.target && e.target.id === "log") { const l = e.target; S.stick = l.scrollTop + l.clientHeight >= l.scrollHeight - 30; } }, true);

  document.addEventListener("click", async (e) => {
    const el = e.target.closest("button, [data-nav], th[data-sort]"); if (!el) return;
    const d = el.dataset;
    if (d.nav) return go(d.nav);
    if (d.goto) return go(d.goto);
    if (d.rm) { const [id, idx] = d.rm.split(":"); S.form[id].splice(Number(idx), 1); renderSearch(); saveFormSoon(); return; }
    if (d.time) { S.form.timeframe = d.time; renderSearch(); saveFormSoon(); return; }
    if (d.level) { S.form.level = d.level; renderSearch(); return; }
    if (d.scanMode) { S.form.mode = d.scanMode; renderSearch(); return; }
    if (d.search !== undefined) {
      if (!d.search) { S.form.search = ""; S.form.topics = []; S.form.topic = ""; }
      else {
        const s = S.searches.find((x) => x.name === d.search);
        if (s) {
          S.form.search = s.name; S.form.topic = s.topic || "";
          S.form.topics = (s.topic || "").split(",").map((x) => x.trim()).filter(Boolean);
          S.form.level = s.level || "all"; S.form.location = s.location || S.form.location;
        }
      }
      renderSearch(); return;
    }
    if (d.revFilter) { S.review.filter = d.revFilter; renderReview(); return; }
    if (d.approveOne) {
      const r = await call("approve_jobs", { ids: [d.approveOne] });
      if (r && r.ok) { toast("Approved."); await loadReview(); await refreshNextStep(); }
      return;
    }
    if (d.revokeOne) {
      const r = await call("revoke_jobs", { ids: [d.revokeOne] });
      if (r && r.ok) { toast("Revoked."); await loadReview(); await refreshNextStep(); }
      return;
    }
    if (d.prepOne) {
      const r = await call("prepare_packs", { ids: [d.prepOne] });
      if (r && r.ok) {
        Object.assign(S.run, { kind: "prepare", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 1, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
        S.stick = true; renderPacks(); watchRun();
      }
      return;
    }
    if (d.viewDoc) { S.docs.selectedId = d.viewDoc; go("documents"); return; }
    if (d.docSel) { S.docs.selectedId = d.docSel; loadPackDocs(d.docSel); return; }
    if (d.docTab) { S.docs.tab = d.docTab; renderDocuments(); return; }
    if (d.openPack) {
      const [id, kind] = d.openPack.split(":");
      await call("open_pack_file", id, kind);
      return;
    }
    if (d.applyMode) { S.apply.mode = d.applyMode; renderApply(); return; }
    if (d.auditIdx !== undefined) {
      const row = filteredApps()[Number(d.auditIdx)];
      if (row && row.grounding) {
        const g = row.grounding, qs = row.questions || [];
        await dialog({
          title: "Grounding audit — " + row.company,
          confirm: "Close",
          body: "<p>" + esc(row.title) + "</p><ul>" +
            "<li>Answered from profile: <span>" + (g.answered_from_profile || 0) + "</span></li>" +
            "<li>Verified: <span>" + (g.verified ? "Yes" : "No") + "</span></li>" +
            (g.no_data && g.no_data.length ? "<li>No data: <span>" + esc(g.no_data.join(", ")) + "</span></li>" : "") +
            (g.stopped && g.stopped.length ? "<li>Stopped: <span>" + esc(g.stopped.join(", ")) + "</span></li>" : "") +
            (g.ungrounded && g.ungrounded.length ? "<li>Ungrounded: <span>" + esc(g.ungrounded.join(", ")) + "</span></li>" : "") +
            qs.map((q) => "<li>" + esc(q.question) + ": <span>" + esc(q.answer) + "</span></li>").join("") +
            "</ul>",
        });
      }
      return;
    }
    if (d.review) { toast("Opening the job in Chrome…"); const r = await call("review_in_chrome", d.review); toast(r && r.ok ? "Opened. Check the form and submit it there." : (r && r.error) || "Could not open Chrome.", r && r.ok ? undefined : "bad"); return; }
    if (d.detail) { const r = await call("review_info", d.detail); const has = r && r.screenshot;
      const ok = await dialog({ title: "Why it stopped", body: "<p>" + esc((r && r.reason) || "No reason was recorded for this job. Open the job and check the form yourself.") + "</p>", confirm: has ? "Open screenshot" : "OK" });
      if (ok && has) call("open_screenshot", d.detail); return; }
    if (d.filter) { S.apps.filter = d.filter; S.apps.limit = 100; renderApps(); return; }
    if (d.sort) { const s = S.apps.sort; s.dir = s.key === d.sort ? -s.dir : 1; s.key = d.sort; renderAppsBody(); return; }
    if (d.url) return void call("open_url", d.url);
    if (d.packDir) return void call("open_pack_folder", d.packDir);
    if (d.open) return void call("open_path", d.open);
    if (d.key) return keyEditor(d.key);
    if (d.savekey) {
      const v = $("#ki-" + d.savekey).value; const r = await call("save_key", d.savekey, v);
      if (r && r.ok) { toast("Key saved."); await refreshInfo(); renderSettings(); } return;
    }
    switch (d.act) {
      case "start-scan": return startScan();
      case "start-apply": return startApply();
      case "approve-selected": {
        const ids = [...S.review.selected];
        if (!ids.length) return;
        const r = await call("approve_jobs", { ids });
        if (r && r.ok) { toast("Approved " + plural(r.approved, "job") + "."); S.review.selected.clear(); await loadReview(); await refreshNextStep(); }
        return;
      }
      case "revoke-selected": {
        const ids = [...S.review.selected];
        if (!ids.length) return;
        const r = await call("revoke_jobs", { ids });
        if (r && r.ok) { toast("Revoked " + plural(r.revoked, "job") + "."); S.review.selected.clear(); await loadReview(); await refreshNextStep(); }
        return;
      }
      case "approve-min": {
        const r = await call("approve_jobs", { min_ats: S.review.minAts });
        if (r && r.ok) { toast("Approved " + plural(r.approved, "job") + " at or above " + S.review.minAts + "%."); await loadReview(); await refreshNextStep(); }
        return;
      }
      case "prepare-packs": {
        const ids = [...S.packs.selected];
        const r = await call("prepare_packs", { ids });
        if (r && r.ok) {
          S.packs.selected.clear();
          Object.assign(S.run, { kind: "prepare", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: ids.length || 1, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
          S.stick = true; renderPacks(); watchRun();
        }
        return;
      }
      case "signoff-pack": {
        const id = d.id;
        const r = await call("signoff_pack", id);
        if (r && r.ok) {
          toast("Signed off for Apply.");
          const nextNeed = (S.docs.packs || []).find((p) => p.id !== id && (p.state === "needs_signoff" || p.state === "ready"));
          await loadDocuments(nextNeed ? nextNeed.id : id);
          await refreshNextStep();
        }
        return;
      }
      case "redo-pack": case "new-draft": {
        const r = await call("prepare_packs", { ids: [d.id], redo: true, fresh: d.act === "new-draft" });
        if (r && r.ok) {
          Object.assign(S.run, { kind: "prepare", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 1, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
          S.stick = true; go("packs"); watchRun();
        }
        return;
      }
      case "save-cv-json": {
        const summary = ($("#cv-sum") || {}).value || "";
        const experience = $all("[data-cv-exp]").map((el) => el.value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean));
        const r = await call("save_pack_cv", d.id, { summary, experience });
        if (r && r.ok) {
          toast("Saved cv.json — re-rendering PDF…");
          Object.assign(S.run, { kind: "prepare", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 1, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
          S.stick = true; watchRun();
        }
        return;
      }
      case "confirm-skill": {
        const ok = await dialog({
          title: "Do you have " + d.skill + "?",
          icon: "alert", confirm: "Add to my profile",
          body: '<p class="help">Only say yes if it is true. Write one or two sentences about where you used it, in your own words. They are kept in your profile as your evidence, are not printed on the CV, and the skill is then listed on CVs built from now on.</p>' +
                '<div class="field"><label for="cs-ev">Where did you use ' + esc(d.skill) + '?</label><textarea class="input" id="cs-ev" rows="3" maxlength="500" placeholder="e.g. Built an iOS prototype in ' + esc(d.skill) + ' during my MSc coursework."></textarea></div>',
          collect: (wrap) => ({ evidence: ($("#cs-ev", wrap) || {}).value || "" }),
        });
        if (!ok) return;
        const r = await call("confirm_experience", d.skill, ok.evidence, "");
        if (r && r.ok) {
          const again = await dialog({ title: "Rebuild this CV now?", icon: "alert", confirm: "Rebuild",
            body: "<p>" + esc(d.skill) + " is saved. Rebuild this pack to put it on the CV. Your edits to this pack's cv.json are replaced.</p>" });
          if (again) {
            const q = await call("prepare_packs", { ids: [d.id], redo: true });
            if (q && q.ok) { Object.assign(S.run, { kind: "prepare", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 1, position: 0, submitted: 0, needs_review: 0, skipped: 0 } }); S.stick = true; go("packs"); watchRun(); }
          } else { await loadDocuments(d.id); }
        }
        else toast((r && r.error) || "Could not save.", "bad");
        return;
      }
      case "unconfirm-skill": {
        const ok = await dialog({ title: "Remove " + d.skill + "?", confirm: "Remove", danger: true,
          body: "<p>It will no longer be listed on CVs built from now on. CVs already built keep it until you rebuild them.</p>" });
        if (!ok) return;
        const r = await call("remove_confirmed_experience", d.skill);
        if (r && r.ok) { toast(d.skill + " removed."); await loadPackDocs(d.id); }
        return;
      }
      case "latex-open": case "latex-reset": {
        S.docs.latex = { id: d.id, busy: true, tex: "", pages: [] }; renderDocuments();
        const r = await call(d.act === "latex-reset" ? "reset_pack_latex" : "get_pack_latex", d.id);
        S.docs.latex = r && r.ok ? { id: d.id, tex: r.tex, pages: r.pages || [], available: r.available, in_use: r.in_use, meta: r.source === "saved" ? "Your saved LaTeX." : "Generated from your CV." }
                                 : { id: d.id, tex: "", pages: [], error: (r && r.error) || "Could not open the LaTeX." };
        renderDocuments();
        return;
      }
      case "latex-compile": {
        const tex = ($("#cv-tex") || {}).value || "";
        const prev = S.docs.latex || { id: d.id };
        S.docs.latex = { ...prev, id: d.id, tex, busy: true, error: "" }; renderDocuments();
        const r = await call("compile_pack_latex", d.id, tex);
        if (r && r.ok) {
          S.docs.latex = { ...prev, id: d.id, tex, busy: false, error: "", pages: r.pages || [], warnings: r.warnings || [],
            meta: r.page_count + (r.page_count === 1 ? " page" : " pages") + (r.fill != null ? ", " + Math.round(r.fill * 100) + "% full" : "") + (r.tightened ? ", spacing tightened to fit one page" : "") };
        } else {
          S.docs.latex = { ...prev, id: d.id, tex, busy: false, error: (r && r.error) || "Compile failed." };
        }
        renderDocuments();
        return;
      }
      case "latex-use": {
        const r = await call("use_pack_latex_pdf", d.id);
        if (r && r.ok) { toast("This LaTeX PDF will be used for applications."); S.docs.latex = { ...S.docs.latex, in_use: true }; renderDocuments(); }
        return;
      }
      case "latex-use-standard": {
        const r = await call("use_standard_cv_pdf", d.id);
        if (r && r.ok) { toast("Switched back to the standard CV PDF."); S.docs.latex = { ...S.docs.latex, in_use: false }; await loadPackDocs(d.id); }
        else toast((r && r.error) || "Could not switch back to the standard CV.");
        return;
      }
      case "revert-change": {
        const r = await call("revert_pack_change", d.id, d.chg);
        if (r && r.ok) {
          toast("Reverted change — rebuilding PDF…");
          await loadDocuments(d.id);
        }
        return;
      }
      case "revoke-pack": {
        const r = await call("revoke_jobs", { ids: [d.id] });
        if (r && r.ok) { toast("Revoked from queue."); S.docs.selectedId = null; await loadDocuments(); await refreshNextStep(); }
        return;
      }
      case "refresh-boards": {
        const r = await call("refresh_boards");
        if (r && r.ok) {
          Object.assign(S.run, { kind: "scan", running: true, offset: 0, lines: [], exit: null, started: true, counts: { found: 0, position: 0, submitted: 0, needs_review: 0, skipped: 0 } });
          S.stick = true; go("search"); watchRun();
        }
        return;
      }
      case "cancel-key": return renderSettings();
      case "edit-portal-pw": { const ctl = $("#c-portal-pw"); if (!ctl) return; ctl.innerHTML = '<span class="keybox"><input class="input" type="password" id="ki-portal-pw" placeholder="Portal sign-up password" autocomplete="off" spellcheck="false" aria-label="Portal sign-up password"><button class="btn primary" data-act="save-portal-pw">Save</button><button class="btn" data-act="cancel-key">Cancel</button></span>'; $("#ki-portal-pw").focus(); return; }
      case "save-portal-pw": { const r = await call("save_portal_password", ($("#ki-portal-pw") || {}).value || ""); if (r && r.ok) { toast("Portal password saved."); await refreshInfo(); renderSettings(); } return; }
      case "google-signin": { S.gateError = ""; const r = await call("google_sign_in"); if (r && r.ok) { await refreshInfo(); renderShell(); watchSignIn(); } return; }
      case "cancel-signin": { await call("cancel_google_sign_in"); await new Promise((res) => setTimeout(res, 600)); await refreshInfo(); renderShell(); return; }
      case "retry-session": { await call("session_check"); await refreshInfo(); renderShell(); if (S.info && S.info.session && S.info.session.signed_in) onSignedIn(); return; }
      case "disconnect-sync": { await call("disconnect_sync"); S.apps.rows = null; toast("Signed out. Your applications stay on this computer."); await refreshInfo(); renderSettings(); return; }
      case "delete-account": {
        const email = (S.info && (S.info.cloud && S.info.cloud.email || S.info.session && S.info.session.email)) || "";
        S._delEmail = "";
        const ok = await dialog({
          title: "Delete your account?", icon: "alert", danger: true, confirm: "Delete account",
          body: "<p>This permanently removes your account, saved resumes, and synced application history from job-finder.space. Local files on this computer stay intact.</p>" +
            '<div class="field" style="margin-top:12px"><label for="del-confirm-email">Type your email (' + esc(email) + ') to confirm</label>' +
            '<input class="input" id="del-confirm-email" type="email" placeholder="' + esc(email) + '" autocomplete="off"></div>',
        });
        if (!ok) return;
        const typed = S._delEmail || "";
        if (!typed.trim()) { toast("Type your email to confirm.", "bad"); return; }
        const r = await call("delete_account", typed.trim());
        if (r && r.ok) { S.apps.rows = null; toast("Account deleted from job-finder.space."); await refreshInfo(); renderShell(); }
        return;
      }
      case "sync-cloud": { const r = await call("sync_cloud_now"); if (r && r.ok) toast(r.pushed ? "Added " + plural(r.pushed, "application") + " to job-finder.space." : "job-finder.space is up to date."); else toast((r && r.error) || "Sync failed.", "bad"); await refreshInfo(); renderSettings(); return; }
      case "stop": return void call("stop_scan");
      case "goto-settings": return go("settings");
      case "choose-ws": { const r = await call("choose_workspace"); if (r && r.ok) { S.info = r.state; S.apps.rows = null; hydrateForm(); toast("Folder changed."); go(S.view); } return; }
      case "build-profile": { const r = await call("choose_resume_and_build_profile"); if (r && r.ok) { go("search"); Object.assign(S.run, { kind: "scan", running: true, started: true, offset: 0, lines: [], exit: null }); renderRunStatus(); renderLog(true); watchRun(); } return; }
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
      case "edit-about": return void openAboutYou();
      case "start-tour": return void startTour();
      case "install-browser": await call("ensure_browser"); await refreshInfo(); renderSettings(); watchBrowser(); return;
      case "sync": { if (S.apps.syncing) return; S.apps.syncing = true; renderView(); const r = await call("sync_cloud_now"); S.apps.syncing = false;
        if (r && r.ok) toast(r.pushed ? "Added " + plural(r.pushed, "application") + " to your account." : "Your account is up to date."); else toast((r && r.error) || "Sync failed.", "bad"); await loadApps(true); await refreshInfo(); renderView(); return; }
      case "more": S.apps.limit += 200; renderAppsBody(); return;
      case "copy-log": { try { await navigator.clipboard.writeText(S.run.lines.join("\n")); toast("Log copied."); } catch (_) { toast("Could not copy the log.", "bad"); } return; }
      case "open-logs": return void call("open_path", "logs");
      case "check-update": { const r = await call("check_update"); S.update = r && r.ok ? r : S.update; renderShell(); if (S.view === "settings") renderSettings(); if (r && r.ok && !r.newer) toast("You are on the latest version."); return; }
    }
  });
  $("#update-chip").addEventListener("click", () => S.update && call("open_url", S.update.url));

  /* ── Start-up ────────────────────────────────────────────────────────────── */
  let lastFocusRefresh = 0;
  window.addEventListener("focus", () => { if (Date.now() - lastFocusRefresh > 1500) { lastFocusRefresh = Date.now(); refreshInfo().then(() => { if (S.view === "settings") renderSettings(); }); } });
  async function refreshInfo() { const s = await call("get_state"); if (s && s.workspace) { S.info = s; renderShell(); } return s; }
  function hydrateForm() {
    const p = S.info.prefs;
    Object.assign(S.form, {
      roles: p.roles || [], location: p.location || "",
      timeframe: ["24h", "48h", "1w", "1m"].includes(p.timeframe) ? p.timeframe : "1m",
      min_ats: p.min_ats, title_keywords: p.title_keywords || [], skip_portals: p.skip_portals || [],
      primary_ai: (S.info.app_prefs || {}).primary_ai || "auto",
      headless: !!(S.info.app_prefs || {}).headless,
    });
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

  /* ── About you: the questions a resume cannot answer ─────────────────────── */
  async function openAboutYou() {
    const data = await call("get_about_you");
    if (!data || !data.ok) { toast("Could not open the questions.", "bad"); return false; }
    return new Promise((resolve) => {
      const wrap = document.createElement("div"); wrap.className = "scrim";
      const close = (saved) => { document.removeEventListener("keydown", onKey, true); wrap.remove(); resolve(saved); };
      const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(false); } };
      document.addEventListener("keydown", onKey, true);
      if (!data.exists) {
        wrap.innerHTML = '<div class="dialog" role="dialog" aria-modal="true"><h2>Create your profile first</h2><p>These questions are saved into your profile, so build it from your resume first. It takes a minute, and then come back here.</p><div class="btns"><button type="button" class="btn primary" data-ab="close">OK</button></div></div>';
        wrap.addEventListener("click", (e) => { if (e.target.closest('[data-ab="close"]') || e.target === wrap) close(false); });
        $("#overlay").appendChild(wrap); return;
      }
      const values = {}; data.fields.forEach((f) => { values[f.key] = f.value !== null && f.value !== undefined && f.value !== "" ? f.value : (f.kind === "multi" ? [] : (f.default || (f.kind === "bool" ? null : ""))); });
      const control = (f) => {
        const id = "ab-" + f.key;
        if (f.kind === "bool") return '<div class="seg" role="group" aria-label="' + esc(f.label) + '"><button type="button" data-ab-bool="' + f.key + ':yes" aria-pressed="' + (values[f.key] === true) + '">Yes</button><button type="button" data-ab-bool="' + f.key + ':no" aria-pressed="' + (values[f.key] === false) + '">No</button></div>';
        if (f.kind === "multi") return '<div class="chips">' + f.options.map((o) => '<button type="button" class="chip pick" data-ab-multi="' + f.key + ":" + esc(o) + '" aria-pressed="' + values[f.key].includes(o) + '">' + esc(o) + "</button>").join("") + "</div>";
        const list = f.options ? '<datalist id="' + id + '-dl">' + f.options.map((o) => '<option value="' + esc(o) + '">').join("") + "</datalist>" : "";
        return '<input class="input" id="' + id + '" data-ab-text="' + f.key + '" maxlength="200" value="' + esc(values[f.key]) + '"' + (f.options ? ' list="' + id + '-dl"' : "") + ' placeholder="' + esc(f.placeholder || (f.options ? "Pick one or type your own" : "")) + '" autocomplete="off">' + list;
      };
      const draw = () => {
        let last = "";
        const body = data.fields.map((f) => {
          const h = f.section !== last ? '<div class="ab-sec">' + esc(f.section) + "</div>" : ""; last = f.section;
          return h + '<div class="ab-q"><label for="ab-' + f.key + '">' + esc(f.label) + (f.required ? ' <span class="req" aria-label="needed">*</span>' : "") + "</label>" + control(f) + (f.help ? '<div class="d">' + esc(f.help) + "</div>" : "") + "</div>";
        }).join("");
        wrap.innerHTML = '<div class="dialog wide" role="dialog" aria-modal="true" aria-labelledby="ab-title"><h2 id="ab-title">A few things your resume cannot say</h2>' +
          "<p>Application forms ask these. The agent types exactly what you choose here, and never guesses. Stars are needed; the rest are optional.</p>" +
          '<div class="ab-list">' + body + "</div>" +
          '<div class="btns"><button type="button" class="btn" data-ab="close">Not now</button><button type="button" class="btn primary" data-ab="save">Save</button></div></div>';
      };
      const collectText = () => $all("[data-ab-text]", wrap).forEach((el) => { values[el.dataset.abText] = el.value; });
      wrap.addEventListener("click", async (e) => {
        const b = e.target.closest("button"); if (!b) { if (e.target === wrap) close(false); return; }
        collectText();
        if (b.dataset.abBool) { const [k, v] = b.dataset.abBool.split(":"), want = v === "yes"; values[k] = values[k] === want ? null : want; const list = $(".ab-list", wrap), top = list ? list.scrollTop : 0; draw(); const again = $(".ab-list", wrap); if (again) again.scrollTop = top; return; }
        if (b.dataset.abMulti) { const i = b.dataset.abMulti.indexOf(":"), k = b.dataset.abMulti.slice(0, i), o = b.dataset.abMulti.slice(i + 1); values[k] = values[k].includes(o) ? values[k].filter((x) => x !== o) : values[k].concat(o); const list = $(".ab-list", wrap), top = list ? list.scrollTop : 0; draw(); const again = $(".ab-list", wrap); if (again) again.scrollTop = top; return; }
        if (b.dataset.ab === "close") return close(false);
        if (b.dataset.ab === "save") {
          const missing = data.fields.filter((f) => f.required && (f.kind === "multi" ? !values[f.key].length : f.kind === "bool" ? values[f.key] === null : !String(values[f.key]).trim()));
          if (missing.length) { toast("Still needed: " + missing.map((f) => f.label.replace(/\?$/, "")).join(", ") + ".", "bad"); return; }
          const r = await call("save_about_you", values);
          if (r && r.ok) { close(true); toast("Saved to your profile."); await refreshInfo(); renderView(); }
          else toast((r && r.error) || "Could not save.", "bad");
        }
      });
      draw(); $("#overlay").appendChild(wrap);
      const first = $("input", wrap); if (first) first.focus();
    });
  }

  /* ── Guided tour ─────────────────────────────────────────────────────────── */
  const TOUR = [
    { view: "settings", sel: "#c-gemini", title: "Add an AI key", text: "The agent needs one provider to read job pages and tailor CVs. Gemini has a free tier. Keys stay in a file on this Mac." },
    { view: "settings", sel: '[data-act="build-profile"], [data-act="import-profile"]', title: "Create your profile", text: "Build it from your resume, or import a profile.json you already have. Every form and tailored CV is grounded in it." },
    { view: "settings", sel: '[data-act="edit-about"]', title: "Tell us what your resume cannot", text: "Forms ask where you can work, whether you need a visa, when you can start and what you want to earn. Answer once and the agent uses it.", cta: "Answer now" },
    { view: "settings", sel: '[data-act="open-signin"]', title: "Sign in to job sites", text: "LinkedIn, Indeed, Reed and MyGreenhouse work best when you are signed in. Open Chrome once, sign in, and future runs reuse it." },
    { view: "settings", sel: "#c-portal-pw", title: "Portal sign-up password", text: "Optional. Stored privately in .env for portals like Workday or Reed that require creating an account with email and password." },
    { view: "settings", sel: "#c-sync", title: "Saved to your account", text: "Your applications sync to your job-finder.space account automatically. Use Sync now anytime to push or refresh." },
    { view: "settings", sel: "#c-mailbox", title: "See replies automatically", text: "Optional. Connect your mailbox with an app password and employer replies, interviews and rejections are marked for you." },
    { view: "settings", sel: '[data-act="edit-answers"]', title: "Write answers once", text: "For questions your profile cannot answer, such as why you want the job. The agent types your answer word for word instead of guessing." },
    { view: "settings", sel: "#sched-time", title: "Run every morning", text: "Optional. Pick a time and a daily run starts by itself, even when the app is closed." },
    { view: "search", sel: '[data-tags="topics"]', title: "1. Search for jobs", text: "Add one or more topics/roles, pick a level and location. Use Dry-run to inspect the search funnel, or Run to save scored jobs into an Excel workbook." },
    { view: "review", sel: '[data-nav="review"]', title: "2. Review and approve", text: "Tick the jobs you want to apply for, or approve everything above a minimum ATS score." },
    { view: "packs", sel: '[data-nav="packs"]', title: "3. Prepare application packs", text: "Each approved job gets its own folder with a tailored 1-page CV, fit analysis, and cover letter when requested." },
    { view: "documents", sel: '[data-nav="documents"]', title: "4. Review documents & sign off", text: "Inspect the tailored CV, cover letter, and REVIEW.md checklist, then click Docs OK before applying." },
    { view: "apply", sel: '[data-nav="apply"]', title: "5. Preview and Apply", text: "Only signed-off jobs appear here. Start with Preview to watch the agent fill forms, then Submit when ready." },
    { view: "apps", sel: '[data-nav="apps"]', title: "6. Track applications", text: "Every submitted or in-progress application is tracked here and synced to your account." },
  ];

  async function startTour(from) {
    let i = 0;
    const layer = document.createElement("div"); layer.className = "tour"; $("#overlay").appendChild(layer);
    const closeLayer = () => { layer.remove(); document.removeEventListener("keydown", onKey, true); window.removeEventListener("resize", place); };
    const finish = () => { closeLayer(); call("save_app_prefs", { tour_done: true }); go("search"); };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); finish(); } else if (e.key === "ArrowRight" || e.key === "Enter") { e.preventDefault(); next(); } else if (e.key === "ArrowLeft") { e.preventDefault(); back(); } };
    document.addEventListener("keydown", onKey, true);
    let current = null;
    function place() {
      if (!current) return; const r = current.el.getBoundingClientRect(), pad = 6;
      const hole = $(".tour-hole", layer), card = $(".tour-card", layer);
      Object.assign(hole.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
      const cw = 370, ch = card.offsetHeight || 170;
      let left = Math.min(Math.max(12, r.left), window.innerWidth - cw - 12), top = r.bottom + 16;
      if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 16);
      Object.assign(card.style, { left: left + "px", top: top + "px", width: cw + "px" });
    }
    async function show(n) {
      const step = TOUR[n]; go(step.view); await new Promise((res) => setTimeout(res, 110));
      const el = document.querySelector(step.sel);
      if (!el) return n >= i ? next(n + 1) : back(n - 1);
      el.scrollIntoView({ block: "center" }); current = { el, step, n };
      const total = TOUR.length;
      layer.innerHTML = '<div class="tour-hole"></div><div class="tour-card" role="dialog" aria-label="Guided tour"><div class="tour-n">Step ' + (n + 1) + " of " + total + "</div><h3>" + esc(step.title) + "</h3><p>" + esc(step.text) + '</p><div class="tour-btns"><button class="btn quiet" data-t="skip">Skip tour</button><span class="grow"></span>' +
        (n > 0 ? '<button class="btn" data-t="back">Back</button>' : "") + '<button class="btn primary" data-t="next">' + (n === total - 1 ? "Done" : "Next") + "</button></div></div>";
      if (step.cta) { const nx = $('[data-t="next"]', layer); nx.insertAdjacentHTML("beforebegin", '<button class="btn primary" data-t="cta">' + esc(step.cta) + "</button>"); nx.classList.remove("primary"); }
      i = n; place();
      ($('[data-t="cta"]', layer) || $('[data-t="next"]', layer)).focus();
    }
    function next(n) { const to = typeof n === "number" ? n : i + 1; if (to >= TOUR.length) return finish(); show(to); }
    function back(n) { const to = typeof n === "number" ? n : i - 1; if (to < 0) return; show(to); }
    layer.addEventListener("click", (e) => { const b = e.target.closest("[data-t]"); if (!b) return; if (b.dataset.t === "cta") { const resumeAt = i + 1; closeLayer(); openAboutYou().then(() => startTour(resumeAt)); return; }
      ({ next, back, skip: finish })[b.dataset.t](); });
    window.addEventListener("resize", place);
    show(typeof from === "number" ? from : 0);
  }

  async function init() {
    renderShell(); go("search");
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme); applyTheme();
    const s = await refreshInfo(); if (!s || !s.workspace) return;
    renderShell();
    if (s.session && s.session.signing_in) watchSignIn();
    if (!(s.session && s.session.signed_in)) return;
    if (s.running) { S.run.running = true; S.run.started = true; watchRun(); }
    if (s.browser && s.browser.installing) watchBrowser();
    onSignedIn();
  }

  window.__jf = {
    hasInfo: () => !!(S.info && S.info.workspace),
    go,
    checkUpdate: () => { go("settings"); const b = document.querySelector('[data-act="check-update"]'); if (b) b.click(); },
  };
  init();
})();
