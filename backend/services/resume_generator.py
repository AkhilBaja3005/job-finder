import os
# pyrefly: ignore [missing-import]
from jinja2 import Template
# pyrefly: ignore [missing-import]
from playwright.async_api import async_playwright

RESUME_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{{ resume.name }} - Resume</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        body {
            font-family: 'Times New Roman', Times, 'Didot', Georgia, serif;
            color: #000;
            line-height: 1.25;
            font-size: 10.5pt;
            background: #fff;
            padding: 0.3in 0.40in 0.2in 0.40in;
        }
        /* Strict single page container styling */
        .resume-page {
            max-width: 800px;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            height: 100%;
        }
        header {
            text-align: center;
            margin-bottom: 12px;
        }
        header h1 {
            font-size: 18pt;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }
        .contact-info {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 8px;
            font-size: 9.5pt;
        }
        .contact-info span {
            color: #444;
        }
        .contact-info a {
            color: #000;
            text-decoration: none;
        }
        .divider {
            color: #888;
            font-weight: normal;
            margin: 0 4px;
        }
        section {
            margin-bottom: 10px;
        }
        /* Section heading styled matching LaTeX resume.cls rSection */
        h2 {
            font-size: 11pt;
            font-weight: bold;
            text-transform: uppercase;
            border-bottom: 1px solid #000;
            padding-bottom: 1px;
            margin-top: 10px;
            margin-bottom: 5px;
            letter-spacing: 0.5px;
        }
        .skills-list {
            font-size: 10.5pt;
            margin-bottom: 2px;
        }
        .job-entry {
            margin-bottom: 8px;
        }
        /* Subheadings with left-aligned title/role and right-aligned dates */
        .job-header {
            display: flex;
            justify-content: space-between;
            font-weight: normal;
            font-size: 10.5pt;
            margin-bottom: 1px;
        }
        .job-title {
            font-weight: bold;
        }
        .job-date {
            font-style: italic;
        }
        .job-tech {
            font-style: italic;
            font-size: 9.5pt;
            color: #222;
            margin-bottom: 3px;
        }
        .job-bullets {
            margin-left: 14px;
            list-style-type: disc;
        }
        .job-bullets li {
            margin-bottom: 2px;
            font-size: 10pt;
            text-align: justify;
        }
        .edu-entry {
            margin-bottom: 5px;
            font-size: 10.5pt;
        }
        .edu-header {
            display: flex;
            justify-content: space-between;
        }
        .edu-inst {
            font-weight: bold;
        }
        .edu-date {
            font-style: italic;
        }
        .edu-degree {
            display: flex;
            justify-content: space-between;
            font-style: italic;
            font-size: 10pt;
        }
        .project-entry {
            margin-bottom: 6px;
            font-size: 10pt;
        }
        .project-title {
            font-weight: bold;
        }
        .project-desc {
            margin-left: 10px;
            margin-top: 1px;
            text-align: justify;
        }
        @media print {
            body {
                padding: 0;
            }
            @page {
                size: A4;
                margin: 0;
            }
        }
    </style>
</head>
<body>
    <div class="resume-page">
        <header>
            <h1>{{ resume.name }}</h1>
            <div class="contact-info">
                <span>{{ resume.email }}</span>
                {% for link in resume.links %}
                    <span class="divider">|</span>
                    <a href="{{ link }}">{{ link | replace('https://www.', '') | replace('http://', '') }}</a>
                {% endfor %}
            </div>
        </header>

        {% if resume.education %}
        <section>
            <h2>Education</h2>
            {% for edu in resume.education %}
                <div class="edu-entry">
                    <div class="edu-header">
                        <span class="edu-inst">{{ edu.institution }}</span>
                        <span class="edu-date">{{ edu.graduation_date }}</span>
                    </div>
                    <div class="edu-degree">
                        <span>{{ edu.degree }} in {{ edu.field_of_study }}</span>
                    </div>
                </div>
            {% endfor %}
        </section>
        {% endif %}

        {% if resume.skills %}
        <section>
            <h2>Technical Skills</h2>
            <p class="skills-list">
                <strong>Technical Skills:</strong> {{ resume.skills | join(', ') }}
            </p>
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
                            <li>{{ bullet }}</li>
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
                <div class="project-entry">
                    <div class="project-title">{{ proj.title }}</div>
                    {% if proj.get('description') %}
                        {% if proj.description is string %}
                            <div class="project-desc">&ndash; {{ proj.description }}</div>
                        {% else %}
                            {% for bullet in proj.description %}
                                <div class="project-desc">&ndash; {{ bullet }}</div>
                            {% endfor %}
                        {% endif %}
                    {% endif %}
                </div>
                {% endif %}
            {% endfor %}
        </section>
        {% endif %}
    </div>
</body>
</html>
"""

async def generate_pdf_resume(resume_data: dict, output_pdf_path: str):
    """
    Renders the structured resume data to HTML and uses Playwright
    to export it to a clean single-page PDF.
    """
    # Render Jinja Template
    template = Template(RESUME_HTML_TEMPLATE)
    html_content = template.render(resume=resume_data)
    
    # Save temp HTML file
    temp_html_path = output_pdf_path.replace(".pdf", ".html")
    with open(temp_html_path, "w") as f:
        f.write(html_content)
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Load the HTML content
        await page.goto(f"file://{os.path.abspath(temp_html_path)}")
        
        # Save as PDF matching A4 page size
        await page.pdf(
            path=output_pdf_path,
            format="A4",
            print_background=True,
            margin={"top": "0in", "bottom": "0in", "left": "0in", "right": "0in"}
        )
        await browser.close()
        
    # Clean up temp HTML
    if os.path.exists(temp_html_path):
        os.remove(temp_html_path)
