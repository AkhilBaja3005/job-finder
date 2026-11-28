"""
application_pack.py - one folder per approved job, holding everything to review before applying.

    applications/0007_acme_applied-ai-intern/
        REVIEW.md              what to check, in order
        job.md                 the job: link, closing date, scores, why it fits
        job_description.txt    the full posting text, saved so it can't vanish
        fit_analysis.md        each requirement: met / partial / not met, with your evidence
        cv.pdf                 the tailored CV that will be UPLOADED when you apply
        cv.json / cv.html      the editable source of cv.pdf
        cv_changes.md          exactly what was changed from your profile, and why
        cover_letter.txt       only if the job asks for one (or you forced it); pasted VERBATIM when applying
        cover_letter.pdf       the same letter as a file, for forms that want an upload
        cover_letter_notes.md  validator warnings, gaps, alternative opening lines
        apply_log.md           added by `apply`: what happened, when, screenshots
        manifest.json          machine-readable summary

Nothing is submitted until you set "Docs OK = Yes" for the job (`./jf review --ok <ID>`). Edit any file you like:
`cv.json` / `cover_letter.txt` edits are kept, and `./jf prepare --render-only --ids <ID>` rebuilds the PDFs from them.
"""

import asyncio
import copy
import html as _html
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from . import cv_master, cv_model_runner, cv_tailor, fit_scorer, jd_analyzer

_COVER_LETTER_CUES = re.compile(r"cover[\s-]*letter|covering[\s-]*letter|letter of (?:motivation|interest)|motivation letter|personal statement",
                                re.I)
COVER_MODES = ("auto", "always", "never")


@dataclass
class PackResult:
    folder: str
    status: str                         # "Ready for review" | "Needs attention"
    cv_tailored: bool
    cv_pdf: Optional[str]
    cover_letter: str                   # "Yes" | "No" | "Failed"
    warnings: List[str] = field(default_factory=list)


# ─── paths ────────────────────────────────────────────────────────────────────
def applications_dir() -> str:
    env = os.getenv("JOB_FINDER_APPLICATIONS_DIR")
    if env and env.strip():
        return os.path.abspath(os.path.expanduser(env.strip()))
    try:
        from config.constants import resolve_workspace_root
    except ImportError:
        from backend.config.constants import resolve_workspace_root
    return os.path.join(resolve_workspace_root(), "applications")


def slug(text: Any, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return (s[:limit].strip("-")) or "job"


def pack_folder_for(row: Dict[str, Any], base: Optional[str] = None) -> str:
    rid = int(row.get("ID") or 0)
    return os.path.join(base or applications_dir(), f"{rid:04d}_{slug(row.get('Company'), 28)}_{slug(row.get('Job Role'), 44)}")


def needs_cover_letter(jd_text: str, mode: str = "auto") -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(_COVER_LETTER_CUES.search(jd_text or ""))


# ─── rendering ────────────────────────────────────────────────────────────────
def _esc(v: Any) -> str:
    return _html.escape(str(v or ""), quote=False)


def render_cv_html(cv: Dict[str, Any]) -> str:
    """CV dict -> HTML (single column, text-based: ATS parsers read it). All values are HTML-escaped."""
    try:
        from .html_resume_renderer import render_html_resume
    except ImportError:  # pragma: no cover
        from html_resume_renderer import render_html_resume
    c = copy.deepcopy(cv)
    c["name"], c["email"], c["phone"] = _esc(c.get("name")), _esc(c.get("email")), _esc(c.get("phone"))
    c["links"] = [_html.escape(str(l), quote=True) for l in c.get("links", [])]
    c["summary"] = _esc(c.get("summary"))
    c["skills"] = [_esc(s) for s in c.get("skills", [])]
    if c.get("skill_groups"):
        c["skill_groups"] = {_esc(g): [_esc(x) for x in items] for g, items in c["skill_groups"].items()}
    for e in c.get("experience", []):
        for k in ("company", "role", "technologies", "start_date", "end_date"):
            e[k] = _esc(e.get(k))
        e["description"] = [_esc(b) for b in e.get("description", [])]
    for e in c.get("education", []):
        for k in ("institution", "degree", "field_of_study", "start_date", "graduation_date", "location", "grade"):
            e[k] = _esc(e.get(k))
        e["highlights"] = [_esc(h) for h in e.get("highlights", [])]
    for p in c.get("projects", []):
        tech = f" ({', '.join(p.get('technologies') or [])})" if p.get("technologies") else ""
        p["title"] = _esc(f"{p.get('title', '')}{tech}")
        p["url"] = _html.escape(str(p.get("url") or ""), quote=True)
        p["description"] = [_esc(d) for d in p.get("description", [])]
    rendered = render_html_resume(c)
    rendered = re.sub(r'<span class="edu-dates">\s*(?:–|&ndash;|-)?\s*</span>', '<span class="edu-dates"></span>', rendered)
    screen_css = "<style>@media screen{body{max-width:210mm;margin:16px auto;padding:11mm 14mm;box-shadow:0 1px 6px rgba(0,0,0,.12)}}</style>"
    return rendered.replace("</head>", screen_css + "</head>", 1) if "</head>" in rendered else rendered


def letter_html(name: str, company: str, text: str) -> str:
    paras = "".join(f"<p>{_esc(p).replace(chr(10), '<br>')}</p>" for p in re.split(r"\n\s*\n", text.strip()) if p.strip())
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Cover letter</title><style>"
            "@page{size:A4;margin:22mm 20mm}body{font-family:Helvetica,Arial,sans-serif;font-size:11pt;line-height:1.5;color:#111}"
            "p{margin:0 0 11pt}</style></head><body>" + paras + "</body></html>")


