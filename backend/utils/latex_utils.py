"""
utils/latex_utils.py
LaTeX manipulation helpers: hotfix application, command extraction, JSON→LaTeX generation.
Extracted from main.py for separation of concerns.
"""

import re
import os
import json
from typing import Optional, List, Dict, Set, Any


UPLOAD_DIR = "./uploads"


def extract_latex_command(latex_code: str, cmd_name: str) -> Optional[str]:
    """
    Extract the full block of a LaTeX command including its brace-delimited argument.
    e.g. extract_latex_command(code, "\\name") → "\\name{John Doe}"
    Handles nested braces correctly via counting, ignores comments, and enforces word boundaries.
    """
    escaped_cmd = re.escape(cmd_name)
    # Match cmd_name on lines that are not comments, followed by non-alpha or {
    pattern = re.compile(rf"(?m)^(?![ \t]*%)[^%\n]*?({escaped_cmd}(?![a-zA-Z]))")

    for match in pattern.finditer(latex_code):
        idx = match.start(1)
        brace_count = 0
        found_first_brace = False
        start_search = idx + len(cmd_name)

        # Ensure only whitespace or comments between cmd_name and {
        valid = True
        j = start_search
        while j < len(latex_code):
            char = latex_code[j]
            if char in " \t\r\n":
                j += 1
                continue
            elif char == "%":
                eol = latex_code.find("\n", j)
                j = len(latex_code) if eol == -1 else eol + 1
                continue
            elif char == "{":
                found_first_brace = True
                brace_count = 1
                break
            else:
                valid = False
                break

        if not valid or not found_first_brace:
            continue

        for i in range(j + 1, len(latex_code)):
            char = latex_code[i]
            if char == "%":
                eol = latex_code.find("\n", i)
                i = len(latex_code) if eol == -1 else eol
                continue
            elif char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return latex_code[idx : i + 1]
    return None


