"""
test_ats_scorer.py — Comprehensive Golden Test Suite for ATS Scorer (Steps 1-5)
"""

import pytest
from services import ats_scorer as ats


# ─────────────────────────────────────────────────────────────────────────────
# _extract_taxonomy_skills
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_taxonomy_skills_basic_tech_aliases():
    text = "Built ML pipelines using PyTorch and deployed on AWS Lambda with Docker containers"
    skills = ats._extract_taxonomy_skills(text)
    assert "machine learning" in skills
    assert "pytorch" in skills
    assert "aws" in skills
    assert "docker" in skills


def test_extract_taxonomy_skills_go_requires_context():
    no_context = ats._extract_taxonomy_skills("We go the extra mile for every customer")
    assert "go" not in no_context
    assert "go" in ats._extract_taxonomy_skills("5 years of golang experience")
    assert "go" in ats._extract_taxonomy_skills("Go programming language backend services")


def test_extract_taxonomy_skills_non_tech_domains():
    product = ats._extract_taxonomy_skills("Led product roadmap and ran A/B testing experiments using Jira")
    assert "product management" not in product
    assert "roadmapping" in product
    assert "a/b testing" in product
    assert "jira" in product

    design = ats._extract_taxonomy_skills("Created wireframes and prototypes in Figma, maintaining our design system")
    assert "figma" in design
    assert "wireframing" in design
    assert "design systems" in design

    finance = ats._extract_taxonomy_skills("Built financial models and managed budgeting in Microsoft Excel and NetSuite")
    assert "financial modeling" in finance
    assert "budgeting" in finance
    assert "excel" in finance
    assert "quickbooks" in finance


def test_extract_taxonomy_skills_empty_text():
    assert ats._extract_taxonomy_skills("") == set()
    assert ats._extract_taxonomy_skills(None) == set()


# ─────────────────────────────────────────────────────────────────────────────
# High-risk token context guards
# ─────────────────────────────────────────────────────────────────────────────

def test_high_risk_tokens_reject_generic_english_usage():
    assert ats._extract_taxonomy_skills("I always strive to excel in a fast-paced environment") == set()
    assert ats._extract_taxonomy_skills("We must stay lean given the budget") == set()
    assert ats._extract_taxonomy_skills("This decision could sap morale across the team") == set()
    assert ats._extract_taxonomy_skills("We built a strong sales pipeline this quarter") == set()
    assert ats._extract_taxonomy_skills("Managing our hiring pipeline for new candidates") == set()
    assert ats._extract_taxonomy_skills("This project will spark innovation across teams") == set()
    assert ats._extract_taxonomy_skills("The candidate should spark curiosity in others") == set()
    assert ats._extract_taxonomy_skills("Please submit your CV and cover letter to apply") == set()


def test_high_risk_tokens_match_with_proper_context():
    assert "excel" in ats._extract_taxonomy_skills("Advanced skills in Microsoft Excel with pivot tables")
    assert "process improvement" in ats._extract_taxonomy_skills("Experience with Lean Six Sigma methodology")
    assert "sap" in ats._extract_taxonomy_skills("Experience with SAP ERP and S4 HANA modules")
    assert "airflow" in ats._extract_taxonomy_skills("Built ETL data pipelines using Apache Airflow")
    assert "apache spark" in ats._extract_taxonomy_skills("We use Apache Spark for big data processing")
    assert "computer vision" in ats._extract_taxonomy_skills("Experience with computer vision and object detection")


# ─────────────────────────────────────────────────────────────────────────────
# extract_jd_skills — required vs preferred bucketing
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_jd_skills_does_not_leak_generic_pipeline_requirement():
    jd = "Requirements: Strong sales pipeline management skills. 5+ years of experience."
    required, preferred = ats.extract_jd_skills(jd)
    assert "pipeline" not in required
    assert "pipeline" not in preferred
    assert "data pipelines" not in required


def test_extract_jd_skills_splits_required_and_preferred():
    jd = """
    Requirements:
    - 5+ years of Python and SQL experience
    - Experience with AWS

    Nice to have:
    - Familiarity with Kubernetes and Terraform
    """
    required, preferred = ats.extract_jd_skills(jd)
    assert "python" in required
    assert "sql" in required
    assert "aws" in required
    assert "kubernetes" in preferred
    assert "terraform" in preferred
    assert not (set(required) & set(preferred))


