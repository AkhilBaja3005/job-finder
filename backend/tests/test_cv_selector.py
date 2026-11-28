"""Acceptance tests for Phase 3: Content selector (tasks 3.1 - 3.10)."""
from __future__ import annotations

from backend.services.cv_selector import (
    choose_section_order,
    compute_page_budget,
    estimate_fill_ratio,
    filter_education,
    organize_skills,
    score_item,
    select_cv_content,
)
from backend.services.jd_analyzer import analyze_jd


def _make_master(num_roles: int = 2, *, include_extras: bool = False):
    roles = []
    for i in range(num_roles):
        yr_start = 2024 - i * 2
        yr_end = "Present" if i == 0 else str(yr_start + 2)
        roles.append(
            {
                "id": f"role_{i}",
                "title": "Applied AI/ML Engineer" if i == 0 else f"Software Engineer {i}",
                "company": f"Company {i}",
                "start": f"Jan {yr_start}",
                "end": yr_end,
                "current": i == 0,
                "bullets": [
                    {
                        "id": f"role_{i}_b0",
                        "text": f"Built LLM RAG pipeline in Python and LangGraph serving {100 + i * 10}k queries/day.",
                        "has_metric": True,
                    },
                    {
                        "id": f"role_{i}_b1",
                        "text": f"Reduced inference latency by {25 + i}% using FastAPI and Docker.",
                        "has_metric": True,
                    },
                    {
                        "id": f"role_{i}_b2",
                        "text": f"Maintained internal CI/CD scripts and documentation for team {i}.",
                        "has_metric": False,
                    },
                    {
                        "id": f"role_{i}_b3",
                        "text": f"Collaborated with product managers on sprint planning {i}.",
                        "has_metric": False,
                    },
                ],
            }
        )
    master = {
        "name": "Akhil Test",
        "summary": "Applied AI/ML engineer with production LLM and Python experience.",
        "roles": roles,
        "projects": [
            {
                "id": "proj_0",
                "name": "Graphite",
                "description": "7 LangGraph agents with 4 validation gates for automated workflows.",
                "url": "https://github.com/example/graphite",
                "open_source": True,
            },
            {
                "id": "proj_1",
                "name": "DocSearch",
                "description": "RAG search over developer documentation in Python.",
                "url": "https://github.com/example/docsearch",
                "open_source": False,
            },
            {
                "id": "proj_2",
                "name": "StaticBlog",
                "description": "HTML and CSS personal website.",
                "url": "https://github.com/example/blog",
                "open_source": False,
            },
        ],
        "skills": {
            "AI & ML": ["LLMs", "Large Language Models", "LangGraph", "RAG", "PyTorch"],
            "Backend": ["Python", "FastAPI", "Docker", "PostgreSQL"],
            "Frontend": ["HTML", "CSS"],
        },
        "education": [
            {
                "id": "edu_0",
                "degree": "MSc Artificial Intelligence",
                "institution": "Imperial College London",
                "dates": "Sept 2026 – Sept 2027",
                "expected": True,
                "grade": "9.1 CPI",
                "coursework": ["Deep Learning", "Natural Language Processing"],
            },
            {
                "id": "edu_1",
                "degree": "BTech Computer Science",
                "institution": "NIT",
                "dates": "2018 – 2022",
                "grade": "9.2 CPI",
                "placement_role": "Placement Coordinator",
            },
            {
                "id": "edu_2",
                "degree": "High School Diploma",
                "institution": "City High",
                "dates": "2016 – 2018",
            },
        ],
        "awards": ["Best AI Project 2024"],
        "certifications": ["AWS Certified Developer"],
        "languages": ["English (Native)", "Hindi (Native)"],
    }
    if include_extras:
        master["publications"] = ["Agentic Evaluation at Scale (2025)"]
    return master


def test_at_3_1_reproducible_scoring_with_aliases():
    jd = analyze_jd(
        "Required: Large Language Models, Python, agentic workflows, FastAPI.",
        title="Applied ML Engineer",
    )
    s1 = score_item("Built LLM and LangGraph multi-agent system in Python (40% faster).", jd)
    s2 = score_item("Built LLM and LangGraph multi-agent system in Python (40% faster).", jd)
    assert s1 == s2
    assert s1 > score_item("Organized weekly team lunches.", jd)


def test_at_3_2_selection_floors_for_1_2_5_10_roles():
    jd = analyze_jd("Required: Python, LLM, RAG, FastAPI, LangGraph.", title="Applied ML Engineer")
    for n in (1, 2, 5, 10):
        master = _make_master(n)
        sel = select_cv_content(master, jd, page_budget=1)
        assert len(sel["roles"]) == n
        # Most recent role keeps at least 3 bullets (when available)
        assert len(sel["roles"][0]["bullets"]) >= min(3, len(master["roles"][0]["bullets"]))
        # Every role keeps at least 1 bullet and its strongest quantified result
        for idx, r in enumerate(sel["roles"]):
            assert len(r["bullets"]) >= 1
            if any(b.get("has_metric") for b in master["roles"][idx]["bullets"]):
                assert any(b.get("has_metric") for b in r["bullets"])


