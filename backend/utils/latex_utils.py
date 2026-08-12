"""
utils/latex_utils.py
LaTeX manipulation helpers: hotfix application, command extraction, JSON→LaTeX generation.
Extracted from main.py for separation of concerns.
"""

import re
import os
from typing import Optional, List


UPLOAD_DIR = "./uploads"


def extract_latex_command(latex_code: str, cmd_name: str) -> Optional[str]:
    """
    Extract the full block of a LaTeX command including its brace-delimited argument.
    e.g. extract_latex_command(code, "\\name") → "\\name{John Doe}"
    Handles nested braces correctly via counting.
    """
    idx = latex_code.find(cmd_name)
    if idx == -1:
        return None
    brace_count = 0
    start_idx = -1
    for i in range(idx + len(cmd_name), len(latex_code)):
        char = latex_code[i]
        if char == '{':
            if brace_count == 0:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0:
                return latex_code[idx: i + 1]
    return None


def apply_latex_hotfix(
    code: str,
    spacing_scale: float = 1.0,
    linespread: float = 1.0,
    master_latex: Optional[str] = None,
) -> str:
    """
    Apply a battery of deterministic post-processing fixes to LLM-generated LaTeX:
    - Strip conversational preamble/postamble
    - Restore \\name and \\address from master (zero metadata loss)
    - Inject calibrated spacing overrides
    - Fix hyperref package to hide link borders
    - Escape unescaped special chars (&, %, _)
    - Fix itemize spacing
    - Fix tabular layout for Technical Skills
    """
    fixed = code

    # ── Strip conversational intro/outro ─────────────────────────────────────
    doc_class_idx = fixed.find("\\documentclass")
    if doc_class_idx != -1:
        fixed = fixed[doc_class_idx:]
    end_doc_idx = fixed.find("\\end{document}")
    if end_doc_idx != -1:
        fixed = fixed[:end_doc_idx + len("\\end{document}")]

    # ── Restore \\name and \\address from master verbatim ────────────────────
    if master_latex:
        name_block    = extract_latex_command(master_latex, "\\name")
        address_block = extract_latex_command(master_latex, "\\address")

        if name_block:
            gen_name = extract_latex_command(fixed, "\\name")
            if gen_name:
                fixed = fixed.replace(gen_name, name_block, 1)
            else:
                fixed = fixed.replace("\\begin{document}", name_block + "\n\\begin{document}", 1)

        if address_block:
            gen_addr = extract_latex_command(fixed, "\\address")
            if gen_addr:
                fixed = fixed.replace(gen_addr, address_block, 1)
            else:
                fixed = fixed.replace("\\begin{document}", address_block + "\n\\begin{document}", 1)

    # ── Strip any existing spacing def overrides (we re-inject below) ────────
    for pattern in [
        r'\\def\\sectionskip\{([^{}]*|\{[^{}]*\})*\}',
        r'\\def\\sectionlineskip\{([^{}]*|\{[^{}]*\})*\}',
        r'\\def\\nameskip\{([^{}]*|\{[^{}]*\})*\}',
        r'\\def\\addressskip\{([^{}]*|\{[^{}]*\})*\}',
        r'\\renewcommand\{\\sectionskip\}\{([^{}]*|\{[^{}]*\})*\}',
        r'\\renewcommand\{\\sectionlineskip\}\{([^{}]*|\{[^{}]*\})*\}',
        r'\\renewcommand\{\\nameskip\}\{([^{}]*|\{[^{}]*\})*\}',
        r'\\renewcommand\{\\addressskip\}\{([^{}]*|\{[^{}]*\})*\}',
    ]:
        fixed = re.sub(pattern, '', fixed)

    # ── Tighten geometry margins (force single-page fit) ─────────────────────
    fixed = re.sub(
        r'\\usepackage\[[^\]]*\]\{geometry\}',
        r'\\usepackage[left=0.35in,top=0.25in,right=0.35in,bottom=0.20in]{geometry}',
        fixed,
    )

    # ── Inject spacing overrides after \\documentclass ───────────────────────
    ns  = f"{0.10 * spacing_scale:.3f}em"
    as_ = f"{0.06 * spacing_scale:.3f}em"
    ss  = f"{0.20 * spacing_scale:.3f}em"
    sls = f"{0.08 * spacing_scale:.3f}em"
    spacing_overrides = (
        f"\n\\def\\nameskip{{\\vspace{{{ns}}}}}\n"
        f"\\def\\addressskip{{\\vspace{{{as_}}}}}\n"
        f"\\def\\sectionskip{{\\vspace{{{ss}}}}}\n"
        f"\\def\\sectionlineskip{{\\vspace{{{sls}}}}}\n"
        "\\renewcommand{\\smallskip}{\\vspace{1.5pt}}\n"
    )
    if linespread != 1.0:
        spacing_overrides += f"\\linespread{{{linespread:.2f}}}\n"

    for dc in ["\\documentclass{resume}", "\\documentclass[11pt]{resume}"]:
        if dc in fixed:
            fixed = fixed.replace(dc, dc + spacing_overrides, 1)
            break
    else:
        fixed = fixed.replace("\\begin{document}", spacing_overrides + "\\begin{document}", 1)

    # ── Remove empty itemize blocks that cause LaTeX 'missing \item' errors ──
    fixed = re.sub(r'\\begin\{itemize\}(\\setlength\{[^}]*\})*\s*\\end\{itemize\}', '', fixed)

    # ── Compress itemize / list environment padding & force second-level bullets to dots (not dashes) ──
    fixed = fixed.replace("\\begin{itemize}", "\\begin{itemize}\\setlength{\\itemsep}{-1.5pt}\\setlength{\\parsep}{0pt}\\setlength{\\topsep}{0pt}")

    # Ensure itemize bullets render as solid dots (\textbullet) across all levels
    if "\\renewcommand{\\labelitemi}" not in fixed:
        fixed = fixed.replace("\\begin{document}", "\\renewcommand{\\labelitemi}{\\textbullet}\n\\renewcommand{\\labelitemii}{\\textbullet}\n\\begin{document}", 1)
    elif "\\renewcommand{\\labelitemii}" not in fixed:
        fixed = fixed.replace("\\begin{document}", "\\renewcommand{\\labelitemii}{\\textbullet}\n\\begin{document}", 1)

    # ── Replace outdated times package with modern lmodern (ensures full bold weight rendering)
    fixed = fixed.replace("\\usepackage{times}", "\\usepackage{lmodern}")

    # ── Inject \frenchspacing to ensure clean, consistent inter-sentence spacing
    if "\\frenchspacing" not in fixed:
        fixed = fixed.replace("\\begin{document}", "\\frenchspacing\n\\begin{document}", 1)

    # ── Escape unescaped special LaTeX chars ─────────────────────────────────
    fixed = re.sub(r'(?<!\\)&', r'\\&', fixed)
    fixed = re.sub(r'(?<!\\)%', r'\\%', fixed)
    fixed = re.sub(r'(?<!\\)_', r'\\_', fixed)
    fixed = re.sub(r'(?<!\\)#', r'\\#', fixed)
    # Undo double-escapes that arise from the above
    fixed = fixed.replace('\\\\&', '\\&')
    fixed = fixed.replace('\\\\%', '\\%')
    fixed = fixed.replace('\\\\_', '\\_')
    fixed = fixed.replace('\\\\#', '\\#')

    # ── Remove stray \\ before \begin{itemize} (causes big gaps) ────────────
    fixed = re.sub(
        r'\\\\(\s*|\\n|\n|\\vspace\{-?\d+(\.\d+)?(em|ex|pt|in|cm)\})*\\begin\{itemize\}',
        r'\n\\begin{itemize}',
        fixed,
    )

    # ── Force p{0.97\textwidth} tabular for skills (prevents overflow) ───────
    fixed = re.sub(
        r'\\begin\{tabular\}\{\s*@\{\}\s*>\s*\{\}\s*l\s*@\{\s*\\hspace\{\s*\d+ex\s*\}\s*\}\s*l\s*\}',
        r'\\begin{tabular}{ @{} p{0.97\\textwidth} }',
        fixed,
    )

    # ── Fix hyperref to hide link borders ────────────────────────────────────
    HYPERREF_PATCH = (
        "\\usepackage[hidelinks]{hyperref}\n"
        "\\makeatletter\n"
        "\\providecommand{\\Hy@colorlink}[1]{}\n"
        "\\providecommand{\\Hy@endcolorlink}{}\n"
        "\\providecommand{\\@urlcolor}{black}\n"
        "\\makeatother"
    )
    if "\\usepackage{hyperref}" in fixed and "[hidelinks]" not in fixed:
        fixed = fixed.replace("\\usepackage{hyperref}", HYPERREF_PATCH, 1)
    # ── Auto-bold Inline Awards, Honors & Certificates generically if LLM missed \textbf{} ──
    award_patterns = [
        r'(?<!\\textbf\{)([A-Z][A-Za-z0-9\s]{2,40}\s+Award\b)(?!\})',
        r'(?<!\\textbf\{)([A-Z][A-Za-z0-9\s]{2,40}\s+Certificate\s+of\s+[A-Za-z0-9\s]+)(?!\})',
        r'(?<!\\textbf\{)(Certificate\s+of\s+Recognition)(?!\})',
        r'(?<!\\textbf\{)([A-Z][A-Za-z0-9\s]{2,40}\s+Honor\b)(?!\})',
        r'(?<!\\textbf\{)([A-Z][A-Za-z0-9\s]{2,40}\s+Fellowship\b)(?!\})'
    ]
    for pat in award_patterns:
        fixed = re.sub(pat, r'\\textbf{\1}', fixed)

    return fixed


