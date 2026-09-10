from utils.latex_utils import extract_latex_command, apply_latex_hotfix, generate_latex_from_json


# ─────────────────────────────────────────────────────────────────────────────
# extract_latex_command
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_latex_command_simple():
    code = r"\documentclass{resume}\name{John Doe}\begin{document}"
    assert extract_latex_command(code, r"\name") == r"\name{John Doe}"


def test_extract_latex_command_handles_nested_braces():
    code = r"\address{\faEnvelope{ john@example.com } \faPhone{ 555-1234 }}"
    result = extract_latex_command(code, r"\address")
    assert result == code  # entire nested block, brace-balanced


def test_extract_latex_command_missing_returns_none():
    code = r"\documentclass{resume}\begin{document}"
    assert extract_latex_command(code, r"\name") is None


# ─────────────────────────────────────────────────────────────────────────────
# apply_latex_hotfix
# ─────────────────────────────────────────────────────────────────────────────

def _minimal_latex():
    return (
        r"\documentclass{resume}"
        r"\name{Old Name}"
        r"\address{old@example.com}"
        r"\begin{document}"
        r"Some content with 50% completion & other stuff"
        r"\end{document}"
    )


def test_apply_latex_hotfix_strips_conversational_wrapper():
    code = "Sure, here is your resume:\n" + _minimal_latex() + "\nHope this helps!"
    fixed = apply_latex_hotfix(code)
    assert r"\documentclass" in fixed
    assert fixed.rstrip().endswith(r"\end{document}")
    assert "Sure, here is" not in fixed
    assert "Hope this helps" not in fixed


def test_apply_latex_hotfix_restores_name_and_address_from_master():
    master = (
        r"\documentclass{resume}\name{Real Name}\address{real@example.com}\begin{document}\end{document}"
    )
    generated = (
        r"\documentclass{resume}\name{Hallucinated Name}\address{fake@example.com}"
        r"\begin{document}content\end{document}"
    )
    fixed = apply_latex_hotfix(generated, master_latex=master)
    assert r"\name{Real Name}" in fixed
    assert "real@example.com" in fixed
    assert "Hallucinated Name" not in fixed
    assert "fake@example.com" not in fixed


def test_apply_latex_hotfix_injects_name_and_address_when_missing():
    master = r"\documentclass{resume}\name{Real Name}\address{real@example.com}\begin{document}\end{document}"
    generated = r"\documentclass{resume}\begin{document}content\end{document}"
    fixed = apply_latex_hotfix(generated, master_latex=master)
    assert r"\name{Real Name}" in fixed
    assert "real@example.com" in fixed


def test_apply_latex_hotfix_escapes_unescaped_special_chars():
    code = r"\documentclass{resume}\begin{document}Achieved 50% growth in R&D_team\end{document}"
    fixed = apply_latex_hotfix(code)
    assert r"50\%" in fixed
    assert r"R\&D" in fixed
    assert r"D\_team" in fixed
    # Must not double-escape.
    assert r"\\%" not in fixed
    assert r"\\&" not in fixed


def test_apply_latex_hotfix_does_not_double_escape_already_escaped_chars():
    code = r"\documentclass{resume}\begin{document}Grew revenue by 50\% for R\&D\end{document}"
    fixed = apply_latex_hotfix(code)
    assert r"50\%" in fixed
    assert r"50\\%" not in fixed
    assert r"R\&D" in fixed
    assert r"R\\&D" not in fixed


def test_apply_latex_hotfix_injects_spacing_overrides():
    fixed = apply_latex_hotfix(_minimal_latex(), spacing_scale=0.9, linespread=1.0)
    assert r"\def\nameskip" in fixed
    assert r"\def\sectionskip" in fixed


def test_apply_latex_hotfix_adds_linespread_when_not_default():
    fixed = apply_latex_hotfix(_minimal_latex(), linespread=1.1)
    assert r"\linespread{1.10}" in fixed


def test_apply_latex_hotfix_fixes_hyperref_hidelinks():
    code = r"\documentclass{resume}\usepackage{hyperref}\begin{document}\end{document}"
    fixed = apply_latex_hotfix(code)
    assert r"\usepackage[hidelinks]{hyperref}" in fixed


# ─────────────────────────────────────────────────────────────────────────────
# generate_latex_from_json
# ─────────────────────────────────────────────────────────────────────────────

