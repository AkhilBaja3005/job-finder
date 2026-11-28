"""The master CV keeps everything on the resume; the renderer shows it; the validator and gate stop false alarms."""
import json

from backend.services import application_pack as ap
from backend.services import cv_master, cv_model_runner, cv_tailor, cv_verifier

RESUME = """AKHIL BAJA
TECHNICAL SKILLS
Languages: Python, C++, Java, SQL.
AI/ML & GenAI: LLMs, RAG, Computer Vision (U-Net).
Systems, DevOps & Automation: Distributed Systems, RabbitMQ, AST
Parsing, Linux, MCP.
EDUCATION
Imperial College London
"""

PROFILE = {
    "name": "Ada", "email": "ada@example.org", "phone": "+44 7700 900123",
    "experience_summary": "Applied AI/ML engineer with 3+ years of experience, systems used by 1,000+ engineers.",
    "work_experience": [{"company": "Acme", "role": "Engineer", "timeline": "Jan 2022 - Dec 2024", "technologies": ["Python"],
                         "highlights": ["Built a RAG assistant for 1,300+ employees, cutting support time by 70%."]}],
    "education": [{"institution": "IIT", "degree": "B.Tech", "timeline": "Aug 2019 - May 2023", "location": "Hyderabad, India",
                   "cpi": "CPI: 8.04 / 10.0", "highlights": ["Relevant coursework: Responsible AI", "Placement Cell Coordinator: led outreach to 100+ firms."]}],
    "projects": [{"title": "Graphite", "technologies": ["Python"], "url": "https://github.com/ada/graphite", "description": "Built an auditor."}],
    "skill_categories": {"Languages": ["Python"]},
}


def test_skill_groups_are_copied_from_the_resume_text_in_order():
    g = cv_master.skill_groups_from_resume_text(RESUME)
    assert list(g) == ["Languages", "AI/ML & GenAI", "Systems, DevOps & Automation"]
    assert g["AI/ML & GenAI"] == ["LLMs", "RAG", "Computer Vision (U-Net)"]      # commas inside brackets do not split
    assert "AST Parsing" in g["Systems, DevOps & Automation"]                    # a wrapped line is joined
    assert cv_master.skill_groups_from_resume_text("no skills here") == {}


def test_master_keeps_education_details_links_and_resume_skill_groups(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text(RESUME)
    m = cv_master.build_structured_master(PROFILE, resume_path=str(resume))
    edu = m["education"][0]
    assert edu["grade"] == "CPI: 8.04 / 10.0" and edu["location"] == "Hyderabad, India"
    assert any("Placement Cell" in h for h in edu["highlights"])
    assert m["projects"][0]["url"] == "https://github.com/ada/graphite"
    assert list(m["skill_groups"]) == ["Languages", "AI/ML & GenAI", "Systems, DevOps & Automation"]
    assert "RabbitMQ" in m["skills"] and "Python" in m["skills"]


def test_master_without_a_resume_uses_the_profile_groups():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent/resume.pdf")
    assert m["skill_groups"] == {"Languages": ["Python"]}


def test_rendered_cv_shows_cpi_coursework_placement_groups_and_links():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent")
    html = ap.render_cv_html(m)
    assert "CPI: 8.04 / 10.0" in html and "Hyderabad, India" in html
    assert "Relevant coursework: Responsible AI" in html and "Placement Cell Coordinator" in html
    assert "<strong>Languages:</strong>" in html
    assert "github.com/ada/graphite" in html


def test_rendered_cv_escapes_the_new_fields():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent")
    m["education"][0]["highlights"] = ["<script>alert(1)</script>"]
    m["projects"][0]["url"] = 'https://x.test/"><b>'
    html = ap.render_cv_html(m)
    assert "<script>alert(1)</script>" not in html and '"><b>' not in html


def test_tailoring_regroups_skills_without_dropping_any():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent")
    m["skill_groups"] = {"Languages": ["Python", "SQL"], "Systems": ["Docker", "RabbitMQ"]}
    m["skills"] = ["Python", "SQL", "Docker", "RabbitMQ"]
    plan = {"summary": m["summary"], "experience": [{"exp_index": 0, "keep": [0]}], "rewrites": [], "project_order": [0],
            "skills": ["RabbitMQ", "Docker"], "keywords": ["RabbitMQ"]}
    out, _ = cv_tailor._apply_plan(m, plan)
    assert list(out.cv["skill_groups"])[0] == "Systems"
    assert sorted(out.cv["skills"]) == sorted(m["skills"]) and out.cv["skill_groups"]["Systems"][0] == "RabbitMQ"


def test_sentence_openers_and_compound_names_are_not_unsupported_entities():
    src = "Built XGBoost models. Cut costs by 40%."
    assert cv_verifier.check_facts("Also built XGBoost models.", src) == []
    assert cv_verifier.check_facts("Previously cut costs by 40%.", src) == []
    assert cv_verifier.check_facts("Built XGBoost-based models.", src) == []
    assert any("Google" in i for i in cv_verifier.check_facts("Google scale systems.", src))      # a real unknown name is still caught


def test_gate_ignores_generic_words_but_catches_a_lost_skill_bullet():
    m = cv_master.build_structured_master(PROFILE, resume_path="/nonexistent")
    jd = "We build production systems. We need a production engineer to build systems in Python with RAG and RAG evaluation."
    same = cv_tailor.TailoredCV(cv=json.loads(json.dumps(m)), changes=[], warnings=[], keywords=[], tailored=True)
    assert cv_tailor._worse_than_master(m, same, jd, "Engineer") is None
    lost = json.loads(json.dumps(m))
    lost["experience"][0]["description"] = ["Did some work."]
    worse = cv_tailor.TailoredCV(cv=lost, changes=[], warnings=[], keywords=[], tailored=True)
    assert "rag" in (cv_tailor._worse_than_master(m, worse, jd, "Engineer") or "").lower()


def test_tailor_model_follows_the_chosen_provider(monkeypatch):
    for k in ("JOB_FINDER_TAILOR_PROVIDER", "BROWSER_USE_PROVIDERS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert cv_model_runner.pick_tailor_provider() == "gemini"
    monkeypatch.setenv("BROWSER_USE_PROVIDERS", "anthropic,openai,gemini")
    assert cv_model_runner.pick_tailor_provider() == "claude"
    monkeypatch.setenv("JOB_FINDER_TAILOR_PROVIDER", "openai")
    assert cv_model_runner.pick_tailor_provider() == "openai"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("JOB_FINDER_TAILOR_PROVIDER", "anthropic")
    assert cv_model_runner.pick_tailor_provider() == "openai"       # no Claude key: next provider with a key


def test_call_tailor_model_records_what_really_ran(monkeypatch):
    from backend.services import gemini_client as gc
    monkeypatch.setenv("JOB_FINDER_TAILOR_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    seen = {}
    monkeypatch.setattr(gc, "_execute_anthropic", lambda prompt, schema, key, model: seen.update(model=model) or "{}")
    assert cv_model_runner.call_tailor_model("p", None) == "{}"
    assert seen["model"] == "sonnet" and cv_model_runner.LAST_TAILOR_CALL["provider"] == "claude"
