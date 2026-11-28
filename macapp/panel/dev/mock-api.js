/* Stand-in for the Python side, for working on the window in a normal browser. Not shipped with the app.
   Open dev/index.html through a local web server (python3 -m http.server) from the panel folder. */
(function () {
  const q = new URLSearchParams(location.search);
  const empty = q.has("empty");
  let savedAnswers = [{ question: "Earliest start date", answer: "Available to start immediately." }];
  const companies = ["Hudson River Trading", "Capstone Investment Advisors", "G-Research", "Revolut", "Monzo", "Wise", "Deliveroo", "Palantir", "DeepMind", "Arm", "Cohere", "Graphcore", "Quantexa", "Darktrace", "Improbable", "Faculty", "Ocado Technology", "Bloomberg"];
  const roles = ["Data Scientist Intern - 2027", "Summer 2027 Risk Internship", "Machine Learning Engineer Intern", "Software Engineering Intern", "Quantitative Research Placement", "AI Engineer Intern", "Data Engineering Intern"];
  const statuses = ["applied", "applied", "Needs Review (Unsubmitted)", "Tailored & Ready", "applied", "Ready to Apply"];

  const rows = empty ? [] : Array.from({ length: 18 }, (_, i) => ({
    id: String(100 + i),
    company: companies[i % companies.length],
    title: roles[(i * 3) % roles.length],
    status: statuses[i % statuses.length],
    ats: (68 + ((i * 7) % 29)) + "%",
    platform: i % 4 ? "LinkedIn" : "Greenhouse",
    url: "https://example.com/job/" + (100 + i),
    synced: i % 5 !== 0,
    grounding: i % 3 === 0 ? {
      answered_from_profile: 8 + (i % 4),
      no_data: i % 6 === 0 ? ["Security clearance eligibility"] : [],
      stopped: i % 6 === 0 ? ["Account creation required"] : [],
      ungrounded: [],
      verified: i % 6 !== 0,
    } : undefined,
    questions: i % 3 === 0 ? [
      { question: "Are you legally authorized to work in the UK?", answer: "Yes, authorised without restriction." },
      { question: "Earliest start date", answer: "Available to start immediately." },
    ] : [],
  }));

  const searches = empty ? [] : [
    { name: "ai-intern", topic: "applied AI", level: "intern", location: "London", jobs: 12, updated: "2026-11-27" },
    { name: "cyber-grad", topic: "cyber security", level: "graduate", location: "Manchester, UK", jobs: 19, updated: "2026-11-26" },
    { name: "ml-all", topic: "machine learning", level: "all", location: "London", jobs: 31, updated: "2026-11-25" },
  ];
  let currentSearch = searches.length ? searches[0].name : "";

  const mockJobs = empty ? [] : [
    { id: "12", role: "AI Engineer Intern", company: "Acme AI", level: "intern", years: "not stated", fit: 91, scored_by: "AI", match: "Core", closing: "2026-12-15", url: "https://example.com/jobs/12", approved: true },
    { id: "13", role: "Machine Learning Intern", company: "DeepMind", level: "intern", years: "not stated", fit: 88, scored_by: "Keyword", match: "Core", closing: "2026-12-20", url: "https://example.com/jobs/13", approved: true },
    { id: "14", role: "Applied Scientist Intern", company: "Cohere", level: "intern", years: "0-1", fit: 84, scored_by: "AI", match: "Core", closing: "2026-12-10", url: "https://example.com/jobs/14", approved: true },
    { id: "15", role: "Data Science Summer Intern", company: "Revolut", level: "intern", years: "not stated", fit: 79, scored_by: "Keyword", match: "Related", closing: "2027-01-05", url: "https://example.com/jobs/15", approved: true },
    { id: "16", role: "AI Safety Research Intern", company: "Faculty", level: "intern", years: "not stated", fit: 82, scored_by: "AI", match: "Core", closing: "2026-12-18", url: "https://example.com/jobs/16", approved: false },
    { id: "17", role: "Software Engineering Intern", company: "Monzo", level: "intern", years: "not stated", fit: 76, scored_by: "Keyword", match: "Related", closing: "2026-12-22", url: "https://example.com/jobs/17", approved: false },
    { id: "18", role: "Quantitative Research Intern", company: "G-Research", level: "intern", years: "not stated", fit: 74, scored_by: "AI", match: "Related", closing: "2026-12-30", url: "https://example.com/jobs/18", approved: false },
    { id: "19", role: "NLP Engineering Intern", company: "Quantexa", level: "intern", years: "0-1", fit: 86, scored_by: "Keyword", match: "Core", closing: "2026-12-12", url: "https://example.com/jobs/19", approved: false },
    { id: "20", role: "Platform AI Intern", company: "Palantir", level: "intern", years: "not stated", fit: 71, scored_by: "AI", match: "Related", closing: "2027-01-10", url: "https://example.com/jobs/20", approved: false },
    { id: "21", role: "Computer Vision Intern", company: "Arm", level: "intern", years: "not stated", fit: 68, scored_by: "Keyword", match: "Related", closing: "2026-12-28", url: "https://example.com/jobs/21", approved: false },
    { id: "22", role: "LLM Evaluation Intern", company: "Graphcore", level: "intern", years: "not stated", fit: 80, scored_by: "AI", match: "Core", closing: "2026-12-19", url: "https://example.com/jobs/22", approved: false },
    { id: "23", role: "Research Engineer Intern", company: "Improbable", level: "intern", years: "not stated", fit: 65, scored_by: "Keyword", match: "Related", closing: "", url: "https://example.com/jobs/23", approved: false },
  ];

  const mockPacks = empty ? {} : {
    "12": { state: "signed_off", error: "" },
    "13": { state: "needs_signoff", error: "" },
    "14": { state: "needs_signoff", error: "" },
    "15": { state: "not_started", error: "" },
  };

  let mockConfirmed = [];
  const mockTex = String.raw`\documentclass[11pt]{resume}
\usepackage{times}
\name{AKHIL BAJA}
\begin{document}
\begin{rSection}{Professional Summary}
Applied AI/ML engineer with 3+ years of experience building production GenAI and ML systems at Qualcomm and Axis Bank. Built LLM and data systems used by 1,000+ engineers and 1,300+ bank employees.
\end{rSection}
\end{document}`;
  const mockDocs = {
    "12": {
      cv_pdf: "/Users/akhil/Documents/Job Finder/applications/ai-intern/0012_acme-ai_ai-engineer-intern/cv.pdf",
      cover_letter: "Dear Acme AI Hiring Team,\n\nI am writing to apply for the AI Engineer Intern role. In my recent projects, I built production RAG pipelines and evaluated LLM tool-calling accuracy across benchmark suites.\n\nI would welcome the opportunity to contribute to your applied AI team this summer.\n\nSincerely,\nAkhil Baja",
      review_md: "# Review Checklist — AI Engineer Intern @ Acme AI\n\n- [x] Tailored CV fits on 1 page (ATS-readable PDF)\n- [x] All metrics match candidate_profile.json\n- [x] Cover letter requested by posting: generated and fact-checked\n\n## Changes made\n- Reordered project bullets to highlight LLM evaluation and Python tooling\n- Kept all dates, titles, and degrees untouched",
      fit: "Overall Fit: 91% (Core)\n\nRequirements:\n- [MET] Python & PyTorch experience — evidenced by ML research project\n- [MET] LLM evaluation / RAG — evidenced by capstone pipeline\n- [PARTIAL] Production cloud deployment — Docker & FastAPI experience",
    },
    "13": {
      cv_pdf: "/Users/akhil/Documents/Job Finder/applications/ai-intern/0013_deepmind_ml-intern/cv.pdf",
      cover_letter: "",
      review_md: "# Review Checklist — Machine Learning Intern @ DeepMind\n\n- [ ] Verify cv.pdf layout and bullet order\n- [x] No cover letter requested by posting\n- [x] Zero unverified claims\n\n## Warnings\n- Posting closes 2026-12-20.",
      fit: "Overall Fit: 88% (Core)\n\nRequirements:\n- [MET] Strong ML fundamentals & Python\n- [MET] Research experimentation & benchmarking\n- [NOT MET] Published NeurIPS/ICML paper (nice-to-have)",
    },
    "14": {
      cv_pdf: "/Users/akhil/Documents/Job Finder/applications/ai-intern/0014_cohere_applied-scientist-intern/cv.pdf",
      cover_letter: "Dear Cohere Team,\n\nI am excited to apply for the Applied Scientist Intern position. My work on retrieval-augmented generation and prompt evaluation aligns closely with Cohere's enterprise AI focus.\n\nThank you for your consideration.\n\nBest regards,\nAkhil Baja",
      review_md: "# Review Checklist — Applied Scientist Intern @ Cohere\n\n- [ ] Check cover letter opening\n- [x] Tailored CV verified against profile\n\n## Keyword Coverage\nBefore: 64% -> After: 84%",
      fit: "Overall Fit: 84% (Core)\n\nRequirements:\n- [MET] NLP / Transformer architectures\n- [MET] Evaluation harnesses in Python",
    },
  };

  let capUsed = empty ? 0 : 3;
  let capLimit = 20;

  const scanScript = [
    "[Scanner] Starting search: applied AI (intern) in London...",
    "Sources: LinkedIn, Greenhouse, Lever, Ashby (board index: 8,412 boards)",
    "[1/12] AI Engineer Intern @ Acme AI — 91% Core",
    "[2/12] Machine Learning Intern @ DeepMind — 88% Core",
    "[3/12] Applied Scientist Intern @ Cohere — 84% Core",
    "[4/12] NLP Engineering Intern @ Quantexa — 86% Core",
    "Saved 12 jobs to applications_tracker/searches/ai-intern/scanned_jobs.xlsx",
  ];
  const practiceScript = [
    "[Dry-run] Searching applied AI (intern) in London (no files written)...",
    "Found per source: LinkedIn (42), Greenhouse (31), Ashby (18), Indeed (24)",
    "Removed per stage: Already in tracker (9), Wrong level / senior (54), Off-topic title (40)",
    "Dropped titles: Senior AI Architect (wrong level), Security Guard (off-topic), Lead ML Engineer (wrong level)",
    "Funnel complete: 115 found -> 12 would be saved.",
  ];
  const prepareScript = [
    "[Prepare] Building application packs for approved jobs...",
    "Tailoring CV for Data Science Summer Intern @ Revolut...",
    "Checking profile evidence and rendering 1-page cv.pdf...",
    "Generating REVIEW.md and fit_analysis.md...",
    "Pack ready: Data Science Summer Intern @ Revolut (needs sign-off).",
  ];
  const applyPreviewScript = [
    "[Apply] Preview mode: reading signed-off jobs from approved_jobs.xlsx...",
    "[1/1] AI Engineer Intern @ Acme AI (Greenhouse)",
    "   Uploading tailored cv.pdf from pack 0012...",
    "   Pasting reviewed cover_letter.txt verbatim...",
    "   Answered 9 fields from profile (0 ungrounded).",
    "   Preview complete: stopped before Submit.",
  ];
  const applySubmitScript = [
    "[Apply] Submit mode: reading signed-off jobs from approved_jobs.xlsx...",
    "[1/1] AI Engineer Intern @ Acme AI (Greenhouse)",
    "   Uploading tailored cv.pdf from pack 0012...",
    "   Pasting reviewed cover_letter.txt verbatim...",
    "   Answered 9 fields from profile (0 ungrounded).",
    "   Application verified & submitted successfully for AI Engineer Intern @ Acme AI",
  ];

  let activeTask = null; // "scan" | "practice" | "prepare" | "apply"
  let activeScript = scanScript;
  let started = 0, lineIndex = 0, running = false;
  let applyTargets = [];

  const state = {
    workspace: "/Users/akhil/Documents/Job Finder", version: "1.9.1", running: false, chrome_found: true,
    app_prefs: { primary_ai: "auto", headless: false, dock_browser: false, tour_done: true },
    cloud: { configured: true, connected: true, email: "me@example.com", kind: "google" },
    browser: { ready: !q.has("browser"), installing: false, error: "" },
    boards: { ready: !q.has("fresh"), updated: q.has("fresh") ? "" : "2026-11-27" },
    keys: q.has("fresh") ? { gemini: { set: false, hint: "" }, anthropic: { set: false, hint: "" }, openai: { set: false, hint: "" } }
                          : { gemini: { set: true, hint: "a3Kd" }, anthropic: { set: true, hint: "Qw9z" }, openai: { set: false, hint: "" } },
    portal_password: { set: !q.has("fresh"), hint: q.has("fresh") ? "" : "x9Kp" },
    prefs: { profile_exists: !q.has("fresh"), candidate_name: "Akhil Baja", roles: ["Machine Learning Engineer Intern", "Data Science Intern", "AI Engineer Intern"],
      location: "London, UK", timeframe: "1m", min_ats: 70, title_keywords: ["intern", "internship", "placement"], skip_portals: ["targetjobs", "workday"] },
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function computeNextStep() {
    const scanned = mockJobs.length;
    const approvedJobs = mockJobs.filter((j) => j.approved);
    const approved = approvedJobs.length;
    let packsReady = 0, needsSignoff = 0, readyToApply = 0, notStarted = 0;
    approvedJobs.forEach((j) => {
      const p = mockPacks[j.id] || { state: "not_started" };
      if (p.state === "not_started" || p.state === "preparing") notStarted++;
      else if (p.state === "ready" || p.state === "needs_signoff") { packsReady++; needsSignoff++; }
      else if (p.state === "signed_off") { packsReady++; readyToApply++; }
    });
    const applied = rows.filter((r) => /appl|submitted/i.test(r.status)).length;
    const counts = { scanned, approved, packs_ready: packsReady, needs_signoff: needsSignoff, ready_to_apply: readyToApply, applied };

    if (!scanned) return { ok: true, stage: "search", title: "No jobs scanned yet", button: "Run a search", goto: "search", counts };
    if (!approved) return { ok: true, stage: "review", title: scanned + " jobs found", button: "Review them", goto: "review", counts };
    if (notStarted > 0 && needsSignoff === 0 && readyToApply === 0) return { ok: true, stage: "packs", title: notStarted + " approved", button: "Prepare packs", goto: "packs", counts };
    if (needsSignoff > 0) return { ok: true, stage: "documents", title: needsSignoff + (needsSignoff === 1 ? " pack needs sign-off" : " packs need sign-off"), button: "Review docs", goto: "documents", counts };
    if (readyToApply > 0) return { ok: true, stage: "apply", title: readyToApply + " ready to apply", button: "Apply", goto: "apply", counts };
    return { ok: true, stage: "done", title: "All caught up (" + applied + " applied)", button: "New search", goto: "search", counts };
  }

  window.pywebview = { api: {
    get_state: async () => {
      await wait(80);
      const waiting = window.__signin === "waiting";
      const out = q.has("signedout") && window.__signin !== "done";
      const session = out ? { signed_in: false, reason: q.has("offline") ? "offline" : q.has("expired") ? "expired" : "none", signing_in: waiting, error: "" } : { signed_in: true, reason: "", email: "me@example.com" };
      return { ...state, running, session };
    },
    next_step: async () => computeNextStep(),
    list_searches: async () => ({ ok: true, current: currentSearch, searches: searches.slice() }),
    list_jobs: async (search) => {
      await wait(100);
      if (search && searches.length && search !== currentSearch) {
        currentSearch = search;
      }
      return { ok: true, jobs: mockJobs.map((j) => ({ ...j })) };
    },
    approve_jobs: async (payload) => {
      let count = 0;
      if (payload && Array.isArray(payload.ids)) {
        mockJobs.forEach((j) => {
          if (payload.ids.includes(j.id) && !j.approved) {
            j.approved = true; count++;
            if (!mockPacks[j.id]) mockPacks[j.id] = { state: "not_started", error: "" };
          }
        });
      } else if (payload && typeof payload.min_ats === "number") {
        mockJobs.forEach((j) => {
          if (j.fit >= payload.min_ats && !j.approved) {
            j.approved = true; count++;
            if (!mockPacks[j.id]) mockPacks[j.id] = { state: "not_started", error: "" };
          }
        });
      }
      return { ok: true, approved: count };
    },
    revoke_jobs: async (payload) => {
      let count = 0;
      if (payload && Array.isArray(payload.ids)) {
        mockJobs.forEach((j) => {
          if (payload.ids.includes(j.id) && j.approved) { j.approved = false; count++; }
        });
      }
      return { ok: true, revoked: count };
    },
    list_packs: async () => {
      await wait(80);
      const packs = mockJobs.filter((j) => j.approved).map((j, idx) => {
        const p = mockPacks[j.id] || { state: "not_started", error: "" };
        return { id: j.id, role: j.role, company: j.company, state: p.state, cv_edited: Boolean(p.cv_edited || idx === 0), error: p.error || "" };
      });
      return { ok: true, packs };
    },
    prepare_packs: async (payload) => {
      const ids = payload && Array.isArray(payload.ids) && payload.ids.length
        ? payload.ids
        : mockJobs.filter((j) => j.approved && (!mockPacks[j.id] || mockPacks[j.id].state === "not_started")).map((j) => j.id);
      ids.forEach((id) => { mockPacks[id] = { state: "preparing", error: "" }; });
      activeTask = "prepare";
      activeScript = prepareScript;
      running = true; started = Date.now(); lineIndex = 0;
      setTimeout(() => {
        ids.forEach((id) => {
          mockPacks[id] = { state: "needs_signoff", error: "" };
          if (!mockDocs[id]) {
            const job = mockJobs.find((j) => j.id === id) || { role: "Role", company: "Company" };
            mockDocs[id] = {
              cv_pdf: "/Users/akhil/Documents/Job Finder/applications/ai-intern/" + id + "/cv.pdf",
              cover_letter: "",
              review_md: "# Review Checklist — " + job.role + " @ " + job.company + "\n\n- [ ] Check tailored cv.pdf\n- [x] All bullets grounded in candidate_profile.json",
              fit: "Overall Fit: " + (job.fit || 80) + "% (" + (job.match || "Core") + ")\n\nRequirements:\n- [MET] Core technical skills",
            };
          }
        });
      }, 2800);
      return { ok: true };
    },
    check_resume_gaps: async () => ({ ok: true, has_resume: true, numbers: q.has("gaps") ? ["8.04", "100+"] : [], names: q.has("gaps") ? ["PostgreSQL", "PySpark"] : [] }),
    list_confirmed_experience: async () => ({ ok: true, items: mockConfirmed.slice() }),
    confirm_experience: async (skill, evidence) => {
      await wait(150);
      if (String(evidence || "").trim().length < 20) return { ok: false, error: "Say in a sentence where you used it (at least 20 characters). It is kept as your own evidence." };
      mockConfirmed = mockConfirmed.filter((i) => i.skill.toLowerCase() !== String(skill).toLowerCase()).concat([{ skill, evidence, group: "" }]);
      return { ok: true, items: mockConfirmed.slice() };
    },
    remove_confirmed_experience: async (skill) => { mockConfirmed = mockConfirmed.filter((i) => i.skill !== skill); return { ok: true, items: mockConfirmed.slice() }; },
    get_pack_latex: async (id) => { await wait(120); return { ok: true, tex: mockTex, source: "generated", available: true, pages: [], in_use: false }; },
    reset_pack_latex: async (id) => { await wait(120); return { ok: true, tex: mockTex, source: "generated", available: true, pages: [], in_use: false }; },
    compile_pack_latex: async (id, tex) => {
      await wait(900);
      if (!/\\begin\{document\}/.test(tex)) return { ok: false, error: "That does not look like a LaTeX CV (\\begin{document} is missing)." };
      if (/oops/.test(tex)) return { ok: false, error: "error: Undefined control sequence | l.42 \\oops" };
      const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='760' height='980'><rect width='760' height='980' fill='#fff'/><text x='380' y='60' font-family='Times' font-size='34' font-weight='bold' text-anchor='middle'>AKHIL BAJA</text><g font-family='Times' font-size='13' fill='#222'><text x='40' y='110'>PROFESSIONAL SUMMARY</text><text x='40' y='134'>Applied AI/ML engineer with 3+ years of experience building production GenAI and ML systems...</text><text x='40' y='190'>EDUCATION</text><text x='40' y='214'>Imperial College London - MSc in Artificial Intelligence Applications and Innovation</text><text x='40' y='234'>Aug 2019 - May 2023 | CPI: 8.04 / 10.0</text><text x='40' y='290'>WORK EXPERIENCE</text><text x='40' y='314'>Qualcomm | Software Engineer (GenAI / Systems) | Dec 2024 - Aug 2026</text></g></svg>";
      const edited = /1,300\+ bank employees/.test(tex) ? [] : ["Not found in your resume or profile: unsupported number '2,500'"];
      return { ok: true, pages: ["data:image/svg+xml;utf8," + encodeURIComponent(svg)], page_count: 1, fill: 0.97, warnings: edited, tightened: false };
    },
    use_pack_latex_pdf: async (id) => { await wait(150); return { ok: true }; },
    use_standard_cv_pdf: async (id) => { await wait(150); return { ok: true }; },
    import_latex_template: async () => ({ ok: true, path: "/tmp/custom_resume_template.tex" }),
    clear_latex_template: async () => ({ ok: true }),
    pack_documents: async (id) => {
      await wait(80);
      const d = mockDocs[id];
      if (!d) return { ok: false, error: "Pack documents not prepared yet." };
      return {
        ok: true,
        cover_letter_status: d.cover_letter ? "ready" : "not_asked",
        cover_letter_message: d.cover_letter ? "Cover letter ready." : "Cover letter not requested for this posting.",
        tailoring_status: "tailored",
        tailoring_message: "CV tailored and verified.",
        scores: { master_score: 74, tailored_score: 86, coverage_before: "2/5", coverage_after: "5/5" },
        evidence_panel: {
          keywords_found: ["Python", "LLMs (Large Language Models)", "LangGraph (agentic workflows)"],
          keywords_missing: ["Swift"],
          requirements_gap: ["5+ years (dates show 3 years)"],
          knockouts: [],
          alias_matches: ["LLMs → Large Language Models", "LangGraph → agentic workflows"],
          entailment_results: ["All 2 rewrites entailed"],
        },
        changes: [
          {
            id: "chg_0",
            section: "experience",
            role_index: 0,
            bullet_index: 0,
            original: "Built multi-agent validation pipeline in Python.",
            new_text: "Built 7 LangGraph agentic workflows with 4 validation gates in Python.",
            reason: "Surface LangGraph evidence for agentic workflows",
            reverted: false,
          },
        ],
        unresolved_flags: [],
        signoff_allowed: true,
        signoff_blocked_reason: "",
        ...d,
      };
    },
    revert_pack_change: async () => ({ ok: true }),
    save_pack_cv: async () => ({ ok: true }),
    open_pack_file: async () => ({ ok: true }),
    signoff_pack: async (id) => {
      if (mockPacks[id]) mockPacks[id].state = "signed_off";
      return { ok: true };
    },
    list_ready: async () => {
      await wait(80);
      const ready = mockJobs.filter((j) => j.approved && mockPacks[j.id] && mockPacks[j.id].state === "signed_off").map((j) => ({ ...j }));
      return { ok: true, jobs: ready, cap: { used: capUsed, limit: capLimit } };
    },
    start_apply: async (options) => {
      activeTask = "apply";
      activeScript = options && options.mode === "submit" ? applySubmitScript : applyPreviewScript;
      running = true; started = Date.now(); lineIndex = 0;
      const ready = mockJobs.filter((j) => j.approved && mockPacks[j.id] && mockPacks[j.id].state === "signed_off");
      applyTargets = ready.slice(0, (options && options.limit) || 5);
      if (options && options.mode === "submit") {
        capUsed = Math.min(capLimit, capUsed + applyTargets.length);
      }
      return { ok: true };
    },
    save_prefs: async () => ({ ok: true }),
    save_app_prefs: async (vals) => { if (vals && vals.daily_cap) capLimit = Number(vals.daily_cap) || 20; return { ok: true }; }, set_theme: async () => ({ ok: true }),
    check_update: async () => ({ ok: true, current: "1.9.1", latest: q.has("update") ? "1.10.0" : "1.9.1", newer: q.has("update"), url: "https://github.com" }),
    start_scan: async (options) => {
      activeTask = options && options.mode === "practice" ? "practice" : "scan";
      activeScript = activeTask === "practice" ? practiceScript : scanScript;
      running = true; started = Date.now(); lineIndex = 0;
      return { ok: true };
    },
    stop_scan: async () => { running = false; return { ok: true }; },
    poll: async (offset) => {
      if (running) lineIndex = Math.min(activeScript.length, Math.floor((Date.now() - started) / 700));
      if (running && lineIndex >= activeScript.length) running = false;
      const lines = activeScript.slice(offset, lineIndex);
      const seen = activeScript.slice(0, lineIndex).join("\n");
      const count = (re) => (seen.match(re) || []).length;
      const doneApply = !running && activeTask === "apply";
      return {
        lines, next: lineIndex, running, exit_code: running ? null : 0, title: activeTask || "scan",
        counts: {
          found: activeTask === "prepare" ? 1 : activeTask === "apply" ? applyTargets.length || 1 : 12,
          position: Math.min(12, count(/^\[\d+\//gm) + (activeTask === "prepare" && !running ? 1 : 0)),
          submitted: count(/submitted successfully/g),
          needs_review: count(/verification failed/g),
          skipped: count(/Skipping|Removed/g),
        },
        applied_rows: doneApply ? applyTargets.map((j) => ({
          id: j.id, role: j.role, company: j.company, status: "applied",
          grounding: { answered_from_profile: 9, no_data: [], stopped: [], ungrounded: [], verified: true },
          questions: [
            { question: "Work authorization", answer: "Authorised to work in the UK without restriction" },
            { question: "Earliest start date", answer: "Available to start immediately." },
          ],
        })) : undefined,
      };
    },
    live_view: async () => {
      if (!running || activeTask === "prepare") return { ok: false };
      const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='960' height='540'><rect width='960' height='540' fill='#f6f6f4'/><rect x='60' y='50' width='840' height='60' fill='#fff' stroke='#ddd'/><text x='80' y='90' font-family='sans-serif' font-size='22' fill='#333'>Apply for AI Engineer Intern</text><rect x='60' y='140' width='400' height='44' fill='#fff' stroke='#bbb'/><text x='72' y='168' font-family='sans-serif' font-size='16' fill='#555'>Akhil Baja</text><rect x='60' y='204' width='400' height='44' fill='#fff' stroke='#bbb'/><text x='72' y='232' font-family='sans-serif' font-size='16' fill='#555'>me@example.com</text></svg>";
      return { ok: true, url: "https://jobs.example.com/apply/4821", title: "Apply | Acme AI", image: "data:image/svg+xml;utf8," + encodeURIComponent(svg) };
    },
    get_results: async () => { await wait(200); return rows; },
    set_status: async (url, status) => {
      const r = rows.find((x) => x.url === url);
      if (r) r.status = status;
      return { ok: true };
    },
    review_in_chrome: async () => ({ ok: true }),
    review_info: async () => ({ ok: true, reason: "Account creation or CAPTCHA stopped the agent before Submit.", screenshot: false }),
    open_screenshot: async () => ({ ok: true }),
    sync_now: async () => { await wait(600); return { ok: true, pushed: 3, already: rows.length }; },
    sync_cloud_now: async () => { await wait(600); return { ok: true, pushed: 2, already: rows.length }; },
    disconnect_sync: async () => { state.cloud.connected = false; return { ok: true }; },
    delete_account: async (confirmEmail) => {
      if (String(confirmEmail || "").trim().toLowerCase() !== "me@example.com") return { ok: false, error: "The email does not match this account" };
      state.cloud.connected = false; window.__signin = "idle";
      return { ok: true };
    },
    save_mailbox: async (user) => { state.mailbox = { configured: true, user: user || "me@example.com" }; return { ok: true }; },
    disconnect_mailbox: async () => { state.mailbox = { configured: false }; return { ok: true }; },
    check_replies_now: async () => ({ ok: true, updated: 0, checked: 14 }),
    open_signin: async () => ({ ok: true }),
    problem_report: async () => ({ ok: true, text: "Job Finder 1.9.1 mock report" }),
    choose_profile_and_import: async () => ({ ok: true, name: "Akhil Baja" }),
    save_key: async () => ({ ok: true, keys: state.keys }),
    save_portal_password: async (v) => { state.portal_password = { set: Boolean(v), hint: v && v.length > 8 ? v.slice(-4) : "" }; return { ok: true, portal_password: state.portal_password }; }, open_url: async () => ({ ok: true }), open_path: async () => ({ ok: true }),
    choose_workspace: async () => ({ ok: false }), choose_resume_and_build_profile: async () => ({ ok: false }),
    get_saved_answers: async () => ({ ok: true, items: savedAnswers.slice(), suggestions: ["Why do you want to work here?", "What are your salary expectations?", "What is your notice period or earliest start date?", "Where did you hear about this role?"], max_entries: 40, max_chars: 600 }),
    save_saved_answers: async (items) => { savedAnswers = items.filter((i) => i.question.trim() && i.answer.trim()); return { ok: true, saved: savedAnswers.length }; },
    schedule_status: async () => ({ ok: true, enabled: false }),
    set_schedule: async () => ({ ok: true }),
    drag_start: async () => { (window.__dragLog = window.__dragLog || []).push(["start"]); return { ok: true }; },
    drag_to: async (dx, dy) => { (window.__dragLog = window.__dragLog || []).push(["to", dx, dy]); return { ok: true }; },
    zoom_window: async () => { (window.__dragLog = window.__dragLog || []).push(["zoom"]); return { ok: true }; },
    google_sign_in: async () => { window.__signin = "waiting"; setTimeout(() => { window.__signin = "done"; }, 2500); return { ok: true }; },
    google_sign_in_status: async () => ({ ok: true, state: window.__signin || "idle", error: "", email: "me@example.com" }),
    cancel_google_sign_in: async () => { window.__signin = "idle"; return { ok: true }; },
    session_check: async () => ({ ok: true, signed_in: true }),
    get_about_you: async () => ({ ok: true, exists: true, unanswered: ["work_authorization", "requires_sponsorship", "notice_period", "seniority"], fields: [
      { key: "work_authorization", section: "Work rights", label: "Where can you work?", kind: "choice", required: true, options: ["Authorised to work in the UK without restriction", "I need a visa to work (sponsorship)"], help: "Almost every form asks. Pick one, or type your own.", value: null },
      { key: "requires_sponsorship", section: "Work rights", label: "Will you need visa sponsorship, now or later?", kind: "bool", required: true, help: "Answered Yes or No on forms.", value: null },
      { key: "notice_period", section: "Availability and pay", label: "When can you start?", kind: "choice", required: true, options: ["Immediately", "2 weeks", "1 month"], value: null },
      { key: "salary_expectations", section: "Availability and pay", label: "Salary expectation", kind: "text", required: false, placeholder: "e.g. 35,000 to 40,000 GBP a year", value: null },
      { key: "seniority", section: "What you are looking for", label: "Which levels?", kind: "multi", required: true, options: ["Intern", "Junior", "Mid", "Senior", "Staff", "Lead", "Manager"], value: [] },
      { key: "gender", section: "Optional: equal-opportunity forms", label: "Gender", kind: "choice", required: false, options: ["Prefer not to say", "Female", "Male", "Non-binary"], default: "Prefer not to say", value: null },
      { key: "disability_status", section: "Optional: equal-opportunity forms", label: "Disability", kind: "choice", required: false, options: ["Prefer not to say", "Yes", "No"], default: "Prefer not to say", value: null } ] }),
    save_about_you: async (answers) => { window.__aboutSaved = answers; return { ok: true, unanswered: [] }; },
    ensure_browser: async () => ({ ok: true }),
    save_pack_cv: async () => ({ ok: true }),
    open_pack_folder: async () => ({ ok: true }),
    refresh_boards: async () => { activeTask = "scan"; activeScript = ["[Boards] Refreshing Greenhouse/Lever/Ashby index...", "[Boards] Indexed 8,412 company boards."]; running = true; started = Date.now(); lineIndex = 0; return { ok: true }; },
  } };
  window.dispatchEvent(new Event("pywebviewready"));
})();
