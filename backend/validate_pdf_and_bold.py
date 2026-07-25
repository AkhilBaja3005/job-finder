import os
import sys
import shutil
import subprocess
import time

# Ensure backend root is in sys.path
backend_dir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, backend_dir)

from dotenv import load_dotenv
load_dotenv()

from utils.latex_utils import apply_latex_hotfix
from services.llm_agent import tailor_latex_code
import fitz  # PyMuPDF

def validate_resume_tailoring():
    print("=" * 60)
    print("🚀 RUNNING RESUME TAILORING VALIDATION TEST")
    print("=" * 60)

    # 1. Sample Master LaTeX template
    master_latex = r"""\documentclass{resume}
\usepackage[left=0.4in,top=0.4in,right=0.4in,bottom=0.4in]{geometry}
\usepackage{hyperref}
\hypersetup{hidelinks}

\name{BAJA AKHIL}
\address{akhilkumarbaja@gmail.com | +91 9948083135 | github.com/akhilbaja}

\begin{document}
\begin{rSection}{Professional Summary}
Data Scientist with 3 years of experience in predictive modelling, large-scale data engineering, and machine learning. Proven track record in developing scalable data pipelines and deploying models using Python, PySpark, and SQL. Adept at applying statistical techniques to optimize ranking and recommendation systems.
\end{rSection}

\begin{rSection}{Technical Skills}
\textbf{Languages:} Python, SQL, R, Scala \\
\textbf{Frameworks:} PySpark, TensorFlow, PyTorch, scikit-learn \\
\textbf{Cloud:} GCP, AWS, Azure \\
\textbf{Tools:} Airflow, Docker, Kubernetes, Git
\end{rSection}

\begin{rSection}{Professional Experience}
\begin{rSubsection}{Nexus Corporation}{June 2023 -- Present}{Senior Data Scientist}{Remote}
\item Developed and deployed scalable recommendation model serving 50M+ daily active users, improving engagement by 35%
\item Built automated ETL data pipelines with PySpark and Airflow on GCP, reducing processing latency by 40%
\item Implemented A/B testing framework across key product flows, increasing conversions by 18%
\item Mentored junior engineers and led technical architecture reviews for data engineering infrastructure
\end{rSubsection}

\begin{rSubsection}{TechCorp Global}{January 2021 -- May 2023}{Data Scientist}{Hyderabad, India}
\item Formulated customer churn predictive models achieving 92% ROC-AUC score using XGBoost
\item Created real-time anomaly detection pipelines processing 10K events/sec using Kafka and PySpark
\item Optimized SQL database queries and indexes, improving dashboard load times by 50%
\end{rSubsection}
\end{rSection}

\begin{rSection}{Education}
\textbf{IIT Hyderabad} \hfill May 2023 \\
B.Tech in Engineering Science \hfill {\em CPI: 8.04}
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

    print("\n2️⃣  Applying Hotfix & Geometry Constraints...")
    fixed_code = apply_latex_hotfix(tailored_latex)
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
    blocks = page.get_text("dict")["blocks"]
    
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