def categorize_skill(skill: str) -> str:
    s = skill.strip().lower()
    languages = {"python", "sql", "c++", "c", "java", "javascript", "typescript", "golang", "go", "rust", "c#", "scala", "r", "bash", "shell", "ruby", "php", "swift", "kotlin", "html", "css"}
    if s in languages or any(s == f"{l} programming" for l in languages):
        return "Languages"
    
    data_platforms = {"spark", "pyspark", "hadoop", "kafka", "postgresql", "postgres", "mongodb", "redis", "snowflake", "bigquery", "databricks", "azure", "aws", "gcp", "cloudera", "sas", "mysql", "elasticsearch", "cassandra", "dynamodb", "airflow"}
    if any(k in s for k in data_platforms):
        return "Data & Platforms"

    software_infra = {"docker", "kubernetes", "k8s", "rancher", "jenkins", "rabbitmq", "git", "ci/cd", "cicd", "microservices", "linux", "distributed systems", "unit testing", "ast", "static analysis", "rapid prototyping", "agile", "scrum", "system design", "grpc", "rest", "graphql"}
    if any(k in s for k in software_infra):
        return "Software & Infrastructure"
    
    return "AI/ML & GenAI"


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

    # ── Strip conversational intro/outro ─────────────────────────────────────
    doc_class_idx = fixed.find("\\documentclass")
    if doc_class_idx != -1:
        fixed = fixed[doc_class_idx:]
    end_doc_idx = fixed.find("\\end{document}")
    if end_doc_idx != -1:
        fixed = fixed[:end_doc_idx + len("\\end{document}")]

    # ── Restore \\name, \\address, and categorized Technical Skills from master verbatim ────────────────────
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

        # If master resume has a categorized Technical Skills section, extract and preserve its exact structure
        master_skills_match = re.search(r'(\\begin\{rSection\}\{Technical\s+Skills\}.*?\\end\{rSection\})', master_latex, re.DOTALL)
        if master_skills_match:
            master_skills_block = master_skills_match.group(1)
            # Only restore if master actually has categorized headers
            if re.search(r'\\textbf\{[^}]+:\}', master_skills_block):
                fixed = re.sub(
                    r'\\begin\{rSection\}\{Technical\s+Skills\}.*?\\end\{rSection\}',
                    lambda _: master_skills_block,
                    fixed,
                    flags=re.DOTALL
                )

    # ── Ensure \name and \address render cleanly ────────────────────────────
    # For minipage-based multi-line \address, keep in preamble so resume.cls \AtBeginDocument renders it.
    # For single-line \address, convert to \printaddress inside \begin{document}.
    addr_block = extract_latex_command(fixed, "\\address")
    if addr_block:
        if "minipage" in addr_block:
            # Minipage address belongs in the preamble before \begin{document}
            doc_idx = fixed.find("\\begin{document}")
            addr_idx = fixed.find(addr_block)
            if addr_idx > doc_idx:
                fixed = fixed.replace(addr_block, "")
                fixed = fixed.replace("\\begin{document}", addr_block + "\n\\begin{document}", 1)
        else:
            clean_addr = addr_block.replace("\\address{", "\\printaddress{")
            fixed = fixed.replace(addr_block, "")
            fixed = fixed.replace("\\begin{document}", "\\begin{document}\n" + clean_addr, 1)

    name_block = extract_latex_command(fixed, "\\name")
    if name_block and fixed.find(name_block) > fixed.find("\\begin{document}"):
        fixed = fixed.replace(name_block, "")
        fixed = fixed.replace("\\begin{document}", name_block + "\n\\begin{document}", 1)

    # ── Strip any existing spacing def overrides (we re-inject below) ────────
    for pattern in [
        r'\\def\\(sectionskip|sectionlineskip|nameskip|addressskip)(\{([^{}]*|\{[^{}]*\})*\}|\\[a-zA-Z]+|\s+[^\s\\{]+)',
        r'\\renewcommand\{\\(sectionskip|sectionlineskip|nameskip|addressskip)\}(\{([^{}]*|\{[^{}]*\})*\}|\\[a-zA-Z]+)',
    ]:
        fixed = re.sub(pattern, '', fixed)

    # ── Tighten geometry margins (force single-page fit) ─────────────────────
    fixed = re.sub(
        r'\\usepackage\[[^\]]*\]\{geometry\}',
        r'\\usepackage[left=0.35in,top=0.15in,right=0.35in,bottom=0.13in]{geometry}',
        fixed,
    )

    # ── Clean Preamble Font Packages ───────────────────────────────────────
    # Remove any existing font packages and old fontspec/IfFontExistsTF configurations cleanly
    fixed = re.sub(r'\\usepackage\{(lmodern|helvet|palatino|charter|bookman|courier|marvosym|times|fontspec|fontawesome|xcolor|hyperref)\}', '', fixed)
    fixed = re.sub(r'\\usepackage\[[^\]]*\]\{(fontenc|geometry|hyperref)\}', '', fixed)
    fixed = re.sub(r'\\IfFontExistsTF\{[^\}]+\}\s*\{[^{}]*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}[^{}]*)*\}\s*\{[^{}]*(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}[^{}]*)*\}', '', fixed)
    
    doc_class_end = fixed.find('\n', fixed.find('\\documentclass'))
    ats_preamble = (
        "\\usepackage[T1]{fontenc}\n"
        "\\usepackage[left=0.35in,top=0.15in,right=0.35in,bottom=0.13in]{geometry}\n"
        "\\usepackage{times}\n"
        "\\usepackage[hidelinks]{hyperref}\n"
        "\\hypersetup{\n    colorlinks=false,\n    pdfborder={0 0 0}\n}\n"
        "\\renewcommand{\\labelitemi}{$\\bullet$}\n"
        "\\renewcommand{\\labelitemii}{$\\bullet$}\n"
        "\\def\\sectionskip{\\vspace{0.08em}}\n"
        "\\def\\sectionlineskip{\\vspace{0.04em}}\n"
        "\\def\\nameskip{\\vspace{0.05em}}\n"
        "\\def\\addressskip{\\vspace{0.05em}}\n"
    )
    fixed = fixed[:doc_class_end + 1] + ats_preamble + fixed[doc_class_end + 1:]
    if '\\newcommand\\mybar' not in fixed:
        mybar_def = "\\newcommand\\mybar{\\kern1pt\\rule[-\\dp\\strutbox]{.8pt}{\\baselineskip}\\kern1pt}\n"
        fixed = fixed.replace('\\begin{document}', mybar_def + '\\begin{document}')

    # ── Inject spacing_scale and linespread overrides ────────────────────────
    spacing_overrides = []
    if linespread != 1.0:
        spacing_overrides.append(f"\\linespread{{{linespread:.2f}}}\\selectfont")
    if spacing_scale != 1.0:
        sec_skip = max(0.12, 0.25 * spacing_scale)
        sec_line_skip = max(0.06, 0.12 * spacing_scale)
        name_sk = max(0.12, 0.20 * spacing_scale)
        addr_sk = max(0.08, 0.15 * spacing_scale)
        spacing_overrides.append(f"\\def\\sectionskip{{\\vspace{{{sec_skip:.2f}em}}}}")
        spacing_overrides.append(f"\\def\\sectionlineskip{{\\vspace{{{sec_line_skip:.2f}em}}}}")
        spacing_overrides.append(f"\\def\\nameskip{{\\vspace{{{name_sk:.2f}em}}}}")
        spacing_overrides.append(f"\\def\\addressskip{{\\vspace{{{addr_sk:.2f}em}}}}")

    # ── Strict 1-Page PDF Budget Clamping: tighten itemize and margin if scaled
    if spacing_scale <= 0.90 or linespread <= 0.95:
        # Tighten list item padding and section baseline padding
        spacing_overrides.append("\\addtolength{\\textheight}{0.28in}")
        spacing_overrides.append("\\addtolength{\\topmargin}{-0.14in}")
        spacing_overrides.append("\\let\\olditem\\item")
        spacing_overrides.append("\\renewcommand{\\item}{\\vspace{-1.5pt}\\olditem}")

    if spacing_overrides:
        fixed = fixed.replace("\\begin{document}", "\\begin{document}\n" + "\n".join(spacing_overrides), 1)

    # ── Inject \frenchspacing to ensure clean, consistent inter-sentence spacing
    if "\\frenchspacing" not in fixed:
        fixed = fixed.replace("\\begin{document}", "\\frenchspacing\n\\begin{document}", 1)

    # ── Escape unescaped special LaTeX chars in document body ONLY (skip pure comments) ─────
    doc_start = fixed.find('\\begin{document}')
    if doc_start != -1:
        preamble = fixed[:doc_start]
        body = fixed[doc_start:]

        lines = body.split('\n')
        new_lines = []
        for line in lines:
            if line.strip().startswith('%'):
                new_lines.append(line)
                continue
            # Replace raw Unicode £ with \pounds (raw £ in Times New Roman under Tectonic maps to Czech hacek c caron)
            line = line.replace('£', '\\pounds ')
            # Replace unicode en-dash, em-dash, and curly quotes that trigger missing font glyph warnings
            line = line.replace('–', '--').replace('—', '---')
            line = line.replace('’', "'").replace('‘', "'").replace('”', '"').replace('“', '"')
            # Ensure proper separation between \pounds and digits (e.g. \pounds30M+ -> \pounds 30M+)
            line = re.sub(r'\\pounds(?=[0-9])', r'\\pounds ', line)
            l = re.sub(r'(?<!\\)&', r'\\&', line)
            l = re.sub(r'(?<!\\)%', r'\\%', l)
            l = re.sub(r'(?<!\\)_', r'\\_', l)
            l = re.sub(r"(?<!\\)#(?!\d)", r'\\#', l)
            l = l.replace('\\\\&', '\\&').replace('\\\\%', '\\%').replace('\\\\_', '\\_').replace('\\\\#', '\\#')
            new_lines.append(l)
        fixed = preamble + '\n'.join(new_lines)

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

    # ── Clean up any tabular environments inserted by LLM inside rSection ───────
    def _convert_tabular_to_clean_lines(match):
        body = match.group(1)
        clean_lines = []
        # Split by LaTeX line break \\
        for raw_line in re.split(r'\\{2,}', body):
            line = raw_line.strip()
            if not line:
                continue
            # If the line contains table column separator '&'
            if '&' in line:
                parts = line.split('&', 1)
                col1 = parts[0].strip()
                col2 = parts[1].strip()
                # Clean up any \bfseries or bold markup from label
                col1_clean = re.sub(r'\\(?:bfseries|textbf)\{?([^}]*)\}?', r'\1', col1).strip().rstrip(':')
                clean_lines.append(f"\\textbf{{{col1_clean}:}} {col2} \\\\")
            else:
                clean_lines.append(line + " \\\\")
        return "\n".join(clean_lines)

    # Match \begin{tabular}... \end{tabular} including any complex column specs like @{} >{\bfseries}l @{\hspace{6ex}} l
    fixed = re.sub(
        r'\\begin\{tabular\}(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\{[^{}]*\})?(.*?)\\end\{tabular\}',
        _convert_tabular_to_clean_lines,
        fixed,
        flags=re.DOTALL
    )
    # Also strip any leftover lone \begin{tabular...} or \end{tabular}
    fixed = re.sub(r'\\begin\{tabular\}(?:\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\{[^{}]*\})?', '', fixed)
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

    # ── Auto-bold metrics, percentages, currencies, dynamic companies & schools ──
    def _bold_metrics_in_body(match_or_text):
        if hasattr(match_or_text, "group"):
            block = match_or_text.group(0)
        else:
            block = str(match_or_text)
        # Avoid bolding inside command arguments or environments that should not be touched
        parts = re.split(r'(\\textbf\{[^{}]*\}|\\href\{[^{}]*\}\{[^{}]*\}|\\begin\{rSection\}\{Technical\s+Skills\}.*?\\end\{rSection\})', block, flags=re.DOTALL)
        
        # Dynamically discover candidate employers & institutions from the resume itself
        dynamic_entities: Set[str] = set()
        if master_latex:
            # Extract employer names from {\bf Company} \hfill
            for emp in re.findall(r'\{\\bf\s+([^{}\\]+)\}\s*\\mybar|\{\\bf\s+([^{}\\]+)\}\s*\\hfill', master_latex):
                for name in emp:
                    if name and len(name.strip()) > 2 and not name.strip().lower().startswith(('software', 'data', 'engineer', 'lead', 'senior')):
                        dynamic_entities.add(name.strip())
        
        # Also extract employers and schools present in this LaTeX block
        for emp in re.findall(r'\{\\bf\s+([^{}\\]+)\}\s*\\mybar|\{\\bf\s+([^{}\\]+)\}\s*\\hfill', fixed):
            for name in emp:
                if name and len(name.strip()) > 2 and not name.strip().lower().startswith(('software', 'data', 'engineer', 'lead', 'senior')):
                    dynamic_entities.add(name.strip())

        for i in range(len(parts)):
            if not parts[i].startswith(('\\textbf{', '\\href{', '\\begin{rSection}{Technical Skills}')):
                # Bold percentages: 60%, 46%, ~40%, \sim40%, +12%
                parts[i] = re.sub(r'(?<!\\textbf\{)(?<!\w)((\~|\\sim\s*|\+)?\d+(?:\.\d+)?\\%)(?!\})', r'\\textbf{\1}', parts[i])
                # Bold currencies and scale amounts: \pounds 30M+, $10M+, 2M+, 1,000+, 200+, 5,000+
                parts[i] = re.sub(r'(?<!\\textbf\{)(?:\\pounds\s*|\$)\s*(\d+(?:\.\d+)?[MKB]?\+?)', r'\\textbf{\\pounds \1}' if '\\pounds' in parts[i] else r'\\textbf{\$\1}', parts[i])
                parts[i] = re.sub(r'(?<!\\textbf\{)(?<!\w)(\b\d+(?:,\d{3})+\+?|\b\d+[MKB]\+?)(?!\w)(?!\})', r'\\textbf{\1}', parts[i])
                # Bold dynamically extracted candidate employers & schools
                for entity_str in sorted(list(dynamic_entities), key=lambda x: len(x), reverse=True):
                    pat = f"(?<!\\\\textbf\\{{)(?<!\\w)({re.escape(entity_str)})(?!\\w)(?!\\}})"
                    parts[i] = re.sub(pat, r'\\textbf{\1}', parts[i])
        return "".join(parts)

    doc_start = fixed.find('\\begin{document}')
    if doc_start != -1:
        _body_match = re.search(r'\\begin\{document\}.*', fixed, re.DOTALL)
        fixed = fixed[:doc_start] + _bold_metrics_in_body(_body_match.group(0) if _body_match else fixed[doc_start:])

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
                new_lines = []
                categorized = {}
                for s in missing_to_add:
                    cat = categorize_skill(s)
                    categorized.setdefault(cat, []).append(s)

                for line in lines:
                    stripped = line.strip()
                    matched_cat = None
                    if stripped.startswith('\\textbf{'):
                        s_lower = stripped.lower()
                        if 'language' in s_lower and 'Languages' in categorized and categorized['Languages']:
                            matched_cat = 'Languages'
                        elif any(w in s_lower for w in ['ai', 'ml', 'genai', 'machine learning', 'learning']) and 'AI/ML & GenAI' in categorized and categorized['AI/ML & GenAI']:
                            matched_cat = 'AI/ML & GenAI'
                        elif any(w in s_lower for w in ['data', 'platform', 'database', 'cloud']) and 'Data & Platforms' in categorized and categorized['Data & Platforms']:
                            matched_cat = 'Data & Platforms'
                        elif any(w in s_lower for w in ['software', 'infra', 'tool', 'framework']) and 'Software & Infrastructure' in categorized and categorized['Software & Infrastructure']:
                            matched_cat = 'Software & Infrastructure'
                    
                    if matched_cat:
                        to_inject = categorized.pop(matched_cat)
                        if stripped.endswith('\\\\'):
                            new_line = stripped[:-2].rstrip() + ", " + ", ".join(to_inject) + " \\\\"
                        else:
                            new_line = stripped + ", " + ", ".join(to_inject)
                        new_lines.append(new_line)
                    else:
                        new_lines.append(line)

                for remaining_cat, skills_list in categorized.items():
                    if skills_list:
                        new_lines.append(f"\\textbf{{{remaining_cat}:}} {', '.join(skills_list)} \\\\")

                return f"\\begin{{rSection}}{{Technical Skills}}\n" + "\n".join(new_lines) + f"\n\\end{{rSection}}"

            fixed = re.sub(
                r'\\begin\{rSection\}\{Technical\s+Skills\}(.*?)\\end\{rSection\}',
                _inject_user_skills,
                fixed,
                flags=re.DOTALL
            )

    # Prepend XeLaTeX magic comment at the very beginning of the finalized LaTeX
    magic_comment = "% !TEX TS-program = xelatex\n% !TEX program = xelatex\n% !TEX encoding = UTF-8 Unicode\n"
    if not fixed.startswith("% !TEX"):
        fixed = magic_comment + fixed

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
    keywords_to_bold: Set[str] = set()
    if dynamic_skills:
        for s in dynamic_skills:
            if len(s.strip()) > 1:
                keywords_to_bold.add(s.strip())

    # 3. Automatic Metric & Technology Bolding
    parts = re.split(r'(\\textbf\{[^{}]*\})', t)
    for i in range(len(parts)):
        if not parts[i].startswith('\\textbf{'):
            # Bold dynamic skills extracted from candidate profile
            for kw_str in sorted(list(keywords_to_bold), key=lambda x: len(x), reverse=True):
                pattern = f"(?<!\\\\textbf\\{{)(?<!\\w)({re.escape(kw_str)})(?!\\w)(?!\\}})"
                parts[i] = re.sub(pattern, r'\\textbf{\1}', parts[i])
    t = "".join(parts)

    # 4. Clean LaTeX escape chars without destroying \textbf{}
    t = re.sub(r'(?<!\\)&', r'\\&', t)
    t = re.sub(r'(?<!\\)%', r'\\%', t)
    t = re.sub(r'(?<!\\)_', r'\\_', t)
    return t


