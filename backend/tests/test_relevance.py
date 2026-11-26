from services.relevance import check_relevance, level_check, location_check, sponsorship_check

PREFS = {"seniority": ["Senior", "Staff", "Lead"], "target_locations": ["London", "Remote"]}


def test_level_follows_the_levels_the_user_chose():
    assert level_check("Senior ML Engineer", PREFS)[0] is True
    assert level_check("ML Engineer", PREFS)[0] is True          # no level word: allowed
    assert level_check("Graduate Data Scientist", PREFS)[0] is False
    assert level_check("Head of AI", PREFS)[0] is False
    assert "junior" in level_check("Junior Developer", PREFS)[1]
    assert level_check("Summer Intern", {"seniority": ["intern"]})[0] is True
    assert level_check("Senior Engineer", {"seniority": ["intern"]})[0] is False
    assert level_check("Head of AI", {})[0] is True               # no preference: no rule


def test_location_accepts_city_country_and_remote():
    assert location_check("London, England, United Kingdom", PREFS)[0] is True
    assert location_check("Remote - Europe", PREFS)[0] is True
    assert location_check("Greater London Area", PREFS)[0] is True
    ok, why = location_check("Austin, TX", PREFS)
    assert ok is False and "Austin" in why
    assert location_check("", PREFS)[0] is True                   # unknown place: do not guess
    assert location_check("Paris", {})[0] is True
    assert location_check("Manchester, UK", {"target_locations": ["London, UK"]})[0] is True  # same country


def test_sponsorship_only_matters_when_the_user_needs_it():
    jd = "We are unable to offer visa sponsorship for this role."
    assert sponsorship_check(jd, {"requires_sponsorship": False})[0] is True
    assert sponsorship_check(jd, {"requires_sponsorship": True})[0] is False
    assert sponsorship_check(jd, {"requires_sponsorship": "Yes"})[0] is False
    assert sponsorship_check("We sponsor visas.", {"requires_sponsorship": True})[0] is True
    assert sponsorship_check("Must have the right to work in the UK", {"requires_sponsorship": True})[0] is False


def test_check_relevance_returns_the_first_reason():
    job = {"title": "Junior Analyst", "location": "London"}
    ok, why = check_relevance(job, "", {}, PREFS)
    assert ok is False and "junior" in why
    assert check_relevance({"title": "Senior Engineer", "location": "London, UK"}, "", {"requires_sponsorship": False}, PREFS) == (True, "")