def _render_pdf(html_text: str, path: str) -> bool:
    """HTML -> PDF with headless Chromium (Playwright); no LaTeX needed."""
    try:
        from .html_resume_renderer import compile_html_to_pdf
    except ImportError:  # pragma: no cover
        from html_resume_renderer import compile_html_to_pdf
    try:
        return bool(asyncio.run(compile_html_to_pdf(html_text, path)))
    except RuntimeError:                      # already inside an event loop: run in a fresh one on a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return bool(ex.submit(lambda: asyncio.run(compile_html_to_pdf(html_text, path))).result())


# Progressively tighter styling, tried in order until the CV fits on ONE page (long profiles otherwise spill onto page 2).
_COMPACT_STEPS = (
    "",
    "body{font-size:9.4pt!important;line-height:1.28!important}.section-title{margin-top:7px!important}ul.bullets li{margin-bottom:1px!important}",
    "body{font-size:8.9pt!important;line-height:1.22!important}.section-title{margin-top:5px!important}ul.bullets li{margin-bottom:0!important}"
    ".job-item{margin-bottom:4px!important}",
    "body{font-size:8.4pt!important;line-height:1.17!important}.section-title{margin-top:4px!important;margin-bottom:2px!important}"
    "ul.bullets li{margin-bottom:0!important}.job-item{margin-bottom:3px!important}",
)


def render_cv_pdf(html_text: str, path: str) -> bool:
    """Render the CV, tightening the layout step by step until it is a single page. False only if rendering itself fails."""
    for css in _COMPACT_STEPS:
        page_html = html_text.replace("</style>", css + "</style>", 1) if css else html_text
        if not _render_pdf(page_html, path):
            return False
        pages = pdf_facts(path).get("pages")
        if pages in (None, 1):
            return True
    return True


def pdf_facts(path: str) -> Dict[str, Any]:
    """Pages and extractable text of a PDF (ATS parsers need a real text layer)."""
    try:
        from pypdf import PdfReader
        r = PdfReader(path)
        return {"pages": len(r.pages), "text_chars": sum(len(p.extract_text() or "") for p in r.pages)}
    except Exception:
        return {"pages": None, "text_chars": None}


def _generate_cover_letter(title: str, company: str, jd: str, candidate: dict) -> Dict[str, Any]:
    try:
        from .cover_letter_generator import generate_structured_cover_letter
    except ImportError:  # pragma: no cover
        from cover_letter_generator import generate_structured_cover_letter
    return generate_structured_cover_letter(title, company, jd, {"candidate": candidate})


# ─── files ────────────────────────────────────────────────────────────────────
def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _fit_md(candidate: dict, title: str, company: str, jd: str, level: Optional[str]) -> Optional[str]:
    try:
        res = fit_scorer.analyze_fit(candidate, title, company, jd, level)
    except Exception:
        return None
    sym = {"yes": "met", "partial": "partial", "no": "NOT met"}
    lines = [f"# Fit analysis: {title} at {company}", "",
             f"**Overall {res.overall}%** (skills {res.skills_score}, experience/education {res.experience_score}, role fit {res.role_fit})", "",
             res.summary, ""]
    if not res.eligible:
        lines += [f"**Hard requirement you do not meet:** {res.knockout_reason}", ""]
    lines += ["| Requirement | Need | Your profile | Evidence |", "|---|---|---|---|"]
    lines += [f"| {r['text']} | {r['importance']} | {sym.get(r['verdict'], r['verdict'])} | {(r['evidence'] or '-').replace('|', '/')} |"
              for r in res.requirements]
    return "\n".join(lines) + "\n"