# ─────────────────────────────────────────────────────────────────────────────
# calculate_flattened_experience — timeline merging & overlap handling
# ─────────────────────────────────────────────────────────────────────────────

def test_calculate_flattened_experience_merges_overlapping_jobs():
    resume = {
        "experience": [
            {"company": "A", "role": "Engineer", "start_date": "Jan 2020", "end_date": "Dec 2021", "description": []},
            {"company": "B", "role": "Engineer", "start_date": "Jun 2021", "end_date": "Present", "description": []},
        ]
    }
    years, avg_tenure, segments, _ = ats.calculate_flattened_experience(resume)
    assert len(segments) == 1
    assert years > 0


def test_calculate_flattened_experience_no_valid_dates():
    resume = {"experience": [{"company": "A", "role": "Engineer", "start_date": "", "end_date": "", "description": []}]}
    years, avg_tenure, segments, _ = ats.calculate_flattened_experience(resume)
    assert years == 0.0
    assert segments == []


# ─────────────────────────────────────────────────────────────────────────────
# Seniority tier resolution priority
# ─────────────────────────────────────────────────────────────────────────────

def test_seniority_tier_resolves_to_highest_priority_match():
    resume = {"experience": [{"role": "Senior Software Engineer", "company": "X"}]}
    assert ats.get_candidate_seniority_tier(resume) == "senior"


def test_seniority_tier_junior_and_executive():
    assert ats.get_candidate_seniority_tier({"experience": [{"role": "Junior Developer"}]}) == "junior"
    assert ats.get_candidate_seniority_tier({"experience": [{"role": "VP of Engineering"}]}) == "executive"
    assert ats.get_candidate_seniority_tier({"experience": []}) == "junior"


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_knockouts — hard filters
# ─────────────────────────────────────────────────────────────────────────────

def test_knockout_visa_sponsorship_rejects_when_required():
    resume = {"requires_sponsorship": True, "location": "Remote"}
    jd = "This role requires you must have right to work with no visa sponsorship available."
    eligible, reason = ats.evaluate_knockouts(resume, jd)
    assert eligible is False
    assert reason is not None


def test_knockout_passes_with_no_disqualifiers():
    resume = {"requires_sponsorship": False, "location": "Remote"}
    jd = "We are hiring a software engineer to join our remote team."
    eligible, reason = ats.evaluate_knockouts(resume, jd)
    assert eligible is True
    assert reason is None


# ─────────────────────────────────────────────────────────────────────────────
# compute_ats_score — end-to-end deterministic scoring
# ─────────────────────────────────────────────────────────────────────────────

def _sample_resume():
    return {
        "name": "Jane Doe",
        "location": "Remote",
        "requires_sponsorship": False,
        "skills": ["Python", "AWS", "Docker", "SQL"],
        "education": [{"institution": "State University", "degree": "Bachelors", "gpa": ""}],
        "experience": [
            {
                "company": "Acme Corp",
                "role": "Senior Software Engineer",
                "start_date": "Jan 2019",
                "end_date": "Present",
                "description": [
                    "Built scalable Python microservices deployed on AWS using Docker",
                    "Optimized SQL queries reducing latency by 40%",
                ],
            }
        ],
    }


def test_compute_ats_score_strong_match():
    jd = """
    We are looking for a Senior Software Engineer with 4+ years experience.
    Requirements: Python, AWS, Docker, SQL.
    """
    result = ats.compute_ats_score(_sample_resume(), jd)
    assert result.eligible is True
    assert result.skills_score >= 70
    assert result.experience_score >= 70
    assert "python" in result.matched_skills
    assert result.missing_skills == []


def test_compute_ats_score_weak_match_has_missing_skills():
    jd = """
    Requirements: Kubernetes, Terraform, Rust, Go programming language.
    5+ years of experience required.
    """
    result = ats.compute_ats_score(_sample_resume(), jd)
    assert result.eligible is True
    assert result.skills_score < 60
    assert len(result.missing_skills) > 0