def generate_latex_from_json(
    data: dict,
    master_latex: Optional[str] = None,
    user_selected_skills: Optional[List[str]] = None,
) -> str:
    """
    Generate a canonical LaTeX resume from structured JSON data.
    If master_latex is provided, \\name and \\address are copied verbatim from it.
    """
    name     = data.get("name", "Name")
    email    = data.get("email", "")
    phone    = data.get("phone", "")
    portfolio = data.get("portfolio", "") or data.get("website", "")
    linkedin  = data.get("linkedin", "")
    github    = data.get("github", "")

    for link in data.get("links", []):
        link_str = str(link).strip()
        if "linkedin.com" in link_str:
            linkedin = link_str
        elif any(domain in link_str for domain in ["github.io", "akhilbaja3005.github.io"]):
            portfolio = link_str
        elif "github.com" in link_str and not github:
            github = link_str
        elif not portfolio and ("http://" in link_str or "https://" in link_str):
            portfolio = link_str

    contact_parts = []
    if email:
        contact_parts.append(f"\\href{{mailto:{email}}}{{{email}}}")
    if phone:
        contact_parts.append(phone)
    if linkedin:
        li_user = linkedin.split("/in/")[-1].rstrip("/") if "/in/" in linkedin else linkedin
        contact_parts.append(f"\\href{{{linkedin}}}{{linkedin.com/in/{li_user}}}")
    if portfolio:
        disp_port = portfolio.replace("https://", "").replace("http://", "").rstrip("/")
        contact_parts.append(f"\\href{{{portfolio}}}{{{disp_port}}}")
    elif github:
        gh_user = github.split("github.com/")[-1].rstrip("/") if "github.com" in github else github
        contact_parts.append(f"\\href{{{github}}}{{github.com/{gh_user}}}")

    address_line = " $|$ ".join(contact_parts)

    latex = []
    latex.append("\\documentclass[11pt]{resume}")
    latex.append("\\usepackage[T1]{fontenc}")
    latex.append("\\usepackage[left=0.35in,top=0.15in,right=0.35in,bottom=0.13in]{geometry}")
    latex.append("\\usepackage{times}")
    latex.append("\\usepackage[hidelinks]{hyperref}")
    latex.append("\\hypersetup{\n    colorlinks=false,\n    pdfborder={0 0 0}\n}")
    latex.append("\\renewcommand{\\labelitemi}{$\\bullet$}")
    latex.append("\\renewcommand{\\labelitemii}{$\\bullet$}")
    latex.append("\\frenchspacing")
    latex.append("\\def\\sectionskip{\\vspace{0.08em}}")
    latex.append("\\def\\sectionlineskip{\\vspace{0.04em}}")
    latex.append("\\def\\nameskip{\\vspace{0.05em}}")
    latex.append("\\def\\addressskip{\\vspace{0.05em}}")

    name_block: Optional[str] = None
    address_block: Optional[str] = None
    if master_latex:
        name_block    = extract_latex_command(master_latex, "\\name")
        address_block = extract_latex_command(master_latex, "\\address")
        latex.append(name_block if name_block else f"\\name{{{name}}}")
        if address_block:
            latex.append(address_block)
        elif address_line:
            latex.append(f"\\address{{\\begin{{minipage}}{{\\linewidth}}\\centering {address_line}\\end{{minipage}}}}")
    else:
        latex.append(f"\\name{{{name}}}")
        if address_line:
            latex.append(f"\\address{{\\begin{{minipage}}{{\\linewidth}}\\centering {address_line}\\end{{minipage}}}}")

    latex.append("\\begin{document}")

    skills = data.get("skills", [])
    if user_selected_skills and len(user_selected_skills) > 0:
        clean_user_skills = [s.strip() for s in user_selected_skills if s and s.strip()]
        if clean_user_skills:
            if isinstance(skills, dict):
                import copy
                skills = copy.deepcopy(skills)
                for s in clean_user_skills:
                    cat = categorize_skill(s)
                    matched_key = None
                    for k in skills.keys():
                        k_low = k.lower()
                        if cat == "Languages" and "lang" in k_low:
                            matched_key = k
                            break
                        elif cat == "AI/ML & GenAI" and any(w in k_low for w in ["ai", "ml", "genai", "learning"]):
                            matched_key = k
                            break
                        elif cat == "Data & Platforms" and any(w in k_low for w in ["data", "platform", "cloud", "database"]):
                            matched_key = k
                            break
                        elif cat == "Software & Infrastructure" and any(w in k_low for w in ["software", "infra", "tool", "framework"]):
                            matched_key = k
                            break
                    if not matched_key:
                        matched_key = next((k for k in skills.keys() if any(w in k.lower() for w in ["ai", "ml", "software", "infra"])), next(iter(skills), cat))
                    if matched_key not in skills:
                        skills[matched_key] = []
                    cur = skills[matched_key]
                    if isinstance(cur, list):
                        if s not in cur:
                            cur.append(s)
                    elif isinstance(cur, str):
                        if s.lower() not in cur.lower():
                            skills[matched_key] = f"{cur}, {s}"
            elif isinstance(skills, list):
                skills = list(set(skills + [s for s in clean_user_skills if s not in skills]))

    skills_list = skills if isinstance(skills, list) else []

    # 1. Professional Summary
    summary = data.get("summary", "")
    if summary:
        latex.append("\\begin{rSection}{Professional Summary}")
        latex.append(_format_bullet_bolding(summary, skills_list))
        latex.append("\\end{rSection}")

    # 2. Education
    edu_list = data.get("education", [])
    if edu_list:
        latex.append("\\begin{rSection}{Education}")
        for idx, edu in enumerate(edu_list):
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

            meta_parts = []
            if dates:
                meta_parts.append(dates)
            if loc:
                meta_parts.append(loc)
            elif gpa:
                meta_parts.append(gpa)
            meta_line = " $|$ ".join(meta_parts)

            edu_entry_lines = []
            edu_entry_lines.append(f"{{\\bf {school}}} -- {{\\em {degree}}} \\\\")
            if meta_line:
                edu_entry_lines.append(f"{{\\em {meta_line}}} \\\\")
            highlights = edu.get("highlights", [])
            if highlights:
                for h in highlights:
                    formatted_h = _format_bullet_bolding(h, skills_list)
                    edu_entry_lines.append(f"\\textit{{\\textbf{{{formatted_h}}}}} \\\\")
            entry_str = "\n".join(edu_entry_lines)
            if idx < len(edu_list) - 1:
                if not entry_str.endswith("\\\\"):
                    entry_str += " \\\\[0.05em]"
            else:
                if entry_str.endswith(" \\\\"):
                    entry_str = entry_str[:-3]
            latex.append(entry_str)
        latex.append("\\end{rSection}")

    # 3. Work Experience
    exp_list = data.get("experience", [])
    if exp_list:
        latex.append("\\begin{rSection}{Work Experience}")
        for exp in exp_list:
            company  = exp.get("company", "")
            role     = exp.get("role", "")
            location = exp.get("location", "")
            start    = exp.get("start_date", "")
            end      = exp.get("end_date", "")
            dates    = f"{start} -- {end}" if start and end else (start or end or exp.get("dates", ""))
            bullets  = exp.get("description", [])
            techs    = exp.get("technologies", "")

            # Match user format: {\bf Company $|$ \textnormal{Role} $|$ \em Dates $|$ Location}
            header_components = []
            if company:
                header_components.append(f"\\bf {company}")
            if role:
                header_components.append(f"\\textnormal{{{role}}}")
            if dates:
                header_components.append(f"\\em {dates}")
            if location:
                header_components.append(location)

            header_str = " $|$ ".join(header_components)
            latex.append(f"{{{header_str}}} \\\\")
            if techs:
                latex.append(f"{{\\em Technologies: {techs}}}")
            if bullets:
                latex.append("\\vspace{-0.6em}")
                latex.append("\\begin{itemize}")
                latex.append("    \\setlength{\\itemsep}{-0.35em}")
                latex.append("    \\setlength{\\parsep}{0em}")
                for b in bullets:
                    formatted_b = _format_bullet_bolding(b, skills_list)
                    latex.append(f"    \\item {formatted_b}")
                latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    # 4. Projects
    proj_list = data.get("projects", [])
    if proj_list:
        latex.append("\\begin{rSection}{Projects}")
        latex.append("\\begin{itemize}")
        latex.append("    \\setlength{\\itemsep}{-0.35em}")
        latex.append("    \\setlength{\\parsep}{0em}")
        # Load candidate profile projects lookup for fallback URLs and technologies
        known_profile_projects = {}
        try:
            from mcp.tools.profile_tools import PROFILE_CONFIG_PATH
            if os.path.exists(PROFILE_CONFIG_PATH):
                with open(PROFILE_CONFIG_PATH, "r", encoding="utf-8") as _pf:
                    pdata = json.load(_pf)
                    for kp in pdata.get("candidate", {}).get("projects", []):
                        ktitle = kp.get("title", "").lower().strip()
                        if ktitle:
                            known_profile_projects[ktitle] = kp
        except Exception:
            pass

        for proj in proj_list:
            title       = proj.get("title", "")
            tech_stack  = proj.get("technologies", "") or proj.get("tech_stack", "")
            link_url    = proj.get("link", "") or proj.get("url", "") or proj.get("github", "")
            bullets     = proj.get("description", [])

            # Check profile fallback
            t_low = title.lower().strip()
            for kp_title, kp_data in known_profile_projects.items():
                if kp_title in t_low or t_low in kp_title or (len(t_low) > 8 and kp_title[:8] == t_low[:8]):
                    if not link_url and kp_data.get("url"):
                        link_url = kp_data.get("url")
                    if not tech_stack and kp_data.get("technologies"):
                        k_techs = kp_data.get("technologies")
                        tech_stack = ", ".join(k_techs) if isinstance(k_techs, list) else str(k_techs)
                    break

            # Handle case where description array had technologies as its first element
            if isinstance(bullets, list) and len(bullets) > 1 and not tech_stack:
                first_item = bullets[0].strip()
                if not any(v in first_item.lower() for v in ["built", "designed", "developed", "engineered", "cloud", "enhanced"]) and len(first_item.split(",")) >= 2:
                    tech_stack = first_item
                    bullets = bullets[1:]

            body_text   = ""
            if bullets:
                if isinstance(bullets, list):
                    body_text = " ".join([b.strip() for b in bullets])
                else:
                    body_text = str(bullets).strip()

            body_text = re.sub(r'~\s*(?=\d|\\textbf)', r'\\textasciitilde ', body_text)
            formatted_body = _format_bullet_bolding(body_text, skills_list)

            # Escape LaTeX special chars in title and tech_stack if unescaped
            safe_title = re.sub(r'(?<!\\)&', r'\\&', title)
            safe_tech = re.sub(r'(?<!\\)&', r'\\&', tech_stack) if tech_stack else ""

            proj_header = f"    \\item \\textbf{{{safe_title}}}"
            if safe_tech:
                proj_header += f" -- {{\\em {safe_tech}}}"
            proj_header += " \\\\"
            latex.append(proj_header)

            if link_url:
                short_link = link_url.replace("https://", "").replace("http://", "").rstrip("/")
                latex.append(f"    Open source: \\href{{{link_url}}}{{{short_link}}} \\\\")

            if formatted_body:
                latex.append(f"    {formatted_body}")
        latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    # 5. Technical Skills
    if not skills or (isinstance(skills, dict) and len(skills) == 0):
        fallback_skills = []
        for exp in data.get("experience", []):
            techs = exp.get("technologies") or ""
            if techs:
                fallback_skills.extend([t.strip() for t in techs.split(",") if t.strip()])
        if fallback_skills:
            from services.resume_parser import categorize_skills_with_llm
            skills = categorize_skills_with_llm(list(set(fallback_skills)))

    if skills:
        latex.append("\\begin{rSection}{Technical Skills}")
        if isinstance(skills, list):
            from services.resume_parser import categorize_skills_with_llm
            skills = categorize_skills_with_llm(skills)

        if isinstance(skills, dict):
            for cat, s_list in skills.items():
                cat_name = cat.replace("&", "\\&").replace("%", "\\%")
                s_str = ", ".join(s_list) if isinstance(s_list, list) else str(s_list)
                s_str = re.sub(r'\\textbf\{([^{}]*)\}', r'\1', s_str)
                latex.append(f"\\textbf{{{cat_name}:}} {s_str} \\\\")
            if latex[-1].endswith(" \\\\"):
                latex[-1] = latex[-1][:-3]
        else:
            latex.append(str(skills).replace("&", "\\&").replace("%", "\\%").replace("_", "\\_"))
        latex.append("\\end{rSection}")

    # Achievements & Leadership (if present in custom data)
    ach = data.get("achievements", [])
    if ach:
        latex.append("\\begin{rSection}{Achievements \\& Leadership}")
        if len(ach) == 1:
            latex.append(_format_bullet_bolding(ach[0], skills_list))
        else:
            latex.append("\\begin{itemize}\\setlength{\\itemsep}{-0.2em} \\setlength{\\parsep}{0em}")
            for item in ach:
                latex.append(f"    \\item {_format_bullet_bolding(item, skills_list)}")
            latex.append("\\end{itemize}")
        latex.append("\\end{rSection}")

    latex.append("\\end{document}")
    return "\n".join(latex)


