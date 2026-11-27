"""
html_resume_renderer.py — Hybrid HTML/CSS to PDF Resume Generator

Provides an optional clean HTML/CSS responsive template rendered into a PDF
using headless Playwright, allowing non-technical candidates to easily view
and edit HTML templates alongside standard LaTeX.
"""

import os
import re
from typing import Dict, Any, Optional

try:
    # pyrefly: ignore [missing-import]
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{{NAME}} - Resume</title>
<style>
  @page {
    size: A4;
    margin: 11mm 14mm;
  }
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  body {
    font-family: "Times New Roman", Georgia, "Liberation Serif", Times, serif;
    color: #111111;
    line-height: 1.32;
    font-size: 9.8pt;
    background: #fff;
  }
  .header {
    text-align: center;
    padding-bottom: 6px;
    margin-bottom: 8px;
  }
  .name {
    font-size: 19pt;
    font-weight: 700;
    color: #000000;
    letter-spacing: 0.4px;
  }
  .contact-bar {
    font-size: 8.8pt;
    color: #222222;
    margin-top: 3px;
  }
  .contact-bar a {
    color: #111111;
    text-decoration: underline;
  }
  .section-title {
    font-size: 10pt;
    font-weight: 700;
    color: #000000;
    text-transform: uppercase;
    border-bottom: 0.8pt solid #111111;
    padding-bottom: 1.5px;
    margin-top: 8px;
    margin-bottom: 4px;
    letter-spacing: 0.5px;
  }
  .summary-text {
    font-size: 9.3pt;
    color: #111111;
    text-align: justify;
  }
  .job-header, .edu-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 5px;
  }
  .job-company, .edu-school {
    font-weight: 700;
    color: #000000;
    font-size: 9.6pt;
  }
  .job-role, .edu-degree {
    font-weight: 600;
    color: #111111;
    font-size: 9.3pt;
    font-style: italic;
  }
  .job-dates, .edu-dates {
    font-size: 9pt;
    color: #222222;
    font-style: italic;
  }
  .tech-line {
    font-size: 8.5pt;
    color: #333333;
    font-style: italic;
    margin-bottom: 2px;
  }
  ul.bullets {
    padding-left: 15px;
    margin-top: 2px;
  }
  ul.bullets li {
    font-size: 9.1pt;
    color: #111111;
    margin-bottom: 1.8px;
    line-height: 1.3;
  }
  .skills-category {
    font-size: 9.1pt;
    margin-bottom: 2.5px;
    color: #111111;
  }
  .skills-category strong {
    color: #000000;
  }
  .metric-bold {
    font-weight: 700;
    color: #000000;
  }
</style>
</head>
<body>

<div class="header">
  <div class="name">{{NAME}}</div>
  <div class="contact-bar">
    {{CONTACT}}
  </div>
</div>

{{SUMMARY_SECTION}}

{{EXPERIENCE_SECTION}}

{{SKILLS_SECTION}}

{{EDUCATION_SECTION}}

{{PROJECTS_SECTION}}

</body>
</html>"""


_METRIC_RE = re.compile(r"\b(\d[\d,\.]*\s*(?:%|x|\+|Cr\+|K\+|M\+)(?=\b|\s|[.,;)]))")


def _bold_metrics(text: str) -> str:
    return _METRIC_RE.sub(r'<strong class="metric-bold">\1</strong>', text)


def render_html_resume(resume_data: Dict[str, Any]) -> str:
    """Generates clean, semantic HTML resume string from candidate data dict."""
    name = resume_data.get("name", "CANDIDATE NAME").upper()
    email = resume_data.get("email", "")
    phone = resume_data.get("phone", "")
    links = resume_data.get("links", [])
    link_html = " | ".join([f'<a href="{l}">{l.replace("https://", "").replace("www.", "")}</a>' for l in links])

    # Summary
    summary = resume_data.get("summary", "")
    summary_sec = ""
    if summary:
        summary_sec = f"""<div class="section-title">Professional Summary</div>
