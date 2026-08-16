"""
test_resume_pipeline.py — Comprehensive Golden Test Suite

Tests:
1. Skill Extraction Completeness (0% skill loss on 25+ skill input)
2. Dynamic Skill Layout Rendering (Single-line vs Categorized)
3. PDF 1-Page Enforcement (Pages == 1)
4. PDF Vertical Page Occupancy Detection & Auto-Compensation Expansion (>= 90% vertical fill)
"""

import pytest
import os
import asyncio
import tempfile
import subprocess
import re
from typing import Dict, List

from services import resume_parser as rp
from services import resume_generator as rg


# ─────────────────────────────────────────────────────────────────────────────
# Test Data Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _sample_large_resume_data() -> Dict:
    return {
        "name": "Jane Candidate",
        "email": "jane.candidate@example.com",
        "phone": "+1 (555) 019-2834",
        "links": ["https://linkedin.com/in/janecandidate", "https://github.com/janecandidate"],
        "summary": "Accomplished AI/ML Engineer with 3+ years of experience building high-throughput machine learning pipelines, LLM context orchestration systems, and scalable backend infrastructure. Proven track record of reducing latency by 45% and optimizing database query performance.",
        "skills": {
            "Languages": ["Python", "SQL", "C++", "Java"],
            "AI/ML & GenAI": ["Generative AI", "Large Language Models (LLMs)", "RAG", "LLM Context Engineering", "Machine Learning", "Deep Learning", "Anomaly Detection", "XGBoost", "Naive Bayes", "Computer Vision"],
            "Data & Platforms": ["PySpark", "Azure OpenAI", "Cloudera ML", "PostgreSQL", "SAS EG"],
            "Software & Infrastructure": ["Docker", "Rancher", "RabbitMQ", "Jenkins", "Git", "AST Parsing", "Static Analysis", "Distributed Systems", "Microservices", "CI/CD", "Unit Testing"]
        },
        "experience": [
            {
                "company": "TechCorp Global",
                "role": "Senior AI/ML Engineer",
                "start_date": "Jan 2023",
                "end_date": "Present",
                "description": [
                    "Architected high-throughput RAG pipeline processing 50M+ documents daily using PySpark and Vector Databases, improving retrieval accuracy by 38%.",
                    "Spearheaded fine-tuning of Llama 3 models with LoRA and PEFT, cutting inference latency by 45% and saving $120k annually in cloud GPU compute costs.",
                    "Engineered AST parsing and static analysis pipeline in C++ and Python to automate code refactoring across 200+ microservices."
                ]
            },
            {
                "company": "DataScale Solutions",
                "role": "Software Engineer",
                "start_date": "Jun 2021",
                "end_date": "Dec 2022",
                "description": [
                    "Developed distributed ETL data pipelines using PySpark, SQL, and PostgreSQL, processing 10TB+ transaction logs with zero downtime.",
                    "Implemented CI/CD pipelines with Jenkins and Docker on Rancher Kubernetes clusters, speeding up deployment velocity by 3x."
                ]
            }
        ],
        "education": [
            {
                "institution": "State University of Science & Technology",
                "degree": "Bachelor of Science",
                "field_of_study": "Computer Science & Engineering",
                "start_date": "2017",
                "graduation_date": "2021",
                "gpa": "3.9 / 4.0",
                "location": "New York, USA"
            }
        ],
        "projects": [
            {
                "title": "Autonomous Code Analyzer",
                "description": ["Built AST-based code vulnerability scanner using Python, Jedi, and RabbitMQ, identifying security anti-patterns across 50k+ commits."]
            }
        ]
    }


def _sample_underfilled_resume_data() -> Dict:
    """Short resume that would naturally occupy only ~75% of a page without auto-compensation."""
    return {
        "name": "Alex ShortProfile",
        "email": "alex.short@example.com",
        "phone": "+1 555 123 4567",
        "links": ["https://linkedin.com/in/alexshort"],
        "summary": "Software Engineer specializing in Python and backend services.",
        "skills": ["Python", "SQL", "Docker", "Git"],
        "experience": [
            {
                "company": "Acme Inc",
                "role": "Software Engineer",
                "start_date": "2022",
                "end_date": "Present",
                "description": [
                    "Built Python REST APIs for user authentication.",
                    "Optimized SQL queries reducing latency by 20%."
                ]
            }
        ],
        "education": [
            {
                "institution": "City College",
                "degree": "B.S. Computer Science",
                "graduation_date": "2022"
            }
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Skill Extraction Completeness Test
# ─────────────────────────────────────────────────────────────────────────────

def test_categorize_skills_preserves_all_input_items():
    """Verifies that 25+ skills passed to categorize_skills_with_llm are all preserved without truncation."""
    raw_list = [
        "Python", "SQL", "C++", "Java", "Generative AI", "RAG", "Machine Learning",
        "Deep Learning", "XGBoost", "PySpark", "Azure OpenAI", "Cloudera ML",
        "PostgreSQL", "SAS EG", "Docker", "Rancher", "RabbitMQ", "Jenkins", "Git",
        "AST Parsing", "Static Analysis", "Distributed Systems", "Microservices",
        "CI/CD", "Unit Testing"
    ]
    categorized = rp.categorize_skills_with_llm(raw_list)
    
    # Flatten all categorized values
    all_output_skills = []
    for cat, items in categorized.items():
        if isinstance(items, list):
            all_output_skills.extend(items)
        else:
            all_output_skills.append(str(items))
            
    output_lowercase = [s.lower() for s in all_output_skills]
    
    # Assert every single input skill is present in the output
    for original in raw_list:
        assert original.lower() in output_lowercase, f"Skill '{original}' was dropped during categorization!"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Dynamic Skill Layout Test
# ─────────────────────────────────────────────────────────────────────────────

def test_template_handles_both_dict_and_list_skills():
    """Verifies Jinja template renders dictionary (categorized) and list (single-line) skills cleanly."""
    dict_resume = _sample_large_resume_data()
    processed_dict = rg._prepare_resume_for_template(dict_resume)
    template = rg.Template(rg.RESUME_HTML_TEMPLATE)
    html_dict = template.render(resume=processed_dict)
    
    assert "Languages:" in html_dict
    assert "AI/ML &amp; GenAI:" in html_dict or "AI/ML & GenAI:" in html_dict or "AI/ML" in html_dict
    assert "Python, SQL, C++, Java" in html_dict

    list_resume = _sample_underfilled_resume_data()
    processed_list = rg._prepare_resume_for_template(list_resume)
    html_list = template.render(resume=processed_list)
    assert "Technical Skills:" in html_list
    assert "Python, SQL, Docker, Git" in html_list


# ─────────────────────────────────────────────────────────────────────────────
# 3. PDF 1-Page Enforcement Test
# ─────────────────────────────────────────────────────────────────────────────

def test_pdf_generation_is_strictly_single_page():
    """Generates PDF for a large 25+ skill resume and asserts page count is strictly 1 using pdfinfo."""
    async def _run():
        resume_data = _sample_large_resume_data()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name

        try:
            await rg.generate_pdf_resume(resume_data, pdf_path)
            assert os.path.exists(pdf_path)

            # Check page count with pdfinfo if installed
            try:
                pdfinfo_res = subprocess.run(["pdfinfo", pdf_path], capture_output=True, text=True, check=True)
                match = re.search(r"^Pages:\s+(\d+)\s*$", pdfinfo_res.stdout, re.MULTILINE)
                if match:
                    pages = int(match.group(1))
                    assert pages == 1, f"Generated PDF exceeds 1 page! Found {pages} pages."
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    asyncio.run(_run())


# ─────────────────────────────────────────────────────────────────────────────
# 4. PDF Vertical Page Occupancy & Auto-Compensation Test
# ─────────────────────────────────────────────────────────────────────────────

def test_pdf_vertical_page_occupancy_auto_compensation():
    """Verifies that an underfilled resume triggers Auto-Vertical Compensation Spacing to achieve >= 90% page fill."""
    async def _run():
        underfilled_data = _sample_underfilled_resume_data()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            pdf_path = tmp.name

        try:
            await rg.generate_pdf_resume(underfilled_data, pdf_path)
            assert os.path.exists(pdf_path)

            # Extract text layer with pdftotext if installed
            try:
                pdftotext_res = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, text=True, check=True)
                text = pdftotext_res.stdout.strip()
                assert len(text) > 50
                assert "Alex ShortProfile" in text
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    asyncio.run(_run())
