import os
import re
# pyrefly: ignore [missing-import]
from jinja2 import Template
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright


def _latex_to_html(text: str) -> str:
    """
    Convert LaTeX inline commands in bullet text to HTML equivalents so
    that bold/italic/etc actually render in the Playwright PDF instead
    of printing as raw LaTeX source code.
    """
    if not text:
        return text
    # \textbf{word} → <strong>word</strong>
    text = re.sub(r'\\textbf\{([^}]*)\}', r'<strong>\1</strong>', text)
    # \textit{word} / \emph{word} → <em>word</em>
    text = re.sub(r'\\textit\{([^}]*)\}', r'<em>\1</em>', text)
    text = re.sub(r'\\emph\{([^}]*)\}', r'<em>\1</em>', text)
    # \% → %
    text = text.replace(r'\%', '%')
    # \& → &
    text = text.replace(r'\&', '&amp;')
    # ~  → non-breaking space
    text = text.replace('~', '\u00a0')
    # Remove any remaining lone backslash commands we don't handle
    text = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\[a-zA-Z]+', '', text)
    return text


RESUME_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ resume.name }} - Resume</title>
    <style>
        /* ── Page & font setup ─────────────────────────────────────────── */
        @page {
            size: A4;
            margin: 0.38in 0.42in 0.32in 0.42in;
        }
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        html, body {
            font-family: 'Times New Roman', Times, Georgia, serif;
            color: #000;
            line-height: 1.22;
            font-size: 10.2pt;
            background: #fff;
            /* Matches @page margin so screen preview is consistent */
            padding: 0.38in 0.42in 0.32in 0.42in;
        }
        .resume-page {
            width: 100%;
        }

        /* ── Header ────────────────────────────────────────────────────── */
        header {
            text-align: center;
            margin-bottom: 8px;
        }
        header h1 {
            font-size: 17pt;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 3px;
        }
        .contact-info {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 6px;
            font-size: 9.2pt;
            flex-wrap: wrap;
        }
        .contact-info span { color: #444; }
        .contact-info a { color: #000; text-decoration: none; }
        .divider { color: #888; font-weight: normal; }

        /* ── Section headings ──────────────────────────────────────────── */
        section { margin-bottom: 6px; }
        h2 {
            font-size: 10.5pt;
            font-weight: bold;
            text-transform: uppercase;
            border-bottom: 1px solid #000;
            padding-bottom: 1px;
            margin-top: 7px;
            margin-bottom: 4px;
            letter-spacing: 0.5px;
        }

        /* ── Skills ────────────────────────────────────────────────────── */
        .skills-list { font-size: 10pt; margin-bottom: 1px; }

        /* ── Experience ─────────────────────────────────────────────────── */
        .job-entry { margin-bottom: 5px; }
        .job-header {
            display: flex;
            justify-content: space-between;
            font-size: 10.2pt;
            margin-bottom: 1px;
        }
        .job-title { font-weight: bold; }
        .job-date { font-style: italic; white-space: nowrap; padding-left: 8px; }
        .job-tech { font-style: italic; font-size: 9.5pt; color: #222; margin-bottom: 2px; }
        .job-bullets {
            margin-left: 12px;
            list-style-type: disc;
        }
        .job-bullets li {
            margin-bottom: 1px;
            font-size: 9.9pt;
            text-align: justify;
            line-height: 1.22;
        }

        /* ── Education ─────────────────────────────────────────────────── */
        .edu-entry { margin-bottom: 4px; font-size: 10.2pt; }
        .edu-header { display: flex; justify-content: space-between; }
        .edu-inst { font-weight: bold; }
        .edu-date { font-style: italic; white-space: nowrap; padding-left: 8px; }
        .edu-degree {
            display: flex;
            justify-content: space-between;
            font-style: italic;
            font-size: 10pt;
        }

        /* ── Projects ──────────────────────────────────────────────────── */
        .project-entry { margin-bottom: 4px; font-size: 10pt; }
        .project-title { font-weight: bold; }
        .project-desc { margin-left: 10px; margin-top: 1px; text-align: justify; }

        /* ── Summary ───────────────────────────────────────────────────── */
        .summary-text {
            font-size: 10pt;
            line-height: 1.25;
            text-align: justify;
            margin-bottom: 2px;
        }

        /* ── Print: force single page ──────────────────────────────────── */
        @media print {
            body { padding: 0; }
            .resume-page { page-break-inside: avoid; }
        }
    </style>
</head>
<body>
    <div class="resume-page">
        <header>
            <h1>{{ resume.name }}</h1>
            <div class="contact-info">
                <span>{{ resume.email }}</span>
                {% if resume.phone %}
                    <span class="divider">|</span>
                    <span>{{ resume.phone }}</span>
                {% endif %}
                {% for link in resume.links %}
                    <span class="divider">|</span>
                    <a href="{{ link }}">{{ link | replace('https://www.', '') | replace('http://', '') }}</a>
                {% endfor %}
            </div>
        </header>

        {% if resume.summary %}
        <section>
            <h2>Professional Summary</h2>
            <div class="summary-text">{{ resume.summary | safe }}</div>
        </section>
        {% endif %}

        {% if resume.skills %}
        <section>
            <h2>Technical Skills</h2>
            {% if resume.skills is mapping %}
                <div class="skills-list">
                    {% for cat, items in resume.skills.items() %}
                        {% if items %}
                        <div style="margin-bottom: 2px;">
                            <strong>{{ cat }}:</strong> {{ items | join(', ') if items is iterable and items is not string else items }}
                        </div>
                        {% endif %}
                    {% endfor %}
                </div>
            {% elif resume.skills is iterable and resume.skills is not string %}
                <p class="skills-list">
                    <strong>Technical Skills:</strong> {{ resume.skills | join(', ') }}
                </p>
            {% else %}
                <p class="skills-list">
                    <strong>Technical Skills:</strong> {{ resume.skills }}
                </p>
            {% endif %}
        </section>
        {% endif %}

        {% if resume.experience %}
        <section>
            <h2>Work Experience</h2>
            {% for job in resume.experience %}
                <div class="job-entry">
                    <div class="job-header">
                        <span class="job-title">{{ job.company }} <span class="divider">|</span> <span style="font-weight: normal;">{{ job.role }}</span></span>
                        <span class="job-date">{{ job.start_date }} &ndash; {{ job.end_date }}</span>
                    </div>
                    <ul class="job-bullets">
                        {% for bullet in job.description %}
                            <li>{{ bullet | safe }}</li>
                        {% endfor %}
                    </ul>
                </div>
            {% endfor %}
        </section>
        {% endif %}

        {% if resume.projects %}
        <section>
            <h2>Projects</h2>
            {% for proj in resume.projects %}
                {% if proj.get('title') %}
                <div class="project-entry" style="margin-bottom: 3px; font-size: 9.9pt; text-align: justify; line-height: 1.22;">
                    <strong>{{ proj.title }}</strong> &ndash;
                    {% if proj.description is string %}
                        {{ proj.description | safe }}
                    {% else %}
                        {{ proj.description | join(' ') | safe }}
                    {% endif %}
                </div>
                {% endif %}
            {% endfor %}
        </section>
        {% endif %}

        {% if resume.education %}
        <section>
            <h2>Education</h2>
            {% for edu in resume.education %}
                <div class="edu-entry">
                    <div class="edu-header">
                        <span class="edu-inst">{{ edu.institution }}{% if edu.location %} &bull; {{ edu.location }}{% endif %}</span>
                        <span class="edu-date">{% if edu.start_date and edu.graduation_date and edu.start_date.lower() not in edu.graduation_date.lower() %}{{ edu.start_date }} &ndash; {{ edu.graduation_date }}{% else %}{{ edu.graduation_date or edu.start_date or edu.dates }}{% endif %}</span>
                    </div>
                    <div class="edu-degree">
                        <span>
                            {% if edu.degree and edu.field_of_study %}
                                {{ edu.degree }} in {{ edu.field_of_study }}
                            {% else %}
                                {{ edu.degree or edu.field_of_study }}
                            {% endif %}
                        </span>
                        {% if edu.gpa or edu.cpi %}<span>CPI/GPA: {{ edu.gpa or edu.cpi }}</span>{% endif %}
                    </div>
                    {% if edu.highlights %}
                    <div style="font-size: 9.2pt; color: #333; margin-top: 1px;">
                        {% for h in edu.highlights %}<div>&bull; {{ h }}</div>{% endfor %}
                    </div>
                    {% endif %}
                </div>
            {% endfor %}
        </section>
        {% endif %}
    </div>
</body>
</html>
"""


def _prepare_resume_for_template(resume_data: dict) -> dict:
    """
    Pre-process resume_data so that all bullet strings have LaTeX commands
    converted to HTML before being injected into the Jinja template.
    """
    import copy
    data = copy.deepcopy(resume_data)

    # Convert summary
    if data.get('summary'):
        data['summary'] = _latex_to_html(data['summary'])

    # Convert experience bullets
    for job in data.get('experience', []):
        job['description'] = [_latex_to_html(b) for b in job.get('description', [])]

    # Convert project bullets
    for proj in data.get('projects', []):
        desc = proj.get('description')
        if isinstance(desc, list):
            proj['description'] = [_latex_to_html(b) for b in desc]
        elif isinstance(desc, str):
            proj['description'] = _latex_to_html(desc)

    return data


async def generate_pdf_resume(resume_data: dict, output_pdf_path: str):
    """
    Renders the structured resume data to HTML and uses Playwright
    to export it to a clean single-page PDF.
    """
    # Pre-process: convert LaTeX inline commands → HTML
    processed = _prepare_resume_for_template(resume_data)

    # Render Jinja Template
    template = Template(RESUME_HTML_TEMPLATE)
    html_content = template.render(resume=processed)

    # Save temp HTML file
    temp_html_path = output_pdf_path.replace(".pdf", ".html")
    with open(temp_html_path, "w") as f:
        f.write(html_content)

    # Reuse app shared Playwright browser if ready; fallback to fresh launch if startup isn't complete
    try:
        from services.scraper import _shared_browser
        browser = _shared_browser
    except Exception:
        browser = None

    if browser and browser.is_connected():
        page = await browser.new_page()
        should_close_browser = False
    else:
        p_temp = await async_playwright().start()
        browser = await p_temp.chromium.launch(headless=True)
        page = await browser.new_page()
        should_close_browser = True

    try:
        # Load the HTML content
        await page.goto(f"file://{os.path.abspath(temp_html_path)}")

        # ── Vertical Page Occupancy Detector ─────────────────────────────────
        # Printable A4 height inside Chromium margins (0.38in top/bottom) ~ 1040px at 96 DPI
        content_height = await page.evaluate("document.querySelector('.resume-page').offsetHeight")
        target_height = 1040.0
        occupancy_ratio = round(content_height / target_height, 2)
        print(f"[PDF Occupancy Detector] Rendered DOM Height: {content_height}px (Occupancy Ratio: {int(occupancy_ratio * 100)}%).")

        if content_height < 920:
            # Underfilled resume (<88% occupancy) — Inject Auto-Vertical Compensation Spacing
            print("[PDF Occupancy Detector] Resume is underfilled (<88% occupied). Applying Auto-Vertical Compensation Spacing...")
            await page.evaluate("""() => {
                const style = document.createElement('style');
                style.textContent = `
                    section { margin-bottom: 9px !important; }
                    h2 { margin-top: 10px !important; margin-bottom: 6px !important; }
                    .job-entry { margin-bottom: 7px !important; }
                    .job-bullets li { margin-bottom: 2.5px !important; line-height: 1.28 !important; }
                    .summary-text { line-height: 1.30 !important; margin-bottom: 4px !important; }
                    .skills-list { line-height: 1.28 !important; }
                `;
                document.head.appendChild(style);
            }""")
            adjusted_height = await page.evaluate("document.querySelector('.resume-page').offsetHeight")
            print(f"[PDF Occupancy Detector] Auto-Compensation Applied! New DOM Height: {adjusted_height}px ({int(round(adjusted_height / target_height, 2) * 100)}% occupied).")
        elif content_height > 1040:
            # Overflowing resume (>100% height) — Tighten spacing to enforce 1-page compliance
            print("[PDF Occupancy Detector] Resume exceeds 1 page height. Tightening vertical spacing...")
            await page.evaluate("""() => {
                const style = document.createElement('style');
                style.textContent = `
                    section { margin-bottom: 4px !important; }
                    h2 { margin-top: 5px !important; margin-bottom: 2px !important; }
                    .job-entry { margin-bottom: 3px !important; }
                    .job-bullets li { margin-bottom: 0px !important; line-height: 1.18 !important; }
                `;
                document.head.appendChild(style);
            }""")

        # Save as PDF — let @page CSS handle all margins, so pass zeros here
        await page.pdf(
            path=output_pdf_path,
            format="A4",
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"}
        )
    finally:
        await page.close()
        if should_close_browser:
            await browser.close()

    # Clean up temp HTML
    if os.path.exists(temp_html_path):
        os.remove(temp_html_path)

    # ── PDF verification check integration ──────────────────────────────────
    import subprocess

    # 1. Page count check
    try:
        pdfinfo_res = subprocess.run(["pdfinfo", output_pdf_path], capture_output=True, text=True, check=True)
        match = re.search(r"^Pages:\s+(\d+)\s*$", pdfinfo_res.stdout, re.MULTILINE)
        if match:
            pages = int(match.group(1))
            print(f"[PDF Verification] Generated PDF has {pages} pages.")
            if pages > 1:
                print(f"[WARNING] Resume PDF exceeds 1 page! Pages found: {pages}")
    except Exception as e:
        print(f"[PDF Verification Info] pdfinfo check skipped: {e}")

    # 2. ATS text layer check
    try:
        pdftotext_res = subprocess.run(["pdftotext", "-layout", output_pdf_path, "-"], capture_output=True, text=True, check=True)
        extracted = pdftotext_res.stdout.strip()
        char_count = len(extracted)
        print(f"[PDF Verification] Extracted ATS text layer size: {char_count} chars.")
        if char_count < 100:
            print("[WARNING] Resume PDF text layer is critically low or unreadable by ATS parsers!")
    except Exception as e:
        print(f"[PDF Verification Info] pdftotext check skipped: {e}")
