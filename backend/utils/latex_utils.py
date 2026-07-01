"""
utils/latex_utils.py
LaTeX manipulation helpers: hotfix application, command extraction, JSON→LaTeX generation.
Extracted from main.py for separation of concerns.
"""

import re
import os
from typing import Optional


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

    # ── Inject spacing overrides after \\documentclass ───────────────────────
    ns  = f"{0.15 * spacing_scale:.3f}em"
    as_ = f"{0.10 * spacing_scale:.3f}em"
    ss  = f"{0.25 * spacing_scale:.3f}em"
    sls = f"{0.10 * spacing_scale:.3f}em"
    spacing_overrides = (
        f"\n\\def\\nameskip{{\\vspace{{{ns}}}}}\n"
        f"\\def\\addressskip{{\\vspace{{{as_}}}}}\n"
        f"\\def\\sectionskip{{\\vspace{{{ss}}}}}\n"
        f"\\def\\sectionlineskip{{\\vspace{{{sls}}}}}\n"
    )
    if linespread != 1.0:
        spacing_overrides += f"\\linespread{{{linespread:.2f}}}\n"

    for dc in ["\\documentclass{resume}", "\\documentclass[11pt]{resume}"]:
        if dc in fixed:
            fixed = fixed.replace(dc, dc + spacing_overrides, 1)
            break
    else:
        fixed = fixed.replace("\\begin{document}", spacing_overrides + "\\begin{document}", 1)

    # ── Escape unescaped special LaTeX chars ─────────────────────────────────
    fixed = re.sub(r'(?<!\\)&', r'\\&', fixed)
    fixed = re.sub(r'(?<!\\)%', r'\\%', fixed)
    fixed = re.sub(r'(?<!\\)_', r'\\_', fixed)
    # Undo double-escapes that arise from the above
    fixed = fixed.replace('\\\\&', '\\&')
    fixed = fixed.replace('\\\\%', '\\%')
    fixed = fixed.replace('\\\\_', '\\_')

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
    elif "\\usepackage[hidelinks]{hyperref}" in fixed:
        fixed = fixed.replace("\\usepackage[hidelinks]{hyperref}", HYPERREF_PATCH, 1)

    return fixed


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
    latex.append("\\documentclass{resume}")
    latex.append("\\usepackage[T1]{fontenc}")
    latex.append("\\newcommand\\mybar{\\kern1pt\\rule[-\\dp\\strutbox]{.8pt}{\\baselineskip}\\kern1pt}")
    latex.append("\\usepackage[left=0.40in,top=0.3in,right=0.40in,bottom=0.2in]{geometry}")
    latex.append("\\usepackage{fontawesome}")
    latex.append("\\usepackage{times}")
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

    latex.append("\\begin{document}")

    # Education
    edu_list = data.get("education", [])
    if edu_list:
        latex.append("\\begin{rSection}{Education}")
        for edu in edu_list:
            school = edu.get("institution") or edu.get("school") or ""
            degree = edu.get("degree", "")
            field  = edu.get("field_of_study", "")
            if field:
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

    # Technical Skills
    skills = data.get("skills", [])
    if skills:
        latex.append("\\begin{rSection}{Technical Skills}")
        latex.append("\\begin{tabular}{ @{} p{0.97\\textwidth} }")
        latex.append(", ".join(skills))
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
            dates   = f"{start} - {end}" if start and end else (start or end or exp.get("dates", ""))
            bullets = exp.get("description", [])
            latex.append(f"{{\\bf {company} \\mybar \\textnormal{{{role}}}}} \\hfill {{\\em {dates}}}")
            if bullets:
                latex.append("\\begin{itemize}\\setlength{\\itemsep}{-0.15em} \\setlength{\\parsep}{0em}")
                for b in bullets:
                    cb = b.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
                    latex.append(f"    \\item {cb}")
                latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    # Projects
    proj_list = data.get("projects", [])
    if proj_list:
        latex.append("\\begin{rSection}{Projects}")
        for proj in proj_list:
            title   = proj.get("title", "")
            bullets = proj.get("description", [])
            latex.append(f"{{\\bf {title}}} \\\\")
            for b in bullets:
                cb = b.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
                latex.append(f"- {cb} \\\\")
        if latex[-1].endswith(" \\\\"):
            latex[-1] = latex[-1][:-3]
        latex.append("\\end{rSection}")

    # Achievements
    ach = data.get("achievements", [])
    if ach:
        latex.append("\\begin{rSection}{Achievements \\& Leadership}")
        latex.append("\\begin{itemize}\\setlength{\\itemsep}{-0.2em} \\setlength{\\parsep}{0em}")
        for item in ach:
            ci = item.replace("&", "\\&").replace("%", "\\%").replace("_", "\\_")
            latex.append(f"    \\item {ci}")
        latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    latex.append("\\end{document}")
    return "\n".join(latex)