def _job_md(row: Dict[str, Any]) -> str:
    def g(k, default="-"):
        v = row.get(k)
        return str(v.date() if hasattr(v, "date") else v) if v not in (None, "") else default
    return "\n".join([
        f"# {g('Job Role')} at {g('Company')}", "",
        f"- **Apply link:** {g('Job URL')}", f"- **Location:** {g('Location')}   **Source:** {g('Platform')}",
        f"- **Closing date:** {g('Closing Date', 'not stated')}   **Posted:** {g('Posted')}",
        f"- **Fit:** {g('ATS %')}%  (skills {g('Skills %')}, experience {g('Experience %')}, role fit {g('Role Fit %')}; scored by {g('Scored By')})",
        f"- **Why:** {g('Fit Summary')}", f"- **Missing:** {g('Missing Skills', 'none noted')}",
        f"- **Tracker ID:** {g('ID')}", ""])


def _review_md(row: Dict[str, Any], res: "PackResult", tailored: Optional[cv_tailor.TailoredCV], cl_status: str,
               cl_warnings: List[str], pdf: Dict[str, Any]) -> str:
    ID = row.get("ID")
    steps = ["1. Read `job.md` and `fit_analysis.md`: is this job still worth applying to?",
             "2. Open `cv.pdf` and `cv_changes.md`. Every line must be TRUE and something you are happy to be asked about.",
             "   Edit `cv.json` to change anything, then run:  `./jf prepare --render-only --ids %s`" % ID]
    n = 3
    if res.cover_letter == "Yes":
        steps += [f"{n}. Read `cover_letter.txt` (and `cover_letter_notes.md`). It is pasted into the form EXACTLY as written; "
                  "edit the .txt and re-run the render command above to refresh the PDF."]
        n += 1
    steps += [f"{n}. When you are happy:  `./jf review --ok {ID}`  (or set **Docs OK = Yes** in approved_jobs.xlsx).",
              f"{n + 1}. Then `./jf apply --dry-run --ids {ID}` to preview the form, and `./jf apply --submit --ids {ID}` to send."]
    flags = list(res.warnings)
    if pdf.get("pages") and pdf["pages"] > 1:
        flags.append(f"cv.pdf is {pdf['pages']} pages; one page reads best. Trim bullets in cv.json.")
    if pdf.get("text_chars") is not None and pdf["text_chars"] < 300:
        flags.append("cv.pdf has very little extractable text; an ATS may not read it.")
    return "\n".join([f"# Review before applying: {row.get('Job Role')} at {row.get('Company')}", "",
                      f"Status: **{res.status}**   |   CV: {'tailored to this job' if (tailored and tailored.tailored) else 'NOT tailored (your profile as-is)'}"
                      f"   |   Cover letter: {cl_status}", "",
                      "## Needs your attention" if flags else "## Nothing flagged", ""] + ([f"- {f}" for f in flags] + [""] if flags else [""]) +
                     ["## Steps", ""] + steps + [""])


def append_apply_log(folder: str, entry: str) -> None:
    if not folder or not os.path.isdir(folder):
        return
    path = os.path.join(folder, "apply_log.md")
    new = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new:
            f.write("# Apply log\n\n")
        f.write(f"- **{datetime.now().strftime('%Y-%m-%d %H:%M')}** {entry}\n")


def copy_into_pack(folder: str, src: Optional[str], name: Optional[str] = None) -> Optional[str]:
    """Copy a file (e.g. a review screenshot) into the pack folder; returns the new path."""
    if not folder or not src or not os.path.isfile(src):
        return None
    dest = os.path.join(folder, name or os.path.basename(src))
    shutil.copy2(src, dest)
    return dest


def read_cover_letter(folder: Optional[str]) -> Dict[str, Optional[str]]:
    """The reviewed cover letter of a pack: {"text": ..., "pdf": ...} (None where absent)."""
    out: Dict[str, Optional[str]] = {"text": None, "pdf": None}
    if not folder:
        return out
    txt, pdf = os.path.join(folder, "cover_letter.txt"), os.path.join(folder, "cover_letter.pdf")
    if os.path.isfile(txt):
        out["text"] = open(txt, encoding="utf-8").read().strip() or None
    if os.path.isfile(pdf):
        out["pdf"] = pdf
    return out