def _format_bullet_bolding(text: str, dynamic_skills: Optional[List[str]] = None) -> str:
    """Convert Markdown **bold**, short colon-prefix labels, metrics, and technical terms/skills into LaTeX \\textbf{}."""
    if not text:
        return ""
    
    t = text
    # 1. Convert markdown bold **text** -> \textbf{text}
    t = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', t)
    
    # 2. Bold short leading labels before a colon if not already bolded
    if ":" in t and not t.lower().startswith(("http", "https", "e.g.", "note:", "result:")) and not t.startswith("\\textbf{"):
        prefix, rest = t.split(":", 1)
        if len(prefix.split()) <= 6:
            t = f"\\textbf{{{prefix.strip()}:}} {rest.strip()}"

    # Build dynamic tech keywords from candidate's skills + common domain frameworks
    keywords_to_bold = set()
    if dynamic_skills:
        for s in dynamic_skills:
            if len(s.strip()) > 1:
                keywords_to_bold.add(s.strip())

    # 3. Automatic Metric & Technology Bolding
    parts = re.split(r'(\\textbf\{[^{}]*\})', t)
    for i in range(len(parts)):
        if not parts[i].startswith('\\textbf{'):
            # Bold percentage metrics, currencies, scale numbers
            parts[i] = re.sub(r'(?<!\w)(\d+(?:\.\d+)?%|\$[\d\.]+[MKB]?\+?|£[\d\.]+[MKB]?\+?|\b\d+(?:,\d{3})+\+?|\b\d+[MK]|\b\d+Cr\+?|\b\d+\+)(?!\w)', r'\\textbf{\1}', parts[i])
            # Bold dynamic skills extracted from candidate profile
            for kw in keywords_to_bold:
                pattern = r'(?<!\w)(' + re.escape(kw) + r')(?!\w)'
                parts[i] = re.sub(pattern, r'\\textbf{\1}', parts[i])
    t = "".join(parts)

    # 4. Clean LaTeX escape chars without destroying \textbf{}
    t = re.sub(r'(?<!\\)&', r'\\&', t)
    t = re.sub(r'(?<!\\)%', r'\\%', t)
    t = re.sub(r'(?<!\\)_', r'\\_', t)
    return t


