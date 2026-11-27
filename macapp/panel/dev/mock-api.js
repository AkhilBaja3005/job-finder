/* Stand-in for the Python side, for working on the window in a normal browser. Not shipped with the app.
   Open dev/index.html through a local web server (python3 -m http.server) from the panel folder. */
(function () {
  const q = new URLSearchParams(location.search);
  const empty = q.has("empty");
  let savedAnswers = [{ question: "Earliest start date", answer: "Available to start immediately." }];
  const companies = ["Hudson River Trading", "Capstone Investment Advisors", "G-Research", "Revolut", "Monzo", "Wise", "Deliveroo", "Palantir", "DeepMind", "Arm", "Cohere", "Graphcore", "Quantexa", "Darktrace", "Improbable", "Faculty", "Ocado Technology", "Bloomberg"];
  const roles = ["Data Scientist Intern - 2027", "Summer 2027 Risk Internship", "Machine Learning Engineer Intern", "Software Engineering Intern", "Quantitative Research Placement", "AI Engineer Intern", "Data Engineering Intern"];
  const statuses = ["applied", "applied", "Needs Review (Unsubmitted)", "Tailored & Ready", "applied", "Ready to Apply"];
  const rows = empty ? [] : Array.from({ length: 64 }, (_, i) => ({
    company: companies[i % companies.length], title: roles[(i * 3) % roles.length], status: statuses[i % statuses.length],
    ats: (62 + ((i * 7) % 35)) + "%", platform: i % 4 ? "LinkedIn" : "Greenhouse", url: "https://example.com/job/" + i, synced: i % 5 !== 0,
  }));
  const script = [
    "[Scanner] Starting scheduled unified scan...", "Target roles: Machine Learning Engineer Intern, Data Science Intern", "Location: London, UK | Timeframe: 24h",
    "[1/26] Skipping existing: Data & Analytics Platformer @ Havas (84% ATS)",
    "[2/26] EXCELLENT MATCH (93% >= 80%): Summer 2027 Risk Internship @ Capstone Investment Advisors", "   Direct Apply mode: Using master resume (no tailoring needed)",
    "   Application verified & submitted successfully for Summer 2027 Risk Internship @ Capstone Investment Advisors",
    "[3/26] Skipping title without required keyword (intern, internship, placement): Quantitative Researcher @ Anson McCade",
    "[4/26] QUALIFIED MATCH (78% ATS): Intern, 6G Technology Research @ InterDigital", "   Tailoring 1-page LaTeX resume for keyword & skills alignment...",
    "   Submission verification failed for Intern, 6G Technology Research @ InterDigital: account creation was blocked",
    "[5/26] EXCELLENT MATCH (86% >= 80%): Data Science Internship @ targetjobs UK", "   Application verified & submitted successfully for Data Science Internship @ targetjobs UK",
    "Synced with your Supabase project: 3 new application(s) added.",
  ];
  let started = 0, lineIndex = 0, running = false;
  const state = {
    workspace: "/Users/akhil/Documents/Job Finder", version: "1.9.1", running: false, chrome_found: true,
    app_prefs: { primary_ai: "auto", headless: false },
    supabase: q.has("local") ? { configured: false, reachable: false } : { configured: true, reachable: true, host: "iileqpgzppssrsjdseia.supabase.co" },
    browser: { ready: !q.has("browser"), installing: false, error: "" },
    keys: q.has("fresh") ? { gemini: { set: false, hint: "" }, anthropic: { set: false, hint: "" }, openai: { set: false, hint: "" } }
                          : { gemini: { set: true, hint: "a3Kd" }, anthropic: { set: true, hint: "Qw9z" }, openai: { set: false, hint: "" } },
    prefs: { profile_exists: !q.has("fresh"), candidate_name: "Akhil Baja", roles: ["Machine Learning Engineer Intern", "Data Science Intern", "AI Engineer Intern"],
      location: "London, UK", timeframe: "24h", min_ats: 70, title_keywords: ["intern", "internship", "placement"], skip_portals: ["targetjobs", "workday"] },
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  window.pywebview = { api: {
    get_state: async () => { await wait(120); return { ...state, running }; },
    save_prefs: async () => ({ ok: true }), save_app_prefs: async () => ({ ok: true }), set_theme: async () => ({ ok: true }),
    check_update: async () => ({ ok: true, current: "1.9.1", latest: q.has("update") ? "1.10.0" : "1.9.1", newer: q.has("update"), url: "https://github.com" }),
    start_scan: async () => { running = true; started = Date.now(); lineIndex = 0; return { ok: true }; },
    stop_scan: async () => { running = false; return { ok: true }; },
    poll: async (offset) => {
      if (running) lineIndex = Math.min(script.length, Math.floor((Date.now() - started) / 1100));
      if (running && lineIndex >= script.length) running = false;
      const lines = script.slice(offset, lineIndex); const seen = script.slice(0, lineIndex).join("\n");
      const count = (re) => (seen.match(re) || []).length;
      return { lines, next: lineIndex, running, exit_code: running ? null : 0, title: "scan",
        counts: { found: 26, position: Math.min(26, count(/^\[\d+\//gm) + 0), submitted: count(/submitted successfully/g), needs_review: count(/verification failed/g), skipped: count(/Skipping/g) } };
    },
    get_results: async () => { await wait(350); return rows; },
    sync_now: async () => { await wait(900); return { ok: true, pushed: 3, already: rows.length }; },
    save_key: async () => ({ ok: true, keys: state.keys }), open_url: async () => ({ ok: true }), open_path: async () => ({ ok: true }),
    choose_workspace: async () => ({ ok: false }), choose_resume_and_build_profile: async () => ({ ok: false }),
    get_saved_answers: async () => ({ ok: true, items: savedAnswers.slice(), suggestions: ["Why do you want to work here?", "What are your salary expectations?", "What is your notice period or earliest start date?", "Where did you hear about this role?"], max_entries: 40, max_chars: 600 }),
    save_saved_answers: async (items) => { savedAnswers = items.filter((i) => i.question.trim() && i.answer.trim()); return { ok: true, saved: savedAnswers.length }; },
    schedule_status: async () => ({ ok: true, enabled: false }),
    drag_start: async () => { (window.__dragLog = window.__dragLog || []).push(["start"]); return { ok: true }; },
    drag_to: async (dx, dy) => { (window.__dragLog = window.__dragLog || []).push(["to", dx, dy]); return { ok: true }; },
    zoom_window: async () => { (window.__dragLog = window.__dragLog || []).push(["zoom"]); return { ok: true }; },
    ensure_browser: async () => ({ ok: true }),
  } };
  window.dispatchEvent(new Event("pywebviewready"));
})();