def test_at_3_3_fill_the_page_pack_16_under_8_percent_blank():
    master = _make_master(2, include_extras=True)
    jd = analyze_jd(
        "Apple Developer Publications. Required: Python, LLM, RAG, documentation tooling.",
        title="Applied Machine Learning Engineer - Developer Publications",
    )
    sel = select_cv_content(master, jd, page_budget=1)
    fill = estimate_fill_ratio(sel, page_budget=1)
    assert 0.92 <= fill <= 1.0, f"Expected fill in [0.92, 1.0], got {fill}"
    # Extras like CPI/grade, placement_role, awards, certifications used when space remains
    assert sel["extras_used"]


def test_at_3_4_page_budget_by_seniority_and_override():
    assert compute_page_budget(candidate_years=3.0, archetype="applied_ml") == 1
    assert compute_page_budget(candidate_years=9.5, archetype="swe") == 2
    assert compute_page_budget(candidate_years=4.0, archetype="research") == 2
    assert compute_page_budget(candidate_years=10.0, archetype="swe", override=1) == 1
    assert compute_page_budget(candidate_years=2.0, archetype="swe", override=2) == 2


def test_at_3_5_section_order_by_archetype_and_level():
    grad_order = choose_section_order(archetype="swe", level="junior", candidate_years=0.5)
    assert grad_order.index("education") < grad_order.index("experience")

    exp_order = choose_section_order(archetype="swe", level="senior", candidate_years=6.0)
    assert exp_order.index("experience") < exp_order.index("education")

    docs_order = choose_section_order(archetype="docs_devrel", level="mid", candidate_years=3.0)
    assert docs_order.index("projects") < docs_order.index("experience")


def test_at_3_6_education_rules_future_dated_and_high_school_omitted():
    master = _make_master(1)
    edus = filter_education(master["education"], has_degree=True)
    degrees = [e["degree"] for e in edus]
    assert "High School Diploma" not in degrees
    msc = next(e for e in edus if "MSc" in e["degree"])
    assert msc["dates"] == "Sept 2026 – Sept 2027"
    assert msc["expected"] is True
    assert msc["grade"] == "9.1 CPI"


def test_at_3_7_skills_grouped_ordered_no_near_synonym_dupes():
    master = _make_master(1)
    jd = analyze_jd("Required: Large Language Models, Python, FastAPI.", title="Applied ML Engineer")
    grouped = organize_skills(master["skills"], jd, source_text="LLMs Large Language Models LangGraph RAG PyTorch Python FastAPI Docker PostgreSQL HTML CSS")
    assert list(grouped.keys())[0] in ("AI & ML", "Backend")
    flat = [s.lower() for items in grouped.values() for s in items]
    # Never duplicate LLMs and Large Language Models
    assert not ("llms" in flat and "large language models" in flat)


def test_at_3_8_projects_2_to_4_exact_names_and_links():
    master = _make_master(1)
    jd = analyze_jd("Required: LangGraph, RAG, Python.", title="AI Engineer")
    sel = select_cv_content(master, jd, page_budget=1)
    assert 2 <= len(sel["projects"]) <= 4
    assert sel["projects"][0]["name"] == "Graphite"
    assert sel["projects"][0]["url"] == "https://github.com/example/graphite"


def test_at_3_9_older_roles_condensed_never_deleted():
    master = _make_master(6)
    jd = analyze_jd("Required: Python, LLM.", title="Applied ML Engineer")
    sel = select_cv_content(master, jd, page_budget=1)
    assert len(sel["roles"]) == 6
    assert [r["start"] for r in sel["roles"]] == [r["start"] for r in master["roles"]]


def test_at_3_10_career_changer_and_gap_preserved():
    master = _make_master(2)
    master["gaps"] = [{"dates": "2022 – 2023", "label": "Career transition & independent AI study"}]
    master["roles"][1]["title"] = "Mechanical Engineer"
    master["roles"][1]["bullets"] = [
        {"id": "r1_b0", "text": "Built Python data analysis scripts for thermal simulation.", "has_metric": False}
    ]
    jd = analyze_jd("Required: Python, LangGraph, RAG.", title="AI Engineer")
    sel = select_cv_content(master, jd, page_budget=1)
    assert sel["roles"][1]["title"] == "Mechanical Engineer"
    assert sel["gaps"] == master["gaps"]
    assert sel["projects"][0]["name"] == "Graphite"