<p class="summary-text">{summary}</p>"""

    # Experience
    exp_sec = ""
    exp_items = resume_data.get("experience", [])
    if exp_items:
        exp_sec = '<div class="section-title">Work Experience</div>'
        for exp in exp_items:
            comp = exp.get("company", "")
            role = exp.get("role", "")
            dates = f"{exp.get('start_date', '')} – {exp.get('end_date', '')}"
            tech = exp.get("technologies", "")
            tech_line = f'<div class="tech-line">Technologies: {tech}</div>' if tech else ""
            
            bullets = "".join([f"<li>{_bold_metrics(b)}</li>" for b in exp.get("description", [])])
            exp_sec += f"""
<div class="job-item">
  <div class="job-header">
    <div><span class="job-company">{comp}</span> | <span class="job-role">{role}</span></div>
    <div class="job-dates">{dates}</div>
  </div>
  {tech_line}
  <ul class="bullets">{bullets}</ul>
</div>"""

    # Skills
    skills_sec = ""
    skills_data = resume_data.get("skills", {})
    if skills_data:
        skills_sec = '<div class="section-title">Technical Skills</div>'
        if isinstance(skills_data, dict):
            for cat, skl_list in skills_data.items():
                skills_str = ", ".join(skl_list) if isinstance(skl_list, list) else str(skl_list)
                skills_sec += f'<div class="skills-category"><strong>{cat}:</strong> {skills_str}</div>'
        elif isinstance(skills_data, list):
            skills_sec += f'<div class="skills-category">{", ".join(skills_data)}</div>'

    # Education
    edu_sec = ""
    edu_items = resume_data.get("education", [])
    if edu_items:
        edu_sec = '<div class="section-title">Education</div>'
        for edu in edu_items:
            inst = edu.get("institution", "")
            deg = edu.get("degree", "")
            field = edu.get("field_of_study", "")
            dates = f"{edu.get('start_date', '')} – {edu.get('graduation_date', '')}"
            deg_full = f"{deg} in {field}" if field else deg
            edu_sec += f"""
<div class="edu-item">
  <div class="edu-header">
    <div class="edu-school">{inst}</div>
    <div class="edu-dates">{dates}</div>
  </div>
  <div class="edu-degree">{deg_full}</div>
</div>"""

    # Projects
    proj_sec = ""
    proj_items = resume_data.get("projects", [])
    if proj_items:
        proj_sec = '<div class="section-title">Projects</div>'
        for p in proj_items:
            title = p.get("title", "")
            bullets = "".join([f"<li>{b}</li>" for b in p.get("description", [])])
            proj_sec += f"""
<div class="proj-item">
  <div style="font-weight: 700; color: #0f172a; font-size: 9.5pt; margin-top: 4px;">{title}</div>
  <ul class="bullets">{bullets}</ul>
</div>"""

    html = (
        HTML_TEMPLATE
        .replace("{{NAME}}", name)
        .replace("{{CONTACT}}", " | ".join(part for part in (email, phone, link_html) if part))
        .replace("{{SUMMARY_SECTION}}", summary_sec)
        .replace("{{EXPERIENCE_SECTION}}", exp_sec)
        .replace("{{SKILLS_SECTION}}", skills_sec)
        .replace("{{EDUCATION_SECTION}}", edu_sec)
        .replace("{{PROJECTS_SECTION}}", proj_sec)
    )
    return html


async def compile_html_to_pdf(html_content: str, output_pdf_path: str) -> bool:
    """Compiles HTML string into a sharp PDF using headless Playwright."""
    if not async_playwright:
        return False
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_content(html_content, wait_until="networkidle")
            os.makedirs(os.path.dirname(os.path.abspath(output_pdf_path)), exist_ok=True)
            await page.pdf(
                path=output_pdf_path,
                format="A4",
                print_background=True,
                margin={"top": "10mm", "bottom": "10mm", "left": "12mm", "right": "12mm"}
            )
            await browser.close()
            return os.path.exists(output_pdf_path)
    except Exception as e:
        print(f"[HTMLResumeRenderer] Error compiling HTML to PDF: {e}")
        return False
