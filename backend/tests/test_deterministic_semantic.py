from services.ats_scorer import compute_ats_score, deterministic_semantic_analysis

RESUME = {
    "location": "Hyderabad",
    "skills": ["Python", "SQL", "Snowflake", "XGBoost"],
    "experience": [
        {"role": "Data Scientist", "company": "A", "start_date": "Jan 2022", "end_date": "Present",
         "description": ["Built Python and SQL pipelines on Snowflake"]},
    ],
}
JD = "Senior Data Engineer\nRequires 6+ years of experience. Must know Python, SQL, Snowflake and Spark. Security clearance required."


def test_same_input_same_output():
    ats = compute_ats_score(RESUME, JD)
    a = deterministic_semantic_analysis(RESUME, JD, ats)
    b = deterministic_semantic_analysis(RESUME, JD, compute_ats_score(RESUME, JD))
    assert a == b


def test_required_counts_populated():
    ats = compute_ats_score(RESUME, JD)
    assert ats.total_required_count > 0
    assert 0 <= ats.matched_required_count <= ats.total_required_count


def test_shape_and_flags():
    ats = compute_ats_score(RESUME, JD)
    out = deterministic_semantic_analysis(RESUME, JD, ats)
    assert 0 <= out["role_fit_score"] <= 100
    assert 3 <= len(out["tailoring_suggestions"]) <= 5
    assert len(out["red_flags"]) <= 3
    assert "Requires security clearance" in out["red_flags"] or len(out["red_flags"]) == 3
