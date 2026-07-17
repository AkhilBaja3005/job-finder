import services.ats_scorer as ats


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
    # Bare "go" with no engineering context should NOT match (avoids "go to
    # market", "go-getter", etc. false positives).
    no_context = ats._extract_taxonomy_skills("We go the extra mile for every customer")
    assert "go" not in no_context

    # "golang" always matches regardless of surrounding words.
    assert "go" in ats._extract_taxonomy_skills("5 years of golang experience")

    # Bare "go" near an engineering-context word should match.
    assert "go" in ats._extract_taxonomy_skills("Go programming language backend services")


def test_extract_taxonomy_skills_non_tech_domains():
    product = ats._extract_taxonomy_skills("Led product roadmap and ran A/B testing experiments using Jira")
    assert "product management" not in product  # "roadmap" implies roadmapping, not product management itself
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
    assert "quickbooks" in finance  # netsuite aliases to quickbooks canonical


def test_extract_taxonomy_skills_empty_text():
    assert ats._extract_taxonomy_skills("") == set()
    assert ats._extract_taxonomy_skills(None) == set()


# ─────────────────────────────────────────────────────────────────────────────
# High-risk token context guards (go/pipeline/airflow/spark/excel/lean/sap) —
# each is a common English word with a much more frequent non-skill meaning,
# so a bare match with no nearby guard word must NOT register as a skill.
# ─────────────────────────────────────────────────────────────────────────────

def test_high_risk_tokens_reject_generic_english_usage():
    assert ats._extract_taxonomy_skills("I always strive to excel in a fast-paced environment") == set()
    assert ats._extract_taxonomy_skills("We must stay lean given the budget") == set()
    assert ats._extract_taxonomy_skills("This decision could sap morale across the team") == set()
    assert ats._extract_taxonomy_skills("We built a strong sales pipeline this quarter") == set()
    assert ats._extract_taxonomy_skills("Managing our hiring pipeline for new candidates") == set()
    assert ats._extract_taxonomy_skills("This project will spark innovation across teams") == set()
    assert ats._extract_taxonomy_skills("The candidate should spark curiosity in others") == set()
    # "CV" almost always means "curriculum vitae" in resume/JD text, not computer vision.
    assert ats._extract_taxonomy_skills("Please submit your CV and cover letter to apply") == set()


def test_high_risk_tokens_match_with_proper_context():
    assert "excel" in ats._extract_taxonomy_skills("Advanced skills in Microsoft Excel with pivot tables")
    assert "process improvement" in ats._extract_taxonomy_skills("Experience with Lean Six Sigma methodology")
    assert "sap" in ats._extract_taxonomy_skills("Experience with SAP ERP and S4 HANA modules")
    assert "airflow" in ats._extract_taxonomy_skills("Built ETL data pipelines using Apache Airflow")
    assert "apache spark" in ats._extract_taxonomy_skills("We use Apache Spark for big data processing")
    # "computer vision" (the multi-word alias) still matches on its own.
    assert "computer vision" in ats._extract_taxonomy_skills("Experience with computer vision and object detection")


# ─────────────────────────────────────────────────────────────────────────────
# extract_jd_skills — required vs preferred bucketing
# ─────────────────────────────────────────────────────────────────────────────

def test_extract_jd_skills_does_not_leak_generic_pipeline_requirement():
    # Regression: a sales JD mentioning "pipeline management" must not extract
    # "pipeline" as a required *data engineering* skill keyword — it previously
    # did, because "pipeline" had no context guard at all.
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
    # Preferred set must not double-count anything already required.
    assert not (set(required) & set(preferred))


# ─────────────────────────────────────────────────────────────────────────────
# calculate_flattened_experience — timeline merging & overlap handling
# ─────────────────────────────────────────────────────────────────────────────

def test_calculate_flattened_experience_merges_overlapping_jobs():
    resume = {
        "experience": [
            {"company": "A", "role": "Engineer", "start_date": "Jan 2020", "end_date": "Dec 2021", "description": []},
            # Overlaps with the job above (started while it was still active)
            {"company": "B", "role": "Engineer", "start_date": "Jun 2021", "end_date": "Present", "description": []},
        ]
    }
    years, avg_tenure, segments = ats.calculate_flattened_experience(resume)
    # Merged timeline should be a single continuous segment, not double-counted.
    assert len(segments) == 1
    assert years > 0


def test_calculate_flattened_experience_no_valid_dates():
    resume = {"experience": [{"company": "A", "role": "Engineer", "start_date": "", "end_date": "", "description": []}]}
    years, avg_tenure, segments = ats.calculate_flattened_experience(resume)
    assert years == 0.0
    assert segments == []


# ─────────────────────────────────────────────────────────────────────────────
# Seniority tier resolution priority (executive > lead > senior > mid > junior)
# ─────────────────────────────────────────────────────────────────────────────

def test_seniority_tier_resolves_to_highest_priority_match():
    # "Senior Software Engineer" contains keywords for both "senior" and "mid"
    # ("engineer") — must resolve to "senior" (higher priority), not "mid".
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
    # A JD with no recognizable taxonomy skills at all (e.g. a non-technical
    # domain not covered by SKILL_ALIASES) must not be scored as a false 100%
    # match — compute_skills_score's neutral-default path should kick in.
    jd = "We need someone who is a great team player with excellent communication."
    result = ats.compute_ats_score(_sample_resume(), jd)
    assert result.skills_score == 60
    assert result.matched_skills == []


def test_compute_overall_score_formula():
    # 40% skills + 35% experience + 25% role_fit
    assert ats.compute_overall_score(100, 100, 100) == 100
    assert ats.compute_overall_score(0, 0, 0) == 0
    assert ats.compute_overall_score(80, 60, 40) == round(0.40 * 80 + 0.35 * 60 + 0.25 * 40)
