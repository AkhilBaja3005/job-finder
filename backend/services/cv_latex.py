"""The CV as LaTeX: generate it from the tailored CV in the candidate's own resume style (resume.cls), let the user edit it,
compile it with Tectonic, and fit it on one page. Nothing here writes facts: the text comes from cv.json or from what the
user typed, and an edited LaTeX is checked against the resume afterwards (claims not found there are reported, not blocked)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
SHRINK_STEPS = ((None, 1.0), (None, 0.85), (10.4, 0.9), (10.0, 0.85), (9.6, 0.8), (9.2, 0.75))   # (font size or None, spacing scale), tried in order until one page


def tectonic_path() -> Optional[str]:
    return os.environ.get("TECTONIC_PATH") or shutil.which("tectonic")


def tectonic_available() -> bool:
    return bool(tectonic_path())


def cv_to_latex(cv: Dict[str, Any]) -> str:
    """cv.json (tailored or master) -> LaTeX in the resume.cls style."""
    try:
        from utils.latex_utils import generate_latex_from_json
    except ImportError:  # pragma: no cover
        from backend.utils.latex_utils import generate_latex_from_json
    data = dict(cv)
    data["skills"] = cv.get("skill_groups") or cv.get("skills") or []
    data["education"] = [dict(e, cpi=e.get("grade") or e.get("cpi") or "") for e in cv.get("education", [])]
    return generate_latex_from_json(data)


def _find_class_file() -> Optional[str]:
    for path in (os.path.join(ASSETS, "resume.cls"),):
        if os.path.isfile(path):
            return path
    return None


def compile_latex(tex: str, out_pdf: str, timeout: int = 180) -> Tuple[bool, str]:
    """Compile `tex` to `out_pdf`. (True, "") on success, otherwise (False, a short readable error)."""
    exe = tectonic_path()
    if not exe:
        return False, "LaTeX is not installed (Tectonic was not found). Install it, or keep using the standard CV."
    cls = _find_class_file()
    with tempfile.TemporaryDirectory(prefix="jf_tex_") as tmp:
        if cls:
            shutil.copy(cls, os.path.join(tmp, "resume.cls"))
        src = os.path.join(tmp, "cv.tex")
        with open(src, "w", encoding="utf-8") as f:
            f.write(tex)
        try:
            run = subprocess.run([exe, "-X", "compile", src, "--outdir", tmp] if _supports_v2(exe) else [exe, src, "--outdir", tmp],
                                 cwd=tmp, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"LaTeX took longer than {timeout} seconds (the first run downloads fonts and packages; try again)."
        except OSError as exc:
            return False, f"Could not start Tectonic: {exc}"
        pdf = os.path.join(tmp, "cv.pdf")
        if run.returncode != 0 or not os.path.isfile(pdf):
            return False, summarize_error(run.stderr + "\n" + run.stdout)
        os.makedirs(os.path.dirname(os.path.abspath(out_pdf)), exist_ok=True)
        shutil.copy(pdf, out_pdf)
    return True, ""


def _supports_v2(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
        return bool(re.search(r"\b0\.(1[5-9]|[2-9]\d)", out)) and False      # the classic "tectonic file.tex" works on every version
    except Exception:
        return False


def summarize_error(log: str) -> str:
    """The first real LaTeX error with its line, not the whole log."""
    lines = [l.strip() for l in (log or "").splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if line.startswith("error:") or line.startswith("!") or " error:" in line:
            hint = next((l for l in lines[i + 1:i + 6] if l.startswith("l.") or "line" in l.lower()), "")
            return (line[:200] + (" | " + hint[:120] if hint else "")).strip()
    return (lines[-1] if lines else "LaTeX failed.")[:200]


def apply_spacing_scale(tex: str, scale: float, font_pt: Optional[float] = None) -> str:
    """Tighten the template's skips and, when asked, set a smaller body font. (resume.cls is fixed at 11pt, so the size is set
    after the preamble.)"""
    out = tex
    if scale < 0.999:
        def shrink(match: "re.Match[str]") -> str:
            return f"{match.group(1)}{max(0.0, round(float(match.group(2)) * scale, 3))}em}}"
        out = re.sub(r"(\\def\\(?:sectionskip|sectionlineskip|nameskip|addressskip)\{\\vspace\{)([0-9.]+)em\}", shrink, out)
    if font_pt:
        size = f"\\AtBeginDocument{{\\fontsize{{{font_pt}pt}}{{{round(font_pt * 1.16, 2)}pt}}\\selectfont}}"
        out = out.replace("\\begin{document}", size + "\n\\begin{document}", 1)
    return out


def compile_fit_one_page(tex: str, out_pdf: str) -> Tuple[bool, str, Optional[int], str]:
    """Compile; if it runs onto page 2, tighten and retry. Returns (ok, error, pages, tex_used). The user's own edits are kept
    verbatim when the first compile is already one page."""
    from .pdf_preview import page_count
    last_err, used = "", tex
    for font_pt, scale in SHRINK_STEPS:
        used = apply_spacing_scale(tex, scale, font_pt)
        ok, err = compile_latex(used, out_pdf)
        if not ok:
            return False, err, None, tex
        pages = page_count(out_pdf)
        if pages in (None, 1):
            return True, "", pages, used
        last_err = f"The CV is {pages} pages; trim a bullet to fit one page."
    return True, last_err, page_count(out_pdf), used


def unsupported_claims(edited_tex_text: str, source_text: str) -> List[str]:
    """Facts in the edited CV text (numbers, tool names, names) that are not in the resume/profile source: shown as warnings."""
    try:
        from . import cv_verifier
    except ImportError:  # pragma: no cover
        from backend.services import cv_verifier
    plain = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", edited_tex_text)
    plain = re.sub(r"[{}$\\]", " ", plain)
    issues: List[str] = []
    for chunk in re.split(r"\n\s*\n|\\\\|\n", plain):
        if len(chunk.strip()) > 20:
            issues += cv_verifier.check_facts(chunk, source_text)
    return list(dict.fromkeys(issues))[:12]