def validate_latex_syntax(latex_code: str) -> tuple[bool, str]:
    """
    Fast pre-flight syntax validator before spawning tectonic subprocess.
    Catches unclosed environments, unbalanced braces, and missing document markers in microseconds.
    """
    if not latex_code or not latex_code.strip():
        return False, "Empty LaTeX document"

    # Check for document environment
    if "\\begin{document}" not in latex_code or "\\end{document}" not in latex_code:
        return False, "Missing \\begin{document} or \\end{document}"

    # Check brace balance outside comments
    brace_count = 0
    in_comment = False
    i = 0
    n = len(latex_code)
    while i < n:
        c = latex_code[i]
        if c == '\n':
            in_comment = False
        elif not in_comment:
            if c == '%' and (i == 0 or latex_code[i - 1] != '\\'):
                in_comment = True
            elif c == '{' and (i == 0 or latex_code[i - 1] != '\\'):
                brace_count += 1
            elif c == '}' and (i == 0 or latex_code[i - 1] != '\\'):
                brace_count -= 1
                if brace_count < 0:
                    return False, f"Unmatched closing brace '}}' at offset {i}"
        i += 1

    if brace_count != 0:
        return False, f"Unbalanced braces in LaTeX document: {brace_count} unclosed brace(s)"

    # Check environment balances (\begin{env} vs \end{env})
    begins = re.findall(r'\\begin\{([a-zA-Z0-9_*]+)\}', latex_code)
    ends = re.findall(r'\\end\{([a-zA-Z0-9_*]+)\}', latex_code)
    # Check counts of common environments
    for env in set(begins + ends):
        b_cnt = begins.count(env)
        e_cnt = ends.count(env)
        if b_cnt != e_cnt:
            return False, f"Unmatched environment '\\{env}': {b_cnt} begin vs {e_cnt} end"

    return True, "Syntax valid"