def generate_latex_from_json(data: dict, master_latex: Optional[str] = None) -> str:
    """
    Generate a canonical LaTeX resume from structured JSON data.
    If master_latex is provided, \\name and \\address are copied verbatim from it.
    """
    name     = data.get("name", "Name")
    email    = data.get("email", "")
    phone    = data.get("phone", "")
    linkedin = data.get("linkedin", "")
    github   = data.get("github", "")

    for link in data.get("links", []):
        if "linkedin.com" in link:
            linkedin = link
        elif "github.com" in link:
            github = link

    contact_parts = []
    if email:
        contact_parts.append(f"\\faEnvelope{{ {email} }}")
    if phone:
        contact_parts.append(f"\\faPhone{{ {phone} }}")
    if linkedin:
        li_user = linkedin.split("/")[-1] or linkedin
        contact_parts.append(f"\\href{{{linkedin}}}{{\\faLinkedinSquare{{ {li_user} }}}}")
    if github:
        gh_user = github.split("/")[-1] or github
        contact_parts.append(f"\\href{{{github}}}{{\\faGithub{{ {gh_user} }}}}")

    address_line = " \\mybar ".join(contact_parts)

    latex = []
    latex.append("\\documentclass[12pt]{resume}")
    latex.append("\\usepackage[T1]{fontenc}")
    latex.append("\\newcommand\\mybar{\\kern1pt\\rule[-\\dp\\strutbox]{.8pt}{\\baselineskip}\\kern1pt}")
    latex.append("\\usepackage[left=0.35in,top=0.25in,right=0.35in,bottom=0.22in]{geometry}")
    latex.append("\\usepackage{fontawesome}")
    latex.append("\\usepackage{lmodern}")
    latex.append("\\usepackage[hidelinks]{hyperref}")

    if master_latex:
        name_block    = extract_latex_command(master_latex, "\\name")
        address_block = extract_latex_command(master_latex, "\\address")
        latex.append(name_block if name_block else f"\\name{{{name}}}")
        if address_block:
            latex.append(address_block)
        elif address_line:
            latex.append(f"\\address{{{address_line}}}")
    else:
        latex.append(f"\\name{{{name}}}")
        if address_line:
            latex.append(f"\\address{{{address_line}}}")

    latex.append("\\frenchspacing")
    latex.append("\\begin{document}")

    skills = data.get("skills", [])
    skills_list = skills if isinstance(skills, list) else []

    # Professional Summary
    summary = data.get("summary", "")
    if summary:
        latex.append("\\begin{rSection}{Professional Summary}")
        latex.append("\\begin{tabular}{ @{} p{0.97\\textwidth} }")
        latex.append(_format_bullet_bolding(summary, skills_list))
        latex.append("\\end{tabular}")
        latex.append("\\end{rSection}")

    # Work Experience
    exp_list = data.get("experience", [])
    if exp_list:
        latex.append("\\begin{rSection}{Work Experience}")
        for exp in exp_list:
            company = exp.get("company", "")
            role    = exp.get("role", "")
            start   = exp.get("start_date", "")
            end     = exp.get("end_date", "")
            dates   = f"{start} -- {end}" if start and end else (start or end or exp.get("dates", ""))
            bullets = exp.get("description", [])
            latex.append(f"{{\\bf {company} \\mybar \\textnormal{{{role}}}}} \\hfill {{\\em {dates}}}")
            if bullets:
                latex.append("\\begin{itemize}\\setlength{\\itemsep}{-0.20em} \\setlength{\\parsep}{0em}")
                for b in bullets:
                    formatted_b = _format_bullet_bolding(b, skills_list)
                    latex.append(f"    \\item {formatted_b}")
                latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    # Technical Skills
    if skills:
        latex.append("\\begin{rSection}{Technical Skills}")
        latex.append("\\begin{tabular}{ @{} p{0.97\\textwidth} }")
        if isinstance(skills, list):
            # Render plain text skills without extra individual bolding
            latex.append(", ".join([s.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_") for s in skills]))
        else:
            latex.append(str(skills).replace("&", "\\&").replace("%", "\\%").replace("_", "\\_"))
        latex.append("\\end{tabular}")
        latex.append("\\end{rSection}")

    # Education
    edu_list = data.get("education", [])
    if edu_list:
        latex.append("\\begin{rSection}{Education}")
        for edu in edu_list:
            school = edu.get("institution") or edu.get("school") or ""
            degree = edu.get("degree", "")
            field  = edu.get("field_of_study", "")
            if field and field.lower() not in degree.lower():
                degree = f"{degree} in {field}"
            dates  = edu.get("graduation_date") or edu.get("dates") or ""
            gpa    = edu.get("gpa", "") or edu.get("cpi", "")
            if gpa and not gpa.lower().startswith(("cpi", "gpa", "grade", "percentage", "cgpa")):
                gpa = f"CPI: {gpa}"
            latex.append(f"{{\\bf {school}}} \\hfill {{\\em {dates}}} \\\\")
            if gpa:
                latex.append(f"{{\\textit{{{degree}}}}} \\hfill {{\\em {gpa}}} \\\\")
            else:
                latex.append(f"{{\\textit{{{degree}}}}} \\\\")
        if latex[-1].endswith(" \\\\"):
            latex[-1] = latex[-1][:-3]
        latex.append("\\end{rSection}")

    # Projects (Formatted as direct single-line items with \\ like user master resume)
    proj_list = data.get("projects", [])
    if proj_list:
        latex.append("\\begin{rSection}{Projects}")
        for i, proj in enumerate(proj_list):
            title   = proj.get("title", "")
            bullets = proj.get("description", [])
            latex.append(f"{{\\bf {title}}}")
            if bullets:
                for j, b in enumerate(bullets):
                    formatted_b = _format_bullet_bolding(b, skills_list)
                    # Render as hyphenated one-liner text lines ending with \\
                    prefix = "- " if not formatted_b.strip().startswith("-") else ""
                    latex.append(f"{prefix}{formatted_b} \\\\")
            if i < len(proj_list) - 1 and latex[-1].endswith(" \\\\"):
                pass
        if latex[-1].endswith(" \\\\"):
            latex[-1] = latex[-1][:-3]
        latex.append("\\end{rSection}")

    # Achievements & Leadership (Rendered as clean single section or inline highlights)
    ach = data.get("achievements", [])
    if ach:
        latex.append("\\begin{rSection}{Achievements \\& Leadership}")
        if len(ach) == 1:
            latex.append(_format_bullet_bolding(ach[0], skills_list))
        else:
            latex.append("\\begin{itemize}\\setlength{\\itemsep}{-1pt}\\setlength{\\parsep}{0pt}\\setlength{\\topsep}{0pt}\\setlength{\\itemsep}{-0.2em} \\setlength{\\parsep}{0em}")
            for item in ach:
                latex.append(f"    \\item {_format_bullet_bolding(item, skills_list)}")
            latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    latex.append("\\end{document}")
    return "\n".join(latex)