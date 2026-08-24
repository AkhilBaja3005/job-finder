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
    margin: 12mm 15mm;
  }
  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1e293b;
    line-height: 1.4;
    font-size: 10pt;
    background: #fff;
  }
  .header {
    text-align: center;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 8px;
    margin-bottom: 12px;
  }
  .name {
    font-size: 20pt;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.5px;
  }
  .contact-bar {
    font-size: 9pt;
    color: #475569;
    margin-top: 4px;
  }
  .contact-bar a {
    color: #0284c7;
    text-decoration: none;
  }
  .section-title {
    font-size: 11pt;
    font-weight: 800;
    color: #0284c7;
    text-transform: uppercase;
    border-bottom: 1px solid #cbd5e1;
    padding-bottom: 2px;
    margin-top: 10px;
    margin-bottom: 6px;
    letter-spacing: 0.5px;
  }
  .summary-text {
    font-size: 9.5pt;
    color: #334155;
    text-align: justify;
  }
  .job-header, .edu-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 6px;
  }
  .job-company, .edu-school {
    font-weight: 800;
    color: #0f172a;
    font-size: 10pt;
  }
  .job-role, .edu-degree {
    font-weight: 700;
    color: #334155;
    font-size: 9.5pt;
  }
  .job-dates, .edu-dates {
    font-size: 9pt;
    color: #64748b;
    font-style: italic;
  }
  .tech-line {
    font-size: 8.5pt;
    color: #475569;
    font-style: italic;
    margin-bottom: 3px;
  }
  ul.bullets {
    padding-left: 16px;
    margin-top: 2px;
  }
  ul.bullets li {
    font-size: 9.2pt;
    color: #334155;
    margin-bottom: 2px;
    line-height: 1.35;
  }
  .skills-category {
    font-size: 9.2pt;
    margin-bottom: 3px;
    color: #334155;
  }
  .skills-category strong {
    color: #0f172a;
  }
  .metric-bold {
    font-weight: 700;
    color: #0f172a;
  }
</style>
</head>
<body>

<div class="header">
  <div class="name">{{NAME}}</div>
  <div class="contact-bar">
    {{EMAIL}} | {{PHONE}} | {{LINKS}}
  </div>
</div>

{{SUMMARY_SECTION}}

{{EXPERIENCE_SECTION}}

{{SKILLS_SECTION}}

{{EDUCATION_SECTION}}

{{PROJECTS_SECTION}}

</body>
</html>"""


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
            
            bullets = "".join([f"<li>{b}</li>" for b in exp.get("description", [])])
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
        .replace("{{EMAIL}}", email)
        .replace("{{PHONE}}", phone)
        .replace("{{LINKS}}", link_html)
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