def compile_and_check_page_metrics(latex_code: str, spacing_scale: float = 1.0, linespread: float = 1.0, master_latex: Optional[str] = None) -> tuple:
    import uuid
    import shutil
    import subprocess
    from pypdf import PdfReader
    from services.session_store import BASE_DIR, UPLOAD_DIR, OUTPUT_DIR

    try:
        fixed_code = apply_latex_hotfix(latex_code, spacing_scale, linespread, master_latex)

        # Pre-flight syntax validation before spawning subprocess
        is_valid, reason = validate_latex_syntax(fixed_code)
        if not is_valid:
            print(f"[latex_utils] Pre-flight syntax check rejected invalid LaTeX: {reason}")
            return 999, 0.0

        unique_id = uuid.uuid4().hex[:10]
        temp_tex = os.path.join(OUTPUT_DIR, f"temp_check_{unique_id}.tex")
        temp_pdf = os.path.join(OUTPUT_DIR, f"temp_check_{unique_id}.pdf")

        with open(temp_tex, "w", encoding="utf-8") as f:
            f.write(fixed_code)

        cls_source = os.path.join(UPLOAD_DIR, "resume.cls")
        if not os.path.exists(cls_source):
            cls_source = os.path.join(BASE_DIR, "assets", "resume.cls")
        if os.path.exists(cls_source):
            shutil.copy2(cls_source, os.path.join(OUTPUT_DIR, "resume.cls"))

        result = subprocess.run(
            ["tectonic", temp_tex, "--outdir", OUTPUT_DIR],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if result.returncode != 0:
            print(f"Tectonic check failed: {result.stderr}")
            return 999, 0.0

        reader = PdfReader(temp_pdf)
        pages = len(reader.pages)

        filled_height = 0.0
        if pages > 0:
            page = reader.pages[0]
            min_y = 9999.0
            max_y = -9999.0

            def visitor(text, cm, tm, font_dict, font_size):
                nonlocal min_y, max_y
                if text.strip():
                    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y
            try:
                page.extract_text(visitor_text=visitor)
                if min_y < 9999.0:
                    filled_height = max_y - min_y
            except Exception as ex:
                print(f"Error extracting baseline coordinates: {ex}")

        if os.path.exists(temp_tex):
            os.remove(temp_tex)
        if os.path.exists(temp_pdf):
            os.remove(temp_pdf)

        return pages, filled_height
    except Exception as e:
        print(f"Error checking page metrics: {e}")
        return 999, 0.0


def inject_tailored_slots(
    master_latex: str,
    summary: Optional[str] = None,
    experience_bullets: Optional[List[List[str]]] = None,
    project_bullets: Optional[List[List[str]]] = None,
    user_selected_skills: Optional[List[str]] = None,
    candidate_info: Optional[dict] = None,
) -> str:
    """
    Surgical Slot Replacement Engine:
    Keeps master_latex completely intact as the golden structural skeleton and only
    replaces the dynamic text slots (Summary, Work Experience bullets, Technical Skills,
    and Header/Candidate info). Locks down Education, document classes, and layouts.
    """
    result = master_latex

    # 0. Candidate info / Header slot
    if candidate_info:
        name = candidate_info.get("name")
        email = candidate_info.get("email")
        phone = candidate_info.get("phone")
        linkedin = candidate_info.get("linkedin")
        portfolio = candidate_info.get("portfolio") or candidate_info.get("website")

        if name:
            result = re.sub(r'\\name\{[^}]*\}', f"\\\\name{{{name}}}", result)

        addr_match = re.search(r'\\address\{(\\begin\{minipage\}.*?\\end\{minipage\})\}', result, re.DOTALL)
        if addr_match:
            parts = []
            if email:
                parts.append(f"\\href{{mailto:{email}}}{{{email}}}")
            if phone:
                parts.append(phone)
            if linkedin:
                li_user = linkedin.split("/in/")[-1].rstrip("/") if "/in/" in linkedin else linkedin
                parts.append(f"\\href{{{linkedin}}}{{linkedin.com/in/{li_user}}}")
            if portfolio:
                disp_port = portfolio.replace("https://", "").replace("http://", "").rstrip("/")
                parts.append(f"\\href{{{portfolio}}}{{{disp_port}}}")
            if parts:
                new_addr = "\\begin{minipage}{\\linewidth}\n\\centering\n" + " $|$ ".join(parts) + "\n\\end{minipage}"
                result = result[:addr_match.start(1)] + new_addr + result[addr_match.end(1):]

    # 1. Professional Summary slot
    if summary and summary.strip():
        sum_pat = r'(\\begin\{rSection\}\{Professional Summary\}).*?(\\end\{rSection\})'
        clean_sum = summary.strip()
        # Clean markdown bold if LLM emitted it
        clean_sum = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', clean_sum)
        result = re.sub(sum_pat, rf'\1\n{clean_sum}\n\2', result, flags=re.DOTALL)

    # 2. Work Experience bullets slot (preserve company, role, dates, tech stack headers)
    if experience_bullets and len(experience_bullets) > 0:
        exp_m = re.search(r'(\\begin\{rSection\}\{Work Experience\}.*?\\end\{rSection\})', result, re.DOTALL)
        if exp_m:
            exp_text = exp_m.group(1)
            itemizes = list(re.finditer(r'(\\begin\{itemize\}.*?\\end\{itemize\})', exp_text, re.DOTALL))
            for job_idx, job_bullets in enumerate(experience_bullets):
                if job_idx < len(itemizes) and isinstance(job_bullets, list) and len(job_bullets) > 0:
                    target_itemize = itemizes[job_idx].group(1)
                    spacing_m = re.search(r'(\\setlength\{\\itemsep\}\{[^}]*\}\s*\\setlength\{\\parsep\}\{[^}]*\})', target_itemize)
                    spacing_str = spacing_m.group(1) if spacing_m else "\\setlength{\\itemsep}{-0.35em}\n    \\setlength{\\parsep}{0em}"
                    new_items_list = []
                    for b in job_bullets:
                        b_clean = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', b.strip())
                        new_items_list.append(f"    \\item {b_clean}")
                    new_items = "\n".join(new_items_list)
                    new_itemize = f"\\begin{{itemize}}\n    {spacing_str}\n{new_items}\n\\end{{itemize}}"
                    exp_text = exp_text.replace(target_itemize, new_itemize, 1)
            result = result[:exp_m.start(1)] + exp_text + result[exp_m.end(1):]

    # 3. Technical Skills slot (inject approved skills)
    if user_selected_skills and len(user_selected_skills) > 0:
        clean_user_skills = [s.strip() for s in user_selected_skills if s and s.strip()]
        skill_m = re.search(r'(\\begin\{rSection\}\{Technical Skills\}.*?\\end\{rSection\})', result, re.DOTALL)
        if skill_m and clean_user_skills:
            skills_text = skill_m.group(1)
            for s in clean_user_skills:
                if s.lower() not in skills_text.lower():
                    # Place in AI/ML line if AI/LLM related, else Data/Platforms
                    if any(w in s.lower() for w in ["ai", "llm", "rag", "langchain", "prompt", "agent", "pytorch", "vllm", "llama", "triton", "eval"]):
                        skills_text = re.sub(r'(\\textbf\{AI/ML[^:]*:.*?)( \\\\)', rf'\1, {s}\2', skills_text)
                    elif any(w in s.lower() for w in ["cloud", "docker", "k8s", "linux", "ci", "git", "jenkins"]):
                        skills_text = re.sub(r'(\\textbf\{Systems[^:]*:.*?)(?=\\end\{rSection\}|\s*\\\\)', rf'\1, {s}', skills_text)
                    else:
                        skills_text = re.sub(r'(\\textbf\{Data[^:]*:.*?)( \\\\)', rf'\1, {s}\2', skills_text)
            result = result[:skill_m.start(1)] + skills_text + result[skill_m.end(1):]

    # 4. Projects slot (preserves Title, Technologies, and Open source: URLs while updating description)
    if project_bullets and len(project_bullets) > 0:
        proj_m = re.search(r'(\\begin\{rSection\}\{Projects\}.*?\\end\{rSection\})', result, re.DOTALL)
        if proj_m:
            proj_sec = proj_m.group(1)
            items = list(re.finditer(r'(\\item\s+\\textbf\{[^}]+\}.*?)(?=\\item|\s*\\end\{itemize\})', proj_sec, re.DOTALL))
            for p_idx, p_bullets in enumerate(project_bullets):
                if p_idx < len(items) and p_bullets:
                    old_item = items[p_idx].group(1)
                    lines = [l for l in old_item.strip().split("\n") if l.strip()]
                    if lines:
                        header_line = lines[0]
                        has_opensource = len(lines) > 1 and "Open source:" in lines[1]
                        opensource_line = lines[1] if has_opensource else ""
                        
                        desc_bullets = p_bullets if isinstance(p_bullets, list) else [str(p_bullets)]
                        clean_bullets = [re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', b.strip()) for b in desc_bullets if b.strip()]
                        # If the first bullet repeated the technologies, discard it
                        if len(clean_bullets) > 1 and not any(v in clean_bullets[0].lower() for v in ["built", "designed", "developed", "engineered", "enhanced", "cloud"]) and len(clean_bullets[0].split(",")) >= 2:
                            clean_bullets = clean_bullets[1:]
                        new_desc = " ".join(clean_bullets)
                        
                        new_parts = [header_line]
                        if opensource_line:
                            new_parts.append(opensource_line)
                        if new_desc:
                            new_parts.append(f"    {new_desc}")
                        new_item_str = "\n".join(new_parts)
                        proj_sec = proj_sec.replace(old_item.strip(), new_item_str.strip(), 1)
            result = result[:proj_m.start(1)] + proj_sec + result[proj_m.end(1):]

    # 5. Achievements / Leadership slot (preserves inline awards or updates section if present)
    ach_bullets = candidate_info.get("achievements") if candidate_info else None
    if ach_bullets and len(ach_bullets) > 0:
        ach_m = re.search(r'(\\begin\{rSection\}\{(?:Achievements|Awards|Leadership)[^}]*\}.*?\\end\{rSection\})', result, re.DOTALL)
        if ach_m:
            ach_lines = []
            for a in ach_bullets:
                if a and a.strip():
                    a_clean = re.sub(r'\*\*(.*?)\*\*', r'\\textbf{\1}', a.strip())
                    ach_lines.append(f"    \\item {a_clean}")
            ach_items = "\n".join(ach_lines)
            new_ach = f"\\begin{{rSection}}{{Achievements \\& Leadership}}\n\\begin{{itemize}}\n    \\setlength{{\\itemsep}}{{-0.2em}}\n    \\setlength{{\\parsep}}{{0em}}\n{ach_items}\n\\end{{itemize}}\n\\end{{rSection}}"
            result = result[:ach_m.start(1)] + new_ach + result[ach_m.end(1):]

    return result