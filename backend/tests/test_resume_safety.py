import re

from services.resume_checks import check_pdf_text, find_unsupported_numbers
from utils.latex_utils import escape_latex_text, inject_tailored_slots

BASE = r"""\documentclass{resume}
\begin{document}
\name{Jane Doe}
\address{\begin{minipage}{\linewidth}\centering jane@old.com\end{minipage}}
\begin{rSection}{Professional Summary}
old summary
\end{rSection}
\begin{rSection}{Work Experience}
\begin{itemize}
    \setlength{\itemsep}{-0.35em}
    \setlength{\parsep}{0em}
    \item old bullet
\end{itemize}
\end{rSection}
\begin{rSection}{Achievements}
\begin{itemize}
    \item old award
\end{itemize}
\end{rSection}
\end{document}"""


def test_escape_special_characters_and_keep_bold():
    out = escape_latex_text("Cut costs by 40% in R&D using C# and snake_case **fast**")
    assert r"40\%" in out and r"R\&D" in out and r"C\#" in out and r"snake\_case" in out
    assert r"\textbf{fast}" in out


def test_escape_neutralizes_injection():
    out = escape_latex_text(r"Hello \input{/etc/passwd} \write18{rm -rf} \def\x{y} {evil}")
    for bad in ("\\input", "\\write", "\\def", "{", "}"):
        assert bad not in out


def test_escape_does_not_double_escape():
    assert escape_latex_text(r"50\% growth and R\&D") == r"50\% growth and R\&D"


def test_summary_with_bold_has_no_tab_corruption():
    out = inject_tailored_slots(BASE, summary="Led **ML** team to 40% gains & more")
    assert "\t" not in out
    assert r"\textbf{ML}" in out and r"40\%" in out and r"\&" in out


def test_bullets_escaped_and_achievements_applied():
    out = inject_tailored_slots(
        BASE,
        experience_bullets=[["Saved 30% of R&D spend"]],
        candidate_info={"achievements": ["Won hackathon & got 1st place"]},
    )
    assert r"Saved 30\% of R\&D spend" in out
    assert r"Won hackathon \& got 1st place" in out and "old award" not in out


def test_header_values_are_safe():
    out = inject_tailored_slots(BASE, candidate_info={"name": "Jane_Doe & Co", "email": "bad{x}@a.com", "phone": "+44 7000 #1"})
    assert r"\name{Jane\_Doe \& Co}" in out
    assert "bad{x}" not in out and r"\#1" in out


def test_find_unsupported_numbers():
    master = r"Cut cost by 40\% and served 2,000 users in 2021"
    assert find_unsupported_numbers(master, "Cut cost by 40% and served 2,000 users") == []
    assert find_unsupported_numbers(master, "Cut cost by 75% and served 2,000 users") == ["75%"]


def test_check_pdf_text_reports_unreadable(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as fh:
        writer.write(fh)
    problems = check_pdf_text(str(path), required=["Jane Doe"])
    assert any("extractable" in p for p in problems) and any("Jane Doe" in p for p in problems)