# ─── the builder ──────────────────────────────────────────────────────────────
def build_pack(row: Dict[str, Any], candidate: dict, jd_text: str, *, level: Optional[str] = None,
               cover_letter: str = "auto", redo: bool = False, render_only: bool = False,
               llm: Optional[Callable[[str], str]] = None, base_dir: Optional[str] = None) -> PackResult:
    """Create or refresh the pack for one approved job. Existing edits to cv.json / cover_letter.txt are kept unless `redo`."""
    if cover_letter not in COVER_MODES:
        raise ValueError(f"cover_letter must be one of {COVER_MODES}")
    title, company = str(row.get("Job Role") or "Role"), str(row.get("Company") or "Company")
    folder = pack_folder_for(row, base_dir)
    os.makedirs(folder, exist_ok=True)
    warnings: List[str] = []
    cv_path = os.path.join(folder, "cv.json")
    jd_text = (jd_text or "").strip()

    if render_only and not os.path.isfile(cv_path):
        raise FileNotFoundError(f"No cv.json in {folder}: run `./jf prepare --ids {row.get('ID')}` first.")

    # job + description
    _write(os.path.join(folder, "job.md"), _job_md(row))
    jd_file = os.path.join(folder, "job_description.txt")
    if jd_text:
        _write(jd_file, jd_text + "\n")
    elif os.path.isfile(jd_file):
        jd_text = open(jd_file, encoding="utf-8").read().strip()
    else:
        warnings.append("The job description could not be fetched (site blocked it?), so the CV and cover letter are NOT tailored. "
                        "Paste the posting into job_description.txt and run `./jf prepare --redo --ids %s`." % row.get("ID"))

    # JD & master analysis (Phases 1-2)
    jd_info = jd_analyzer.analyze_jd(jd_text, title=title, company=company)
    provider_name, model_name = cv_model_runner.resolve_tailor_provider_and_model()

    # CV
    tailored: Optional[cv_tailor.TailoredCV] = None
    master = cv_master.build_structured_master(candidate)
    if os.path.isfile(cv_path) and not redo:
        cv = json.load(open(cv_path, encoding="utf-8"))                     # keep the user's edits
    else:
        try:
            tailored = cv_tailor.tailor_cv(master, jd_text, title, company, level, llm=llm)
            cv = tailored.cv
            if not tailored.tailored and tailored.warnings:
                warnings.append(f"CV not tailored ({tailored.warnings[-1]}); using your master CV.")
            _write(os.path.join(folder, "cv_changes.md"), cv_tailor.render_changes_md(tailored, title, company))
        except cv_tailor.TailorUnavailable as e:
            cv = master
            tailored = cv_tailor.TailoredCV(cv=master, tailored=False, warnings=[str(e)])
            warnings.append(f"CV not tailored ({e}); using your profile as-is.")
            _write(os.path.join(folder, "cv_changes.md"), f"# CV not tailored\n\n{e}\n\nThe CV is your profile exactly as saved.\n")
        _write(cv_path, json.dumps(cv, indent=2, ensure_ascii=False))
    cv_html = render_cv_html(cv)
    _write(os.path.join(folder, "cv.html"), cv_html)
    cv_pdf = os.path.join(folder, "cv.pdf")
    ok = render_cv_pdf(cv_html, cv_pdf)
    if not ok:
        warnings.append("cv.pdf could not be rendered (is Playwright Chromium installed? `playwright install chromium`).")
    facts = pdf_facts(cv_pdf) if ok else {}
    if ok:
        try:
            from .pdf_preview import fill_ratio
            facts["page_fill"] = fill_ratio(cv_pdf)            # 0..1: how far down the page the CV reaches
        except Exception:
            pass

    # fit analysis (cached; skipped when re-rendering)
    if not render_only and jd_text:
        md = _fit_md(candidate, title, company, jd_text, level)
        if md:
            _write(os.path.join(folder, "fit_analysis.md"), md)

    # cover letter
    cl_status, cl_warn = "No", []
    txt = os.path.join(folder, "cover_letter.txt")
    wanted = needs_cover_letter(jd_text, cover_letter) or os.path.isfile(txt)
    if wanted:
        if os.path.isfile(txt) and not redo:
            cl_status = "Yes"
        elif render_only:
            cl_status = "No"
        elif not jd_text:
            cl_status, cl_warn = "Failed", ["Cover letter skipped: no job description to write it against."]
        else:
            gen = _generate_cover_letter(title, company, jd_text, candidate)
            letter = str(gen.get("cover_letter") or "").strip()
            if letter:
                _write(txt, letter + "\n")
                notes = [f"# Cover letter notes ({gen.get('status')})", ""]
                if gen.get("warnings"):
                    notes += ["## Warnings", ""] + [f"- {w}" for w in gen["warnings"]] + [""]
                    cl_warn += [f"Cover letter: {w}" for w in gen["warnings"]]
                if gen.get("gaps"):
                    notes += ["## Requirements with no evidence in your profile", "", str(gen["gaps"]), ""]
                if gen.get("alternative_openings"):
                    notes += ["## Alternative opening lines", "", str(gen["alternative_openings"]), ""]
                _write(os.path.join(folder, "cover_letter_notes.md"), "\n".join(notes))
                cl_status = "Yes"
            else:
                cl_status, cl_warn = "Failed", ["Cover letter generation returned nothing."]
        if cl_status == "Yes":
            letter_text = open(txt, encoding="utf-8").read()
            if not _render_pdf(letter_html(cv.get("name", ""), company, letter_text), os.path.join(folder, "cover_letter.pdf")):
                cl_warn.append("cover_letter.pdf could not be rendered; the text is still pasted into forms.")
    warnings += cl_warn

    status = "Ready for review" if ok and (tailored is None or tailored.tailored) and not any("not tailored" in w.lower() for w in warnings) \
        else "Needs attention"
    res = PackResult(folder=folder, status=status, cv_tailored=bool(tailored and tailored.tailored) or (tailored is None and os.path.isfile(os.path.join(folder, "cv_changes.md"))),
                     cv_pdf=cv_pdf if ok else None, cover_letter=cl_status, warnings=warnings)
    # Evidence panel & manifest metadata (Phases 1, 2, 6, 7)
    reqs = jd_info.get("requirements", {})
    all_req_terms = list(reqs.get("must_have", [])) + list(reqs.get("strong", [])) + list(reqs.get("nice_to_have", []))
    kw_found, kw_missing, alias_matches = [], [], []
    for term in all_req_terms:
        ev = cv_master.has_evidence(term, master)
        if ev.get("evidenced"):
            kw_found.append(term)
            if ev.get("alias_used"):
                alias_matches.append(f"{ev['alias_used']} -> {term}")
        else:
            kw_missing.append(term)

    cl_status_norm = "ready" if cl_status == "Yes" else "failed" if cl_status == "Failed" else ("not_asked" if not wanted else "not_generated")
    tailoring_status = "tailored" if res.cv_tailored else "not_tailored"

    _write(os.path.join(folder, "REVIEW.md"), _review_md(row, res, tailored, cl_status, cl_warn, facts))
    _write(os.path.join(folder, "manifest.json"), json.dumps({
        "id": row.get("ID"), "company": company, "role": title, "url": row.get("Job URL"),
        "generated_at": datetime.now().isoformat(timespec="seconds"), "status": res.status,
        "cv_tailored": res.cv_tailored, "cv_pdf": os.path.basename(cv_pdf) if ok else None, "pdf": facts,
        "cover_letter": cl_status,
        "cover_letter_status": cl_status_norm,
        "tailoring_status": tailoring_status,
        "tailor_provider": cv_model_runner.LAST_TAILOR_CALL.get("provider", provider_name),
        "tailor_model": cv_model_runner.LAST_TAILOR_CALL.get("model", model_name),
        "prompt_version": getattr(cv_tailor, "PROMPT_VERSION", "v2"),
        "evidence_panel": {
            "keywords_found": kw_found,
            "keywords_confirmed": [c["skill"] for c in master.get("confirmed_experience", []) if any(c["skill"].lower() in t.lower() or t.lower() in c["skill"].lower() for t in kw_found)],
            "keywords_missing": kw_missing,
            "requirements_gap": [jd_info["seniority"]["gap_note"]] if jd_info.get("seniority", {}).get("gap_note") else [],
            "knockouts": [f"{k['category']}: {k['evidence']}" for k in jd_info.get("knockouts", [])],
            "alias_matches": alias_matches,
            "entailment_results": [],
        },
        "scores": {
            "master_score": getattr(tailored, "master_score", None) if tailored else None,
            "tailored_score": getattr(tailored, "tailored_score", None) if tailored else None,
            "coverage_before": f"{len(kw_found)}/{len(all_req_terms)}" if all_req_terms else "0/0",
            "coverage_after": f"{len(kw_found)}/{len(all_req_terms)}" if all_req_terms else "0/0",
        },
        "unresolved_flags": [],
        "warnings": warnings, "files": sorted(os.listdir(folder)),
    }, indent=2, default=str))
    return res
