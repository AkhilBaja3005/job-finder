"""Acceptance tests for Phase 4: Honest CV writer (tasks 4.1 - 4.10)."""
from __future__ import annotations

from backend.services.cv_writer import (
    apply_candidate_term_controls,
    build_honest_summary,
    check_rewrite_preserves_numbers_and_tools,
    check_style_consistency,
    check_title_honesty,
    escape_for_html,
    escape_for_latex,
    format_rewrite_log,
    measure_style_distance,
    validate_links,
)


def test_at_4_1_rewrite_preserves_multiset_of_numbers_and_tools():
    orig = "Built Python and FastAPI RAG pipeline reducing latency by 35% across 10k queries."
    good = "Reduced latency by 35% across 10k queries by building a Python and FastAPI RAG pipeline."
    ok, reasons = check_rewrite_preserves_numbers_and_tools(orig, good)
    assert ok, reasons

    missing_num = "Reduced latency across 10k queries by building a Python and FastAPI RAG pipeline."
    ok2, _ = check_rewrite_preserves_numbers_and_tools(orig, missing_num)
    assert not ok2

    added_tool = "Built Python, FastAPI, and Kubernetes RAG pipeline reducing latency by 35% across 10k queries."
    ok3, _ = check_rewrite_preserves_numbers_and_tools(orig, added_tool)
    assert not ok3


def test_at_4_2_rewrite_budget_more_than_3_and_side_by_side_log():
    pairs = [
        {"original": f"Orig {i} Python 10%", "new_text": f"New {i} Python 10%", "reason": f"Lead with Python #{i}"}
        for i in range(5)
    ]
    md = format_rewrite_log(pairs)
    assert len(pairs) == 5
    for i in range(5):
        assert f"Orig {i}" in md
        assert f"New {i}" in md
        assert f"Lead with Python #{i}" in md


def test_at_4_3_summary_builder_pack_16_keeps_strong_positioning():
    master_summary = "Applied AI/ML engineer with 3+ years building Python, LLM, and LangGraph systems."
    source_text = (
        master_summary
        + " Built 7 LangGraph agents with 4 validation gates. Reduced latency by 40%."
    )
    weak_candidate = "Software Engineer with experience in various technologies."
    chosen = build_honest_summary(
        master_summary=master_summary,
        candidate_summary=weak_candidate,
        source_text=source_text,
        target_role="Applied Machine Learning Engineer",
        master_score=78.0,
        candidate_score=65.0,
    )
    assert "Applied AI/ML engineer" in chosen

    strong_candidate = (
        "Applied AI/ML engineer with 3+ years in Python and LLM systems, "
        "including 7 LangGraph agents with 4 validation gates and 40% lower latency."
    )
    chosen2 = build_honest_summary(
        master_summary=master_summary,
        candidate_summary=strong_candidate,
        source_text=source_text,
        target_role="Applied Machine Learning Engineer",
        master_score=78.0,
        candidate_score=86.0,
    )
    assert "7 LangGraph agents" in chosen2


def test_at_4_4_title_honesty_rejects_unsupported_target_title():
    source = "Backend Software Engineer working on Django REST APIs and PostgreSQL."
    assert not check_title_honesty("Principal Applied ML Scientist", source)
    assert check_title_honesty("Backend Software Engineer", source)


def test_at_4_5_style_consistency_linter():
    bad = "I built a GREAT API. I deployed it yesterday."
    issues = check_style_consistency(bad, is_current_role=False)
    assert any("first_person" in i for i in issues)
    assert any("all_caps" in i for i in issues)

    good = "Built a Python API and reduced latency by 20%."
    assert check_style_consistency(good, is_current_role=False) == []


def test_at_4_6_voice_style_distance_under_threshold():
    master = "Built Python pipelines. Reduced latency by 30%. Automated evaluation suites."
    close = "Automated evaluation suites. Built Python pipelines and reduced latency by 30%."
    generic_ai = (
        "Spearheaded synergistic end-to-end paradigm-shifting transformational excellence "
        "across cross-functional enterprise ecosystems utilizing cutting-edge methodologies."
    )
    assert measure_style_distance(master, close) < 0.45
    assert measure_style_distance(master, generic_ai) > measure_style_distance(master, close)


def test_at_4_7_currency_and_date_formats_preserved():
    orig = "Processed INR 300Cr+ volume from 12/04/2023 to 01/11/2024."
    ok, _ = check_rewrite_preserves_numbers_and_tools(
        orig, "From 12/04/2023 to 01/11/2024, processed INR 300Cr+ volume."
    )
    assert ok
    bad, _ = check_rewrite_preserves_numbers_and_tools(
        orig, "Processed £30M+ volume from 2023 to 2024."
    )
    assert not bad


def test_at_4_8_special_characters_escaped_html_and_latex():
    raw = "R&D 100% #1 $50_k ~ ^ \\ { } <script> José 日本語 🚀"
    html_esc = escape_for_html(raw)
    assert "&amp;" in html_esc and "&lt;script&gt;" in html_esc
    assert "José" in html_esc and "日本語" in html_esc and "🚀" in html_esc

    tex_esc = escape_for_latex(raw)
    assert r"\&" in tex_esc and r"\%" in tex_esc and r"\#" in tex_esc and r"\$" in tex_esc
    assert "José" in tex_esc


def test_at_4_9_link_validation_rejects_placeholders_and_invented():
    source_urls = ["https://github.com/akhil/graphite", "https://linkedin.com/in/akhil"]
    ok, errs = validate_links(["https://github.com/akhil/graphite"], source_urls)
    assert ok and errs == []

    bad_ok, bad_errs = validate_links(
        ["https://example.com/demo", "https://github.com/janedoe/repo", "https://github.com/invented/x"],
        source_urls,
    )
    assert not bad_ok
    assert len(bad_errs) == 3


def test_at_4_10_candidate_never_say_and_always_keep():
    bullets = [
        {"id": "b1", "text": "Built SecretClientX billing engine in Python."},
        {"id": "b2", "text": "Built Graphite 7-agent workflow in LangGraph."},
    ]
    filtered = apply_candidate_term_controls(
        bullets,
        never_say=["SecretClientX"],
        always_keep=["Graphite"],
    )
    texts = [b["text"] for b in filtered]
    assert not any("SecretClientX" in t for t in texts)
    assert any("Graphite" in t for t in texts)