def test_generate_latex_from_json_includes_all_sections():
    data = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "555-1234",
        "skills": ["Python", "AWS"],
        "education": [{"institution": "State University", "degree": "BS", "field_of_study": "CS", "graduation_date": "2020", "gpa": "3.8"}],
        "experience": [{"company": "Acme", "role": "Engineer", "start_date": "2020", "end_date": "Present", "description": ["Did things"]}],
        "projects": [{"title": "Cool Project", "description": ["Built a thing"]}],
        "achievements": ["Won an award"],
    }
    latex = generate_latex_from_json(data)
    assert r"\documentclass" in latex
    assert r"\begin{document}" in latex
    assert r"\end{document}" in latex
    assert "Jane Doe" in latex
    assert "State University" in latex
    assert "Acme" in latex
    assert "Cool Project" in latex
    assert "Won an award" in latex


def test_generate_latex_from_json_preserves_master_name_and_address():
    master = r"\name{Master Name}\address{master@example.com}"
    data = {"name": "Ignored Name", "email": "ignored@example.com"}
    latex = generate_latex_from_json(data, master_latex=master)
    assert r"\name{Master Name}" in latex
    assert "master@example.com" in latex


def test_generate_latex_from_json_escapes_bullet_special_chars():
    data = {
        "name": "Jane",
        "experience": [{"company": "Acme", "role": "Eng", "start_date": "2020", "end_date": "2021", "description": ["Grew revenue 50% & 20_pct"]}],
    }
    latex = generate_latex_from_json(data)
    assert r"50\%" in latex
    assert r"\&" in latex
    assert r"20\_pct" in latex


def test_generate_latex_from_json_handles_empty_resume():
    latex = generate_latex_from_json({})
    assert r"\documentclass" in latex
    assert r"\begin{document}" in latex
    assert r"\end{document}" in latex


# ─────────────────────────────────────────────────────────────────────────────
# validate_latex_syntax
# ─────────────────────────────────────────────────────────────────────────────

def test_validate_latex_syntax_valid():
    from utils.latex_utils import validate_latex_syntax
    valid_latex = r"""\documentclass{resume}
\begin{document}
\begin{rSection}{Experience}
\begin{itemize}
\item Worked on systems.
\end{itemize}
\end{rSection}
\end{document}"""
    ok, msg = validate_latex_syntax(valid_latex)
    assert ok is True
    assert msg == "Syntax valid"


def test_validate_latex_syntax_unbalanced_braces():
    from utils.latex_utils import validate_latex_syntax
    bad_latex = r"""\documentclass{resume}
\begin{document}
\textbf{Incomplete
\end{document}"""
    ok, msg = validate_latex_syntax(bad_latex)
    assert ok is False
    assert "Unbalanced braces" in msg


def test_validate_latex_syntax_unmatched_environments():
    from utils.latex_utils import validate_latex_syntax
    bad_latex = r"""\documentclass{resume}
\begin{document}
\begin{itemize}
\item Item without end itemize
\end{document}"""
    ok, msg = validate_latex_syntax(bad_latex)
    assert ok is False
    assert "Unmatched environment" in msg


def test_inject_tailored_slots_skills_taxonomy():
    from utils.latex_utils import inject_tailored_slots

    base_latex = r"""\documentclass{resume}
\begin{document}
\begin{rSection}{Technical Skills}
\textbf{AI/ML, Generative AI & Agents:} PyTorch, TensorFlow, LangChain, Transformers \\
\textbf{Data Platforms, Messaging & Engines:} Apache Spark, Kafka, PostgreSQL \\
\textbf{Systems, Cloud & Developer Tooling:} AWS, Docker, Kubernetes, Git
\end{rSection}
\end{document}"""

    # Injecting skills: AI/ML skill (vLLM), Cloud skill (CI/CD), Data skill (Snowflake)
    user_skills = ["vLLM", "CI/CD Pipeline", "Snowflake", "PyTorch"]  # PyTorch is already present, shouldn't duplicate
    tailored = inject_tailored_slots(base_latex, user_selected_skills=user_skills)

    # Verify vLLM placed in AI/ML line
    assert "Transformers, vLLM" in tailored
    # Verify CI/CD Pipeline placed in Systems line
    assert "Git, CI/CD Pipeline" in tailored
    # Verify Snowflake placed in Data Platforms line
    assert "PostgreSQL, Snowflake" in tailored
    # Verify no duplicate PyTorch
    assert tailored.count("PyTorch") == 1