def test_compute_ats_score_unscoreable_jd_uses_neutral_default():
    jd = "We need someone who is a great team player with excellent communication."
    result = ats.compute_ats_score(_sample_resume(), jd)
    assert result.skills_score == 60
    assert result.matched_skills == []


def test_compute_overall_score_formula():
    assert ats.compute_overall_score(100, 100, 100) == 100
    assert ats.compute_overall_score(0, 0, 0) == 0
    assert ats.compute_overall_score(80, 60, 40) == round(0.40 * 80 + 0.35 * 60 + 0.25 * 40)


# ─────────────────────────────────────────────────────────────────────────────
# Golden Test Suite for ATS Scorer Refactors (Steps 1-5)
# ─────────────────────────────────────────────────────────────────────────────

def test_old_job_skill_not_dropped():
    resume = {
        "name": "Alex OldSkill",
        "skills": ["SQL"],
        "experience": [
            {
                "company": "Legacy Systems Corp",
                "role": "Software Developer",
                "start_date": "Jan 2018",
                "end_date": "Dec 2020",
                "description": ["Developed high throughput low latency Python microservices"]
            }
        ]
    }
    jd = "Requirements:\n- Python"
    res = ats.compute_ats_score(resume, jd)
    assert res.skills_score > 0
    assert "python" in res.matched_skills


def test_seniority_tier_modifier_both_directions():
    senior_resume = {
        "experience": [{"role": "Senior Staff Architect", "start_date": "2015", "end_date": "Present"}]
    }
    junior_resume = {
        "experience": [{"role": "Junior Developer Associate", "start_date": "2023", "end_date": "Present"}]
    }
    
    junior_jd = "Junior Software Engineer with 1 year experience"
    senior_jd = "Executive Director / Lead Architect with 10 years experience"

    res_sen_on_jun = ats.compute_ats_score(senior_resume, junior_jd)
    res_jun_on_sen = ats.compute_ats_score(junior_resume, senior_jd)

    assert res_sen_on_jun.experience_score >= res_jun_on_sen.experience_score


def test_date_parsing_fallbacks_and_failure_reporting():
    resume_with_date_formats = {
        "experience": [
            {
                "role": "Engineer A",
                "company": "Company A",
                "start_date": "01/2021",
                "end_date": "2022-06",
            },
            {
                "role": "Engineer B",
                "company": "Company B",
                "start_date": "Q1 2023",
                "end_date": "Present",
            },
            {
                "role": "Engineer C",
                "company": "Company C",
                "start_date": "UnparseableDateString",
                "end_date": "2021",
            }
        ]
    }
    jd = "Requirements: Python"
    res = ats.compute_ats_score(resume_with_date_formats, jd)
    assert res.candidate_years > 2.0
    assert "date_parse_warnings" in res.score_breakdown
    assert "UnparseableDateString" in res.score_breakdown["date_parse_warnings"]


def test_scoring_config_custom_override_roundtrip():
    resume = _sample_resume()
    jd = "Requirements: Python, AWS. Preferred: Docker."
    
    default_res = ats.compute_ats_score(resume, jd, config=ats.DEFAULT_SCORING_CONFIG)
    implicit_res = ats.compute_ats_score(resume, jd)
    assert default_res.skills_score == implicit_res.skills_score
    assert default_res.experience_score == implicit_res.experience_score

    custom_config = ats.ScoringConfig(skill_mandatory_weight=50.0, skill_preferred_weight=50.0)
    custom_res = ats.compute_ats_score(resume, jd, config=custom_config)
    assert custom_res.eligible is True


def test_slash_plus_skill_importance_weighting():
    jd_text = """
    CI/CD Pipeline Lead Engineer
    Requirements:
    - 5+ years of experience building CI/CD pipelines
    - Deep expertise in CI/CD automation tools
    - Knowledge of Python
    - CI/CD deployment optimization
    """
    weights = ats._compute_skill_importance_weights(jd_text, ["ci/cd", "python"])
    
    assert weights["ci/cd"] > weights["python"]
    assert weights["ci/cd"] > 0.6
