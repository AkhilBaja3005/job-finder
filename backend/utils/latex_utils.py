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
    found_first_brace = False
    for i in range(idx + len(cmd_name), len(latex_code)):
        char = latex_code[i]
        if char == '{':
            found_first_brace = True
            brace_count += 1
        elif char == '}':
            if found_first_brace:
                brace_count -= 1
                if brace_count == 0:
                    return latex_code[idx: i + 1]
    return None


def apply_latex_hotfix(
    code: str,
    spacing_scale: float = 1.0,
    linespread: float = 1.0,
    master_latex: Optional[str] = None,
    user_selected_skills: Optional[List[str]] = None,
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

    # ── Ensure Overleaf defaults to XeLaTeX compiler automatically ──────────────
    if "% !TEX program = xelatex" not in fixed:
        fixed = "% !TEX program = xelatex\n" + fixed

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

    # ── Ensure \address{...} is converted to \printaddress{...} inside \begin{document} to prevent Tectonic compilation errors ──
    addr_block = extract_latex_command(fixed, "\\address")
    if addr_block:
        print_addr_str = addr_block.replace("\\address{", "\\printaddress{")
        fixed = fixed.replace(addr_block, "")
        fixed = fixed.replace("\\begin{document}", "\\begin{document}\n" + print_addr_str, 1)

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

    # ── Fontspec + FontAwesome Setup with System Font Fallback ─────────────
    # Allows \faEnvelope, \faLinkedinSquare, \faMapMarker, \faPhone, \faGithub
    # while preserving Times Roman bold. Uses \IfFontExistsTF so it never fails on Linux/HF.
    fixed = re.sub(r'\\usepackage\{(lmodern|helvet|palatino|charter|bookman|courier|marvosym)\}', '', fixed)
    fixed = re.sub(r'\\usepackage\[T1\]\{fontenc\}', '', fixed)
    fixed = re.sub(r'\\usepackage\{times\}', '', fixed)
    if '\\usepackage{fontspec}' not in fixed:
        doc_class_end = fixed.find('\n', fixed.find('\\documentclass'))
        fontspec_preamble = (
            "\\usepackage{fontspec}\n"
            "\\IfFontExistsTF{Times New Roman}{\n"
            "  \\setmainfont{Times New Roman}[\n"
            "    BoldFont={Times New Roman Bold},\n"
            "    ItalicFont={Times New Roman Italic},\n"
            "    BoldItalicFont={Times New Roman Bold Italic}\n"
            "  ]\n"
            "}{\n"
            "  \\IfFontExistsTF{texgyretermes-regular.otf}{\n"
            "    \\setmainfont{texgyretermes-regular.otf}[\n"
            "      BoldFont={texgyretermes-bold.otf},\n"
            "      ItalicFont={texgyretermes-italic.otf},\n"
            "      BoldItalicFont={texgyretermes-bolditalic.otf}\n"
            "    ]\n"
            "  }{\\IfFontExistsTF{TeX Gyre Termes}{\\setmainfont{TeX Gyre Termes}}{}}\n"
            "}\n"
        )
        fixed = fixed[:doc_class_end + 1] + fontspec_preamble + fixed[doc_class_end + 1:]
    if '\\usepackage{fontawesome}' not in fixed:
        fixed = fixed.replace('\\usepackage{fontspec}', '\\usepackage{fontspec}\n\\usepackage{fontawesome}')
    # Standardize marvosym fallback back to FontAwesome
    fixed = re.sub(r'\\Letter\\\s*', r'\\faEnvelope\ ', fixed)
    fixed = re.sub(r'\\Telefon\\\s*', r'\\faPhone\ ', fixed)

    # ── Inject spacing_scale and linespread overrides ────────────────────────
    spacing_overrides = []
    if linespread != 1.0:
        spacing_overrides.append(f"\\linespread{{{linespread:.2f}}}\\selectfont")
    if spacing_scale != 1.0:
        sec_skip = max(0.2, 0.45 * spacing_scale)
        sec_line_skip = max(0.1, 0.25 * spacing_scale)
        name_sk = max(0.2, 0.45 * spacing_scale)
        addr_sk = max(0.2, 0.45 * spacing_scale)
        spacing_overrides.append(f"\\def\\sectionskip{{{sec_skip:.2f}em}}")
        spacing_overrides.append(f"\\def\\sectionlineskip{{{sec_line_skip:.2f}em}}")
        spacing_overrides.append(f"\\def\\nameskip{{{name_sk:.2f}em}}")
        spacing_overrides.append(f"\\def\\addressskip{{{addr_sk:.2f}em}}")

    if spacing_overrides:
        fixed = fixed.replace("\\begin{document}", "\\begin{document}\n" + "\n".join(spacing_overrides), 1)

    # ── Inject \frenchspacing to ensure clean, consistent inter-sentence spacing
    if "\\frenchspacing" not in fixed:
        fixed = fixed.replace("\\begin{document}", "\\frenchspacing\n\\begin{document}", 1)

    # ── Escape unescaped special LaTeX chars ─────────────────────────────────
    fixed = re.sub(r'(?<!\\)&', r'\\&', fixed)
    fixed = re.sub(r'(?<!\\)%', r'\\%', fixed)
    fixed = re.sub(r'(?<!\\)_', r'\\_', fixed)
    # Escape unescaped # characters in body text, preserving LaTeX macro parameter declarations like #1, #2 inside \newcommand / \def
    fixed = re.sub(r"(?<!\\)#(?!\d)", r'\\#', fixed)
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

    # ── Categorize uncategorized Technical Skills section using LLM ─────────────
    def _categorize_skills_sec(match):
        content = match.group(1).strip()
        # If it has bolded category headers (e.g. \textbf{Languages:}, \textbf{Category:}), keep it intact!
        if re.search(r'\\textbf\{[^}]+:\}', content):
            return match.group(0)  # Already cleanly categorized
        
        # Strip any single \textbf{Technical Skills:} prefix
        clean_content = re.sub(r'\\textbf\{Technical\s+Skills:\}\s*', '', content)
        clean_content = re.sub(r'\\vspace\{[^{}]*\}', '', clean_content).strip()
        
        from services.resume_parser import categorize_skills_with_llm
        cats = categorize_skills_with_llm(clean_content)
        
        lines = []
        for cat, s_list in cats.items():
            if s_list:
                # Skills values must NOT be bolded — only the category label is bold
                s_str = ", ".join(s_list) if isinstance(s_list, list) else str(s_list)
                s_str = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', s_str)  # strip any \textbf{} from skill values
                cat_name = cat.replace("&", "\\&").replace("%", "\\%")
                lines.append(f"\\textbf{{{cat_name}:}} {s_str} \\\\")
        if lines:
            if lines[-1].endswith(" \\\\"):
                lines[-1] = lines[-1][:-3]
            return f"\\begin{{rSection}}{{Technical Skills}}\n\\vspace{{-0.1em}}\n" + "\n".join(lines) + f"\n\\end{{rSection}}"
        return match.group(0)

    fixed = re.sub(r'\\begin\{rSection\}\{Technical\s+Skills\}(.*?)\\end\{rSection\}', _categorize_skills_sec, fixed, flags=re.DOTALL)

    # ── Remove stray tabular environment tags inserted by LLM or regex ───────
    fixed = re.sub(r'\\begin\{tabular\}\{[^{}]*\}', '', fixed)
    fixed = re.sub(r'\\end\{tabular\}', '', fixed)

    # ── Strip \textbf{} from skill values in Technical Skills (LLM sometimes bolds individual skills) ──
    def _strip_bold_from_skills(match):
        section_body = match.group(1)
        lines = section_body.split('\n')
        new_lines = []
        for line in lines:
            if line.strip().startswith('\\textbf{'):
                # Line format: \textbf{Label:} skill1, \textbf{skill2}, ...
                # Preserve \textbf{Label:} at start, strip \textbf{} from the rest
                m = re.match(r'^(\s*\\textbf\{[^{}]+\}\s*)(.*)$', line)
                if m:
                    prefix = m.group(1)
                    rest = m.group(2)
                    rest_clean = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', rest)
                    new_lines.append(prefix + rest_clean)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        return f'\\begin{{rSection}}{{Technical Skills}}\n' + '\n'.join(new_lines) + f'\n\\end{{rSection}}'
    fixed = re.sub(
        r'\\begin\{rSection\}\{Technical\s+Skills\}(.*?)\\end\{rSection\}',
        _strip_bold_from_skills,
        fixed,
        flags=re.DOTALL
    )

    # ── Remove separate Achievements & Leadership section if LLM created one ─────
    ach_sec_pattern = r'\\begin\{rSection\}\{Achievements\s*\\?&\s*Leadership\}\s*\\begin\{itemize\}.*?\\end\{itemize\}\s*\\end\{rSection\}'
    fixed = re.sub(ach_sec_pattern, '', fixed, flags=re.DOTALL)

    # ── Replace bare tildes (~40% → \textasciitilde40%) ───────────────────────
    fixed = re.sub(r'~\s*(?=\d|\\textbf|\{\\bf)', r'\\textasciitilde ', fixed)

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

    # ── Inject user-selected skills directly into Technical Skills section (bypassing LLM review) ──
    if user_selected_skills and len(user_selected_skills) > 0:
        clean_user_skills = [s.strip() for s in user_selected_skills if s and s.strip()]
        if clean_user_skills:
            def _inject_user_skills(match):
                sec_body = match.group(1)
                missing_to_add = [s for s in clean_user_skills if s.lower() not in sec_body.lower()]
                if not missing_to_add:
                    return match.group(0)
                
                lines = sec_body.split('\n')
                injected = False
                new_lines = []
                for line in lines:
                    if not injected and line.strip().startswith('\\textbf{'):
                        if line.strip().endswith('\\\\'):
                            new_line = line[:-2].rstrip() + ", " + ", ".join(missing_to_add) + " \\\\"
                        else:
                            new_line = line + ", " + ", ".join(missing_to_add)
                        new_lines.append(new_line)
                        injected = True
                    else:
                        new_lines.append(line)
                if not injected:
                    new_lines.append(f"\\textbf{{Additional Skills:}} {', '.join(missing_to_add)}")
                return f"\\begin{{rSection}}{{Technical Skills}}\n" + "\n".join(new_lines) + f"\n\\end{{rSection}}"

            fixed = re.sub(
                r'\\begin\{rSection\}\{Technical\s+Skills\}(.*?)\\end\{rSection\}',
                _inject_user_skills,
                fixed,
                flags=re.DOTALL
            )

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
            # Bold explicit key models, regulatory bodies, and frameworks requested in system rules
            explicit_bold_terms = ["RBI", "Reserve Bank of India", "XGBoost", "Naive Bayes", "Isolation Forest", "Azure OpenAI", "Cloudera ML"]
            for term in sorted(explicit_bold_terms, key=len, reverse=True):
                pattern = r'(?<!\\textbf\{)(?<!\w)(' + re.escape(term) + r')(?!\w)(?!\})'
                parts[i] = re.sub(pattern, r'\\textbf{\1}', parts[i])
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
        contact_parts.append(f"\\faEnvelope\\ \\href{{mailto:{email}}}{{{email}}}")
    if phone:
        contact_parts.append(f"\\faPhone\\ {phone}")
    if linkedin:
        li_user = linkedin.split("/in/")[-1].rstrip("/") if "/in/" in linkedin else linkedin
        contact_parts.append(f"\\href{{{linkedin}}}{{\\faLinkedinSquare\\ linkedin.com/in/{li_user}}}")
    if github:
        gh_user = github.split("github.com/")[-1].rstrip("/") if "github.com" in github else github
        contact_parts.append(f"\\href{{{github}}}{{\\faGithub\\ github.com/{gh_user}}}")

    address_line = " \\mybar ".join(contact_parts)

    latex = []
    latex.append("\\documentclass[12pt]{resume}")
    latex.append("\\usepackage{fontspec}")
    latex.append("\\IfFontExistsTF{Times New Roman}{")
    latex.append("  \\setmainfont{Times New Roman}[")
    latex.append("    BoldFont={Times New Roman Bold},")
    latex.append("    ItalicFont={Times New Roman Italic},")
    latex.append("    BoldItalicFont={Times New Roman Bold Italic}")
    latex.append("  ]")
    latex.append("}{")
    latex.append("  \\IfFontExistsTF{texgyretermes-regular.otf}{")
    latex.append("    \\setmainfont{texgyretermes-regular.otf}[")
    latex.append("      BoldFont={texgyretermes-bold.otf},")
    latex.append("      ItalicFont={texgyretermes-italic.otf},")
    latex.append("      BoldItalicFont={texgyretermes-bolditalic.otf}")
    latex.append("    ]")
    latex.append("  }{\\IfFontExistsTF{TeX Gyre Termes}{\\setmainfont{TeX Gyre Termes}}{}}")
    latex.append("}")
    latex.append("\\usepackage[left=0.35in,top=0.25in,right=0.35in,bottom=0.22in]{geometry}")
    latex.append("\\usepackage{fontawesome}")
    latex.append("\\usepackage{hyperref}")
    latex.append("\\newcommand\\mybar{\\kern1pt\\rule[-\\dp\\strutbox]{.8pt}{\\baselineskip}\\kern1pt}")
    latex.append("\\hypersetup{\n    colorlinks=false,\n    pdfborder={0 0 0}\n}")
    latex.append("\\renewcommand{\\labelitemi}{$\\bullet$}")
    latex.append("\\renewcommand{\\labelitemii}{$\\bullet$}")
    latex.append("\\frenchspacing")

    if master_latex:
        name_block    = extract_latex_command(master_latex, "\\name")
        address_block = extract_latex_command(master_latex, "\\address")
        latex.append(name_block if name_block else f"\\name{{{name}}}")
    else:
        latex.append(f"\\name{{{name}}}")

    latex.append("\\begin{document}")

    if master_latex and address_block:
        # Convert \address{...} to \printaddress{...} so it renders cleanly inside \begin{document}
        clean_addr = address_block.replace("\\address{", "\\printaddress{")
        latex.append(clean_addr)
    elif address_line:
        latex.append(f"\\printaddress{{{address_line}}}")

    skills = data.get("skills", [])
    skills_list = skills if isinstance(skills, list) else []

    # Professional Summary
    summary = data.get("summary", "")
    if summary:
        latex.append("\\vspace{-0.2em}")
        latex.append("\\begin{rSection}{Professional Summary}")
        latex.append(_format_bullet_bolding(summary, skills_list))
        latex.append("\\end{rSection}")

    # Work Experience
    exp_list = data.get("experience", [])
    if exp_list:
        latex.append("\\vspace{-0.3em}")
        latex.append("\\begin{rSection}{Work Experience}")
        for exp in exp_list:
            company = exp.get("company", "")
            role    = exp.get("role", "")
            start   = exp.get("start_date", "")
            end     = exp.get("end_date", "")
            dates   = f"{start} -- {end}" if start and end else (start or end or exp.get("dates", ""))
            bullets = exp.get("description", [])
            techs   = exp.get("technologies", "")
            latex.append(f"{{\\bf {company} \\mybar \\textnormal{{{role}}}}} \\hfill {{\\em {dates}}}")
            if techs:
                latex.append(f"\\\\ {{\\em Technologies: {techs}}}")
            if bullets:
                latex.append("\\vspace{-0.35em}")
                latex.append("\\begin{itemize}")
                latex.append("    \\setlength{\\itemsep}{-0.20em}")
                latex.append("    \\setlength{\\parsep}{0em}")
                for b in bullets:
                    formatted_b = _format_bullet_bolding(b, skills_list)
                    latex.append(f"    \\item {formatted_b}")
                latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    # Technical Skills
    if not skills or (isinstance(skills, dict) and len(skills) == 0):
        # Fallback: Collect technologies listed under Work Experience if skills dictionary is empty
        fallback_skills = []
        for exp in data.get("experience", []):
            techs = exp.get("technologies") or ""
            if techs:
                fallback_skills.extend([t.strip() for t in techs.split(",") if t.strip()])
        if fallback_skills:
            from services.resume_parser import categorize_skills_with_llm
            skills = categorize_skills_with_llm(list(set(fallback_skills)))

    if skills:
        latex.append("\\vspace{-0.3em}")
        latex.append("\\begin{rSection}{Technical Skills}")
        latex.append("\\vspace{-0.1em}")
        if isinstance(skills, list):
            from services.resume_parser import categorize_skills_with_llm
            skills = categorize_skills_with_llm(skills)

        if isinstance(skills, dict):
            for cat, s_list in skills.items():
                cat_name = cat.replace("&", "\\&").replace("%", "\\%")
                s_str = ", ".join(s_list) if isinstance(s_list, list) else str(s_list)
                # Skills values must NOT be bolded — strip any \textbf{} that came from the data
                s_str = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', s_str)
                latex.append(f"\\textbf{{{cat_name}:}} {s_str} \\\\")
            if latex[-1].endswith(" \\\\"):
                latex[-1] = latex[-1][:-3]
        else:
            latex.append(str(skills).replace("&", "\\&").replace("%", "\\%").replace("_", "\\_"))
        latex.append("\\end{rSection}")

    # Education
    edu_list = data.get("education", [])
    if edu_list:
        latex.append("\\vspace{-0.3em}")
        latex.append("\\begin{rSection}{Education}")
        for edu in edu_list:
            school = edu.get("institution") or edu.get("school") or ""
            degree = edu.get("degree", "")
            field  = edu.get("field_of_study", "")
            loc    = edu.get("location", "")
            if field and field.lower() not in degree.lower():
                degree = f"{degree} in {field}"
            start  = edu.get("start_date", "")
            grad   = edu.get("graduation_date") or edu.get("dates") or ""
            if start and grad and start.lower() not in grad.lower():
                dates = f"{start} -- {grad}"
            else:
                dates = grad or start
            gpa    = edu.get("gpa", "") or edu.get("cpi", "")
            if gpa and not gpa.lower().startswith(("cpi", "gpa", "grade", "percentage", "cgpa")):
                gpa = f"CPI: {gpa}"
            highlights = edu.get("highlights", [])
            latex.append(f"{{\\bf {school}}} \\hfill {{\\em {dates}}} \\\\")
            if loc:
                latex.append(f"{{\\textit{{{degree}}}}} \\hfill {{\\em {loc}}} \\\\")
            elif gpa:
                latex.append(f"{{\\textit{{{degree}}}}} \\hfill {{\\em {gpa}}} \\\\")
            else:
                latex.append(f"{{\\textit{{{degree}}}}} \\\\")
            if highlights:
                for h in highlights:
                    formatted_h = _format_bullet_bolding(h, skills_list)
                    latex.append(f"\\textit{{\\textbf{{{formatted_h}}}}} \\\\")
        if latex[-1].endswith(" \\\\"):
            latex[-1] = latex[-1][:-3]
        latex.append("\\end{rSection}")

    # Projects (Formatted as direct single-line items with \\ like user master resume)
    # Projects (Formatted as itemized section with colon separators, bolding & \textasciitilde)
    proj_list = data.get("projects", [])
    if proj_list:
        latex.append("\\begin{rSection}{Projects}")
        latex.append("\\vspace{-0.2em}")
        latex.append("\\begin{itemize}")
        latex.append("    \\setlength{\\itemsep}{-0.25em}")
        latex.append("    \\setlength{\\parsep}{0em}")
        for proj in proj_list:
            title   = proj.get("title", "")
            bullets = proj.get("description", [])
            body_text = ""
            if bullets:
                if isinstance(bullets, list):
                    body_text = " ".join([b.strip() for b in bullets])
                else:
                    body_text = str(bullets).strip()
            
            # Replace raw tildes before metrics (~40% -> \textasciitilde40%)
            body_text = re.sub(r'~\s*(?=\d|\\textbf)', r'\\textasciitilde ', body_text)
            formatted_body = _format_bullet_bolding(body_text, skills_list)
            
            if body_text:
                latex.append(f"    \\item \\textbf{{{title}:}} {formatted_body}")
            else:
                latex.append(f"    \\item \\textbf{{{title}}}")
        latex.append("\\end{itemize}")
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