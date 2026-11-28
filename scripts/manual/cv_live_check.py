"""Live check of the CV tailoring on real postings: fetch each posting from a scan workbook, build the pack with cover letter,
and compare the tailored CV with the candidate's own resume (job-term coverage, new facts, page fill, ATS check, cover-letter
fact check). Writes results.json and one PDF per job. Needs network and API keys; not part of the test suite.

  CV_CHECK_RESUME=/path/Resume.pdf CV_CHECK_WORKSPACE=/path/to/job-finder-folder \
  CV_CHECK_SCAN=/path/to/scanned_jobs.xlsx CV_CHECK_OUT=/tmp/cvcheck \
  [CV_CHECK_PROVIDER=claude|openai|gemini] [CV_CHECK_IDS=5,4,9] python scripts/manual/cv_live_check.py
"""
import asyncio, json, os, re, sys, time, shutil
sys.path.insert(0, "."); sys.path.insert(0, "backend")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.environ["CV_CHECK_WORKSPACE"], ".env"), override=False)
os.environ["JOB_FINDER_ROOT"] = os.environ["CV_CHECK_WORKSPACE"]
os.environ["JOB_FINDER_TAILOR_PROVIDER"] = os.environ.get("CV_CHECK_PROVIDER", "claude")
import openpyxl
from pypdf import PdfReader
from backend.services import application_pack as ap, cv_master, cv_tailor, cv_verifier, pdf_preview
from services.scraper import scrape_job_description
out = os.environ["CV_CHECK_OUT"]; os.makedirs(out, exist_ok=True)
RES = os.environ["CV_CHECK_RESUME"]
orig = "\n".join(p.extract_text() or "" for p in PdfReader(RES).pages)
prof = json.load(open(os.path.join(os.environ["CV_CHECK_WORKSPACE"], "candidate_profile.json"))); cand = prof["candidate"]
master = cv_master.build_structured_master(cand)
wb = openpyxl.load_workbook(os.environ["CV_CHECK_SCAN"])
ws = wb.active; hdr = [c.value for c in ws[1]]
rows = [dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
if os.environ.get("CV_CHECK_IDS"):
    want = {int(x) for x in os.environ["CV_CHECK_IDS"].split(",")}
    rows = [r for r in rows if int(r["ID"]) in want]
def facts(t): return set(re.findall(r"\d[\d,.]*[+%]?", t)), {x.lower() for x in re.findall(r"\b(?:[A-Z]{2,}[A-Za-z0-9]*|[A-Za-z]+[A-Z][A-Za-z0-9]+)", t)}
sn, st = facts(orig + json.dumps(cand))
def covered(text, terms):
    pseudo = {"summary": text}
    return [t for t in terms if cv_master.has_evidence(t, pseudo).get("evidenced")]
results = []
for r in rows:
    rid = int(r["ID"]); res = {"id": rid, "company": r["Company"], "role": r["Job Role"]}
    t0 = time.time()
    try:
        jd = asyncio.run(asyncio.wait_for(scrape_job_description(r["Job URL"]), timeout=60)).get("description") or ""
        res["jd_chars"] = len(jd)
        if len(jd) < 300:
            res["error"] = "no job description fetched"; results.append(res); continue
        row = {k: ("" if v is None else str(v)) for k, v in r.items()}; row["ID"] = rid
        pack = ap.build_pack(row, cand, jd, level="experienced", cover_letter="always", redo=True, base_dir=out + "/_packs")
        man = json.load(open(pack.folder + "/manifest.json"))
        cvj = json.load(open(pack.folder + "/cv.json")); tcv = cv_tailor.cv_text(cvj)
        from backend.services import jd_analyzer
        reqs = jd_analyzer.analyze_jd(jd, title=r["Job Role"], company=r["Company"])["requirements"]
        terms = list(reqs.get("must_have", [])) + list(reqs.get("strong", []))
        res.update(tailored=pack.cv_tailored, pages=man["pdf"].get("pages"), fill=man["pdf"].get("page_fill"), ats_ok=(man.get("ats_check") or {}).get("ok"),
                   not_a_fit=(man.get("fit_check") or {}).get("not_a_fit"), terms=len(terms), orig_cov=len(covered(orig, terms)), cv_cov=len(covered(tcv, terms)))
        nn, nt = facts(tcv); res["new_numbers"] = sorted(nn - sn)[:5]; res["new_tech"] = sorted(nt - st)[:5]
        cl = pack.folder + "/cover_letter.txt"
        if os.path.isfile(cl):
            letter = open(cl).read(); res["letter_chars"] = len(letter)
            issues = [i for ch in re.split(r"(?<=[.!?])\s+", letter) for i in cv_verifier.check_facts(ch, orig + json.dumps(cand))]
            res["letter_issues"] = issues[:6]
        else:
            res["letter"] = pack.cover_letter
        shutil.copy(pack.folder + "/cv.pdf", f"{out}/{rid:02d}_{r['Company'].split()[0].lower()}.pdf")
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {str(e)[:140]}"
    res["secs"] = round(time.time() - t0); results.append(res)
    print(json.dumps(res), flush=True)
    json.dump(results, open(out + "/results.json", "w"), indent=1)
