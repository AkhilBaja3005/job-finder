# CV pipeline audit: what the app really runs

Checked by searching for each module's use outside tests (after PRs 166 to 169). "Wired" means the pack builder or the Api calls it on every run.

| Module | What it holds | Status |
|---|---|---|
| `cv_master` | structured master, skill groups from the resume, evidence, confirmed experience, resume gaps | **Wired** (`build_pack`, Api) |
| `cv_tailor` | the model's plan, checks, gate, plan cache | **Wired** |
| `cv_verifier` | fact checks (numbers, names, tools, links), prompt-injection sanitizer, strength escalation | **Wired** (through `cv_tailor`) |
| `cv_model_runner` | provider and model choice, call, record of what ran | **Wired**. The offline (no model) tailor, repair loop and backoff in it are **not used** |
| `jd_analyzer` | job sections, weighted requirements, seniority, knockouts | **Wired** (evidence panel, gap notes). Not used to choose bullets |
| `cv_latex`, `pdf_preview` | LaTeX CV, compile, preview, page fill | **Wired** |
| `cv_edge_guards` | pack lock, not-a-fit check | **Wired in this PR** (lock with stale-lock cleanup; not-a-fit as a warning). Dedup key and legacy-pack classifier: not used |
| `cv_selector` | bullet scoring, page budget, section order, education/skill organizing | **Not wired** into real packs. Only the offline tailor and the golden evaluation call it. Selection today is done by the model's plan |
| `cv_writer` | rewrite number/tool multiset check, title honesty, style consistency, link validation, never-say lists | **Not wired.** Equivalent number and tool checks exist in `cv_verifier`; title honesty, style linting, link validation and never-say lists have no effect |
| `cv_renderer_ats` | ATS HTML, region page rules, font floor, PDF metadata, safe file names | **Not wired.** Its parse check expected its own HTML; this PR adds an ATS check that reads the real PDF text instead |
| `cv_eval` | golden set of 20 one-line jobs, baseline comparison, outcome log | **Not wired.** Its jobs are invented one-liners; the real-job runs in `scratchpad` replaced it for now |

## What this means
- The safety that matters (no invented facts, never worse than master, fail safe) runs on every pack.
- The "smart" selection (weighted must-haves, role archetype, section order, fill the page by score) does **not** run; the AI's plan decides, and the page is filled by the CV's own content.
- Not wired and worth wiring next: `cv_writer` title honesty and never-say lists; `cv_selector` scoring as a tie-break and as a check on the model's plan.
