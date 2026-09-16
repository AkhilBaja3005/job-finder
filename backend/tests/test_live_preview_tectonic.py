r"""
test_live_preview_tectonic.py
Integration and unit tests for Web Live Preview and Sectioned Tectonic LaTeX Compilation.
Validates:
1. Live web editor debounced compilation endpoint (/compile_latex) with sectioned rSection/rSubsection.
2. Web live preview handling of legacy TeX font switches ({\bf ...}, {\em ...}) and preamble hotfixes.
3. Clean HTTP 400 response propagation on syntax errors (no 500 masking).
4. Multi-pass page-budget metric optimizer (compile_and_check_page_metrics).
5. Hotfix preservation of sectioned structure and font compatibility macros.
"""

import pytest
from starlette.testclient import TestClient
from main import app
from utils.latex_utils import compile_and_check_page_metrics, apply_latex_hotfix

client = TestClient(app)

SAMPLE_SECTIONED_LATEX = r"""\documentclass[11pt]{resume}
\usepackage[T1]{fontenc}
\usepackage[left=0.35in,top=0.15in,right=0.35in,bottom=0.13in]{geometry}
\usepackage{times}
\usepackage[hidelinks]{hyperref}

\name{Alex Developer}
\address{
\begin{minipage}{\linewidth}
\centering
\href{mailto:alex@example.com}{alex@example.com} $|$ +44 7123 456789 $|$ \href{https://linkedin.com/in/alex}{linkedin.com/in/alex}
\end{minipage}
}

\begin{document}

\begin{rSection}{Professional Summary}
Senior AI Engineer specializing in LLM systems, context optimization, and high-throughput RAG infrastructure.
\end{rSection}

\begin{rSection}{Education}
{\bf University of Cambridge} -- {\em MSc in Advanced Computer Science} \\
{\em 2022 -- 2023 $|$ Cambridge, UK}
\end{rSection}

\begin{rSection}{Technical Skills}
\textbf{Languages:} Python, C++, SQL, TypeScript \\
\textbf{AI/ML & GenAI:} PyTorch, LangChain, vLLM, RAG, Transformers \\
\textbf{Systems & Cloud:} Docker, Kubernetes, AWS, FastAPI, CI/CD
\end{rSection}

\begin{rSection}{Work Experience}
\begin{rSubsection}{DeepMind Partner}{Jan 2024 -- Present}{Staff AI Engineer}{London, UK}
    \item Architected distributed context caching pipeline reducing inference latency by 45\%.
    \item Designed production RAG retrieval evaluating over 5M embeddings per day.
\end{rSubsection}
\end{rSection}

\end{document}
"""


def test_web_live_preview_compile_latex_success():
    """
    Validates that the frontend LiveLatexEditor endpoint (/compile_latex)
    successfully compiles sectioned resume code into a valid PDF stream
    with proper headers and single-page budget.
    """
    response = client.post(
        "/compile_latex",
        json={"latex_code": SAMPLE_SECTIONED_LATEX}
    )
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"
    assert response.headers.get("X-Page-Count") == "1"
    assert "X-ATS-Score" in response.headers
    ats_score_val = response.headers.get("X-ATS-Score")
    assert ats_score_val is not None
    assert int(ats_score_val) >= 50
    assert "X-ATS-Skills-Count" in response.headers
    assert "X-ATS-Quant-Percent" in response.headers
    assert response.content.startswith(b"%PDF-")


def test_web_live_preview_legacy_font_switches_and_special_chars():
    r"""
    Validates that legacy TeX formatting ({\bf ...}, {\em ...}) and unescaped
    characters (%, &, _) in live web edits compile cleanly without Undefined control sequence.
    """
    latex_with_legacy_and_chars = SAMPLE_SECTIONED_LATEX.replace(
        "Senior AI Engineer",
        r"{\bf Lead AI Engineer} with 100% test coverage & R&D experience in C#_frameworks"
    )
    response = client.post(
        "/compile_latex",
        json={"latex_code": latex_with_legacy_and_chars}
    )
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/pdf"
    assert response.content.startswith(b"%PDF-")


def test_web_live_preview_compile_latex_returns_400_on_broken_syntax():
    """
    Validates that genuinely broken LaTeX syntax returns a clean HTTP 400
    with informative error details rather than raising an unhandled 500.
    """
    broken_latex = r"\documentclass{resume}\begin{document}\undefinedCommandXYZ{Invalid}\end{document}"
    response = client.post(
        "/compile_latex",
        json={"latex_code": broken_latex}
    )
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "LaTeX compilation failed" in detail or "Undefined control sequence" in detail


def test_compile_and_check_page_metrics_isolated_execution():
    """
    Validates that the underlying page budget calculator (compile_and_check_page_metrics)
    compiles sectioned resume LaTeX in its own directory with resume.cls and returns (1, height).
    """
    pages, fill_ratio = compile_and_check_page_metrics(
        SAMPLE_SECTIONED_LATEX,
        spacing_scale=1.0,
        linespread=1.0
    )
    assert pages == 1
    assert fill_ratio > 0.0


def test_apply_latex_hotfix_preserves_valid_commands_and_fixes_structure():
    """
    Validates that apply_latex_hotfix injects font compatibility fallbacks,
    sanitizes illegal tokens, and preserves sectioned resume class commands.
    """
    hotfixed = apply_latex_hotfix(SAMPLE_SECTIONED_LATEX)
    assert "\\providecommand{\\bf}{\\textbf}" in hotfixed
    assert "\\providecommand{\\em}{\\textit}" in hotfixed
    assert "\\begin{rSection}{Professional Summary}" in hotfixed
    assert "\\name{Alex Developer}" in hotfixed
