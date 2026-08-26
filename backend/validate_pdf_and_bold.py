import os
import sys
import shutil
import subprocess
import time
from typing import Any, Dict, List

# Ensure backend root is in sys.path
backend_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, backend_dir)

# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
load_dotenv()

from utils.latex_utils import apply_latex_hotfix, compile_and_check_page_metrics
from services.llm_agent import tailor_latex_code
# pyrefly: ignore [missing-import]
import fitz  # PyMuPDF

def validate_resume_tailoring():
    print("=" * 60)
    print("🚀 RUNNING RESUME TAILORING VALIDATION TEST")
    print("=" * 60)

    # 1. Sample Master LaTeX template
    master_latex = r"""
\documentclass[12pt]{resume}

\usepackage[T1]{fontenc}
\usepackage[left=0.35in,top=0.25in,right=0.35in,bottom=0.22in]{geometry}
\usepackage{fontawesome}
\usepackage{times}
\usepackage{hyperref}

\newcommand\mybar{\kern1pt\rule[-\dp\strutbox]{.8pt}{\baselineskip}\kern1pt}

\hypersetup{
    colorlinks=false,
    pdfborder={0 0 0}
}

% Force black dots for all levels of itemize
\renewcommand{\labelitemi}{$\bullet$}
\renewcommand{\labelitemii}{$\bullet$}
\frenchspacing

\name{Akhil Baja}

\address{
\faEnvelope\ \href{mailto:akhilbaja.work@gmail.com}{akhilbaja.work@gmail.com}
|
\faPhone\ +91 9948083135
|
\href{https://www.linkedin.com/in/akhilbaja}{ \faLinkedinSquare\ linkedin.com/in/akhilbaja}
|
\href{https://github.com/AkhilBaja3005}{ \faGithub\ github.com/AkhilBaja3005 }
}

\begin{document}

\vspace{-0.2em}
\begin{rSection}{Professional Summary}
AI/ML Engineer with 3+ years of experience building production-grade GenAI, ML and developer infrastructure at \textbf{Qualcomm} and \textbf{Axis Bank}. Engineered cross-language LLM context pipelines cutting retrieval latency by \textbf{60\%} and improving LLM accuracy by \textbf{46\%}, alongside enterprise GenAI systems serving \textbf{1,000+} users. Strong in Python, LLMs, RAG, machine learning, and distributed systems; MSc student in Artificial Intelligence Applications and Innovation at \textbf{Imperial College London}.
\end{rSection}

\vspace{-0.3em}
\begin{rSection}{Work Experience}
{\bf Qualcomm \mybar \textnormal{Software Engineer (GenAI / Systems)}} \hfill {\em Dec 2024 -- Aug 2026} \\
{\em Technologies: Python, C++, Jedi, Jenkins, RabbitMQ, Docker, Rancher, SQL, Git}
\vspace{-0.35em}
\begin{itemize}
    \setlength{\itemsep}{-0.20em}
    \setlength{\parsep}{0em}
    \item Engineered a cross-language \textbf{LLM context engineering} pipeline using AST-based dependency extraction across Java, Python, C and C++, reducing retrieval latency by \textbf{60\%} and improving LLM accuracy by \textbf{46\%} — \textbf{Qualcomm Certificate of Recognition}.
    \item Re-architected a central data-harvesting pipeline for \textbf{1,000+} users, cutting deployment failure rate by \textbf{84\%} by replacing legacy Jenkins workflows with asynchronous \textbf{RabbitMQ} queues and containerizing microservices via \textbf{Docker/Rancher} for cross-OS deployment stability.
    \item Slashed static analysis parser execution latency by \textbf{93\%} and consolidated \textbf{200+} unit tests into a Linux-compatible test harness, cutting ongoing maintenance overhead by \textbf{60\%}.
\end{itemize}

{\bf Axis Bank \mybar \textnormal{Data Scientist (AI / ML)}} \hfill {\em July 2023 -- Dec 2024} \\
{\em Technologies: Python, Azure OpenAI, PySpark, Cloudera ML, SAS EG, SQL, XGBoost}
\vspace{-0.35em}
\begin{itemize}
    \setlength{\itemsep}{-0.20em}
    \setlength{\parsep}{0em}
    \item Built and deployed an enterprise GenAI assistant using \textbf{Azure OpenAI and Cloudera ML}, serving \textbf{1,000+} active employees and reducing internal query resolution time by \textbf{70\%}.
    \item Engineered an \textbf{Isolation Forest} anomaly detection model for Gold Loans, flagging branch-level risk patterns tied to \textbf{\pounds30M+} in projected annual portfolio loss exposure and cutting manual review time by \textbf{80\%} — \textbf{BIU Star Award}.
    \item Automated customer Dynamic Risk Rating via \textbf{XGBoost and Naive Bayes} pipelines, reducing manual processing effort by \textbf{\textasciitilde40\%} and aligning the automated risk-rating process with \textbf{RBI (Reserve Bank of India)} regulatory requirements.
\end{itemize}
\end{rSection}

\vspace{-0.3em}
\begin{rSection}{Technical Skills}
\vspace{-0.1em}
\textbf{Languages:} Python, SQL, C++, Java \\
\textbf{AI/ML \& GenAI:} Generative AI, Large Language Models (LLMs), RAG, LLM Context Engineering, Machine Learning, Deep Learning, Anomaly Detection, XGBoost, Naive Bayes, Computer Vision (U-Net, DenseNet) \\
\textbf{Data \& Platforms:} PySpark, Azure OpenAI, Cloudera ML, PostgreSQL, SAS EG \\
\textbf{Software \& Infrastructure:} Docker, Rancher, RabbitMQ, Jenkins, Git, AST Parsing, Static Analysis, Distributed Systems, Microservices, CI/CD, Unit Testing

\end{rSection}

\vspace{-0.3em}
\begin{rSection}{Education}
{\bf Imperial College London} \hfill {\em Sept 2026 -- Sept 2027} \\
{\textit{MSc in Artificial Intelligence Applications and Innovation}} \hfill {\em London, UK} \\
{\bf IIT Hyderabad} \hfill {\em Aug 2019 -- May 2023} \\
{\textit{B.Tech in Engineering Science}} \hfill {\em CPI: 8.04 / 10.0} \\
\textit{\textbf{Internship and Placement Cell Coordinator} — Managed corporate outreach and recruitment operations for \textbf{100+} technology and engineering firms.}
\end{rSection}

\vspace{-0.3em}
\begin{rSection}{Projects}
\vspace{-0.2em}
\begin{itemize}
    \setlength{\itemsep}{-0.25em}
    \setlength{\parsep}{0em}
    \item \textbf{Cosmic Ray Segmentation (Deep Learning):} Enhanced the \textbf{deepCR} model for cosmic-ray detection in astronomical images; evaluated \textbf{U-Net} and implemented residual connections, improving pixel-level segmentation precision by \textbf{15\%}.
    \item \textbf{Tuberculosis Detection Pipeline (Computer Vision):} Implemented a transfer-learning pipeline combining \textbf{U-Net} segmentation and \textbf{DenseNet} classification across \textbf{5,000+} chest X-rays (\textbf{+12\%} accuracy over baseline).
    \item \textbf{Scientific Publications Database (Data Infrastructure):} Designed and optimized a \textbf{PostgreSQL} database and custom ER schema for 2M+ research papers, accelerating query execution time by \textbf{45\%} via targeted indexing.
\end{itemize}
\end{rSection}
\end{document}
"""

    job_title = "Senior Data Scientist"
    jd_text = "Looking for a Senior Data Scientist with expertise in PySpark, Python, GCP, ML model deployment, A/B testing, and SQL optimization."
    suggested_updates = [
        "Emphasize PySpark scalability metrics",
        "Highlight GCP cloud infrastructure experience"
    ]
    missing_skills = ["PySpark", "GCP", "A/B Testing"]

    print("\n1️⃣  Running LLM Tailor + Sanitizer...")
    t0 = time.time()
    tailored_latex = tailor_latex_code(master_latex, job_title, jd_text, suggested_updates, missing_skills, None, "", on_log=None)
    print(f"   Done in {time.time() - t0:.2f}s")

    output_dir = os.path.join(backend_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    
    # Copy resume.cls
    cls_src = os.path.join(backend_dir, "assets", "resume.cls")
    shutil.copy2(cls_src, os.path.join(output_dir, "resume.cls"))

    tex_path = os.path.join(output_dir, "validation_test.tex")
    pdf_path = os.path.join(output_dir, "validation_test.pdf")

    print(f"pdf-path: {pdf_path}")
    print(f"latex-path: {tex_path}")

    print("\n2️⃣  Applying Multi-Pass Single-Page Optimization...")
    pages, _ = compile_and_check_page_metrics(tailored_latex, 1.0, 1.0, master_latex)
    opt_scale, opt_ls = 1.0, 1.0
    if pages > 1:
        p = pages
        for ls in [0.95, 0.91, 0.88, 0.82, 0.78]:
            p, _ = compile_and_check_page_metrics(tailored_latex, 1.0, ls, master_latex)
            if p == 1:
                opt_ls = ls
                break
        if p > 1:
            for scale in [0.95, 0.90, 0.85, 0.80]:
                p, _ = compile_and_check_page_metrics(tailored_latex, scale, opt_ls, master_latex)
                if p == 1:
                    opt_scale = scale
                    break

    fixed_code = apply_latex_hotfix(tailored_latex, opt_scale, opt_ls, master_latex)
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(fixed_code)

    print("\n3️⃣  Compiling LaTeX PDF via Tectonic...")
    res = subprocess.run(
        ["tectonic", tex_path, "--outdir", output_dir],
        capture_output=True,
        text=True
    )
    if res.returncode != 0:
        print(f"❌ Compilation Failed: {res.stderr}")
        sys.exit(1)

    print("   Compilation successful!")

    print("\n4️⃣  VERIFYING TEST RESULTS...")
    doc = fitz.open(pdf_path)
    page_count = doc.page_count

    # Check 1: Single Page Verification
    print(f"\n   📄 [CHECK 1: PAGE COUNT]")
    print(f"      Total Pages: {page_count}")
    if page_count == 1:
        print("      ✅ PASS: Resume is strictly 1 page!")
    else:
        print(f"      ❌ FAIL: Resume spilled onto {page_count} pages!")

    # Check 2: Bold Text Verification
    print(f"\n   🔦 [CHECK 2: BOLD CHARACTERS]")
    page = doc[0]
    page_dict: Any = page.get_text("dict")
    blocks = page_dict.get("blocks", []) if isinstance(page_dict, dict) else []
    
    bold_spans = []
    for block in blocks:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = span.get("font", "")
                flags = span.get("flags", 0)
                text = span.get("text", "").strip()
                if text and ("Bold" in font or "bold" in font or flags & (1 << 4)):
                    bold_spans.append(text)

    print(f"      Found {len(bold_spans)} bold text spans in PDF.")
    if bold_spans:
        print(f"      Sample Bold Spans: {bold_spans[:8]}")
        print("      ✅ PASS: Bold characters are present and rendering correctly!")
    else:
        print("      ❌ FAIL: No bold text detected in compiled PDF!")

    print("\n" + "=" * 60)
    if page_count == 1 and bold_spans:
        print("🎉 ALL VALIDATION TESTS PASSED PERFECTLY!")
    else:
        print("⚠️  VALIDATION FAILED — CHECK LOGS ABOVE")
    print("=" * 60)

if __name__ == "__main__":
    validate_resume_tailoring()
