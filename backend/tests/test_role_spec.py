"""Offline tests for topic/level parsing, expansion and the title relevance filter."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services import role_spec as rs  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_cache_path", lambda: str(tmp_path / "topic_terms.json"))


def fake_llm(topic):
    return {"quantum computing": ["quantum", "qml", "quantum software", "quantum machine learning", "engineer"],
            "applied ai": ["ai", "machine learning", "llm", "generative ai"]}.get(topic.lower(), [])


@pytest.mark.parametrize("text,topics,level", [
    ("quantum computing internships", ["quantum computing"], "intern"),
    ("agentic AI, applied AI and AI engineering interns", ["agentic AI", "applied AI", "AI engineering"], "intern"),
    ("robotics graduate roles", ["robotics"], "graduate"),
    ("find me entry-level data jobs", ["data"], "junior"),
    ("AI/ML internship", ["AI/ML"], "intern"),
    ("senior rust", ["rust"], "senior"),
    ("climate tech", ["climate tech"], None),
    ("", [], None),
])
def test_parse_request(text, topics, level):
    assert rs.parse_request(text) == (topics, level)


def test_normalize_level():
    assert rs.normalize_level("Internship") == "intern"
    assert rs.normalize_level(None) is None
    with pytest.raises(ValueError):
        rs.normalize_level("interm")


def test_queries_combine_topics_and_level():
    spec = rs.resolve_spec(request="quantum computing internships", llm=fake_llm)
    assert spec.queries == ["quantum computing Intern", "quantum computing Internship"]
    assert rs.resolve_spec(topic="robotics", level="any", llm=fake_llm).queries == ["robotics"]


def test_topic_matching_is_not_ai_specific():
    spec = rs.resolve_spec(request="quantum computing internships", llm=fake_llm)
    ok = lambda t: spec.matches(t)[0]  # noqa: E731
    assert ok("Quantum Software Intern")
    assert ok("QML Research Internship")
    assert ok("Quantum Computing Industrial Placement")
    assert not ok("Marketing Intern")                       # off topic
    assert not ok("Quantum Software Engineer")              # right topic, wrong level
    assert not ok("Senior Quantum Intern Programme Lead")   # senior title never passes an intern search
    assert not ok("Internal Tools Engineer, Quantum")       # 'internal' is not 'intern'


def test_generic_words_from_the_llm_are_dropped():
    spec = rs.resolve_spec(topic="quantum computing", level="intern", llm=fake_llm)
    assert "engineer" not in spec.topic_terms
    assert not spec.matches("Software Engineer Intern")[0]


def test_ai_topic_still_works_and_stays_title_based():
    spec = rs.resolve_spec(topic="applied AI", level="intern", llm=fake_llm)
    assert spec.matches("Generative AI Intern")[0]
    assert spec.matches("Machine Learning Engineer Internship")[0]
    assert not spec.matches("Tax Technology Intern")[0]
    assert not spec.matches("Research Fellow in Medical Image Analysis")[0]


def test_loose_mode_reads_description():
    strict = rs.resolve_spec(topic="quantum computing", level="intern", llm=fake_llm)
    loose = rs.resolve_spec(topic="quantum computing", level="intern", llm=fake_llm, loose=True)
    desc = "Internship placing you on our quantum team. Quantum hardware, quantum algorithms and quantum control."
    assert not strict.matches("Summer Project", desc)[0]
    assert loose.matches("Summer Project", desc)[0]


def test_exact_skips_llm(monkeypatch):
    def boom(topic):
        raise AssertionError("LLM must not be called with exact=True")
    spec = rs.resolve_spec(topic="quantum computing", level="intern", exact=True, llm=boom)
    assert "quantum" in spec.topic_terms and "qml" not in spec.topic_terms


def test_role_titles_are_expanded_like_topics_and_cover_all_levels_unless_one_is_given():
    spec = rs.resolve_spec(role="Exact Query, Other Query", llm=lambda t: {})
    assert spec.split and spec.topics == ["Exact Query", "Other Query"] and spec.level == "any"       # no level typed -> every level
    assert spec.queries[:2] == ["Exact Query", "Other Query"]
    one = rs.resolve_spec(role="Exact Query", level="intern", llm=lambda t: {})
    assert not one.split and one.level == "intern" and one.matches("Exact Query Intern")[0] and not one.matches("Exact Query")[0]


def test_profile_defaults_apply_only_when_nothing_was_typed():
    prefs = {"topics": ["applied AI"], "level": "intern"}
    assert rs.resolve_spec(prefs=prefs, llm=fake_llm).queries == ["applied AI Intern", "applied AI Internship"]       # bare scan: profile
    spec = rs.resolve_spec(topic="quantum computing", prefs=prefs, llm=fake_llm)                                      # typed, no level
    assert spec.split and spec.topics == ["quantum computing"]                                                        # -> ALL levels, not the profile's intern
    assert rs.resolve_spec(topic="quantum computing", level="graduate", prefs=prefs, llm=fake_llm).level == "graduate"
    assert rs.resolve_spec(request="robotics roles", level="any", prefs=prefs, llm=fake_llm).level == "any"          # 'any' = one mixed list
    assert rs.resolve_spec(prefs={}) is None


def test_expansion_is_cached(tmp_path):
    calls = []
    def llm(topic):
        calls.append(topic)
        return ["quantum", "qml"]
    rs.expand_topic("Quantum Computing", llm=llm)
    rs.expand_topic("quantum computing", llm=lambda t: calls.append("again") or [])
    assert calls == ["Quantum Computing"]
    assert "qml" in json.load(open(rs._cache_path()))["quantum computing"]["include"]


def test_llm_failure_falls_back_to_own_words():
    terms = rs.expand_topic("quantum computing", llm=lambda t: [])
    assert terms[0] == "quantum computing" and "quantum" in terms and "computing" not in terms


# ─── multi-word topics (e.g. "AI cyber security") ────────────────────────────
def test_multiword_topic_is_not_split_into_separate_alternatives():
    spec = rs.resolve_spec(topic="AI cyber security", level="intern", exact=True)
    assert not spec.matches("AI Engineer Intern")[0]              # 'AI' alone is not the topic
    assert not spec.matches("Security Guard Intern")[0]           # nor is 'security' alone
    assert spec.matches("Cyber Security Intern (AI)")[0]          # all the words, any order
    assert spec.matches("AI & Cyber-Security Research Intern")[0]


def test_joined_and_hyphenated_spellings_match():
    spec = rs.resolve_spec(topic="cyber security", level="intern", exact=True)
    for title in ("Cybersecurity Intern", "Cyber Security Intern", "Cyber-Security Analyst Intern"):
        assert spec.matches(title)[0], title
    assert not spec.matches("Security Guard Intern")[0]


def test_commas_mean_alternatives_so_both_niches_can_be_searched():
    spec = rs.resolve_spec(topic="AI security, cyber security", level="intern", exact=True)
    assert spec.matches("AI Security Intern")[0] and spec.matches("Cyber Security Intern")[0]
    assert not spec.matches("AI Engineer Intern")[0]
    assert spec.queries == ["AI security Intern", "cyber security Intern", "AI security Internship", "cyber security Internship"]


def test_single_meaningful_word_topics_still_match_on_that_word():
    spec = rs.resolve_spec(topic="quantum computing", level="intern", exact=True)
    assert spec.matches("Quantum Algorithms Intern")[0] and not spec.matches("Computing Intern")[0]


# ─── topics are FIELDS: "cyber security" = anything security, "applied AI" = ML engineer / researcher ... ─────────
def family_llm(topic):
    return {
        "cyber security": {
            "include": ["security", "cyber", "infosec", "appsec", "software security", "application security", "system security",
                        "ai security", "llm security", "ml security", "penetration testing", "pentest", "threat intelligence",
                        "incident response", "malware", "cryptography", "devsecops", "red team", "engineer"],
            "exclude": ["security guard", "security officer", "social security", "door supervisor"],
            "search": ["application security", "penetration testing", "AI security", "threat intelligence"]},
        "applied ai": {
            "include": ["ai", "ml", "machine learning", "deep learning", "ai researcher", "ml researcher", "research scientist",
                        "applied scientist", "nlp", "computer vision", "llm", "generative ai", "data scientist"],
            "exclude": ["ai-powered sales"],
            "search": ["machine learning", "ML research", "AI researcher", "deep learning"]},
    }.get(topic.lower(), {})


def test_cyber_security_means_anything_security():
    spec = rs.resolve_spec(request="cyber security internships", llm=family_llm)
    for title in ("Software Security Intern", "AI Security Intern", "LLM Security Research Intern", "System Security Intern",
                  "Application Security Engineer Intern", "Penetration Testing Intern", "Threat Intelligence Analyst Intern",
                  "Cybersecurity Intern", "Security Engineering Intern", "DevSecOps Intern", "Cryptography Research Intern"):
        assert spec.matches(title)[0], title
    for title in ("Security Guard Intern", "Security Officer Intern", "Social Security Admin Intern", "Marketing Intern"):
        assert not spec.matches(title)[0], title
    assert "look-alike" in spec.matches("Security Guard Intern")[1]


def test_applied_ai_also_finds_ml_engineers_and_researchers():
    spec = rs.resolve_spec(request="applied AI internships", llm=family_llm)
    for title in ("ML Engineer Intern", "Machine Learning Researcher Intern", "AI Researcher Intern", "Research Scientist Intern",
                  "Applied Scientist Intern", "NLP Research Internship", "Computer Vision Intern", "Generative AI Intern"):
        assert spec.matches(title)[0], title
    assert not spec.matches("Marketing Intern")[0] and not spec.matches("Senior ML Engineer")[0]


def test_generic_words_are_dropped_from_the_family_and_exclusions_never_overlap_inclusions():
    fam = rs._normalize_family({"include": ["security", "Engineer", "software", "Cyber  Security", "senior security"],
                                "exclude": ["security guard", "security"], "search": ["app sec", "Penetration Testing"]})
    assert fam.include == ["security", "cyber security"]
    assert fam.exclude == ["security guard"]
    assert fam.search == ["app sec", "penetration testing"]
    assert rs._normalize_family(["ml", "engineer"]).include == ["ml"]          # a plain list still works


def test_queries_cover_each_sub_field_not_just_the_topic():
    spec = rs.resolve_spec(request="cyber security internships", llm=family_llm)
    assert spec.queries[0] == "cyber security Intern"
    assert {"application security Intern", "penetration testing Intern", "ai security Intern", "threat intelligence Intern"} <= set(spec.queries)
    assert spec.queries[-1] == "cyber security Internship" and len(spec.queries) <= 12


def test_queries_are_shared_fairly_between_topics_and_capped():
    q = rs.build_queries(["a", "b", "c"], "intern", [["a1", "a2", "a3", "a4"], ["b1", "b2", "b3", "b4"], ["c1", "c2", "c3", "c4"]])
    assert q[:3] == ["a Intern", "b Intern", "c Intern"] and q[3:6] == ["a1 Intern", "b1 Intern", "c1 Intern"]
    assert len(q) == 12 and "a4 Intern" not in q          # capped; round-robin means no topic is starved


def test_user_edits_to_the_cache_file_are_respected_without_calling_the_llm():
    path = rs._cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"quantum computing": {"include": ["quantum", "photonics"], "exclude": ["quantum leap"], "search": ["photonics"]}},
              open(path, "w"))
    spec = rs.resolve_spec(topic="quantum computing", level="intern",
                           llm=lambda t: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
    assert spec.matches("Photonics Intern")[0] and not spec.matches("Quantum Leap Intern")[0]


def test_an_old_narrow_cache_entry_is_refreshed_with_the_broad_family():
    path = rs._cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"cyber security": ["ai security"]}, open(path, "w"))                  # older flat-list format
    spec = rs.resolve_spec(topic="cyber security", level="intern", llm=family_llm)
    assert spec.matches("Software Security Intern")[0]
    assert "include" in json.load(open(path))["cyber security"]


def test_refresh_regenerates_the_family(monkeypatch):
    calls = []
    def llm(t):
        calls.append(t)
        return {"include": ["a%d" % len(calls)]}
    rs.get_family("x topic", llm=llm)
    rs.get_family("x topic", llm=llm)
    assert len(calls) == 1
    assert rs.get_family("x topic", llm=llm, refresh=True).include == ["a2"]


def test_singular_and_plural_forms_match_either_way():
    spec = rs.resolve_spec(topic="digital forensics", level="intern", exact=True)
    for title in ("Digital Forensic Placement", "Digital Forensics Intern", "Digital-Forensic Analyst Intern"):
        assert spec.matches(title)[0], title
    spec = rs.resolve_spec(topic="ml researcher", level="intern", exact=True)
    assert spec.matches("ML Researchers Intern")[0] and spec.matches("ML Researcher Internship")[0]
    assert not rs.resolve_spec(topic="ai", level="intern", exact=True).matches("Aid Worker Intern")[0]   # no loose substring matching


def test_science_scientist_research_researcher_engineer_engineering_are_the_same_family():
    """Regression from a live dry run: 'Applied Science Intern' and 'Data Science PhD Intern' were dropped as off topic."""
    spec = rs.resolve_spec(topic="applied AI engineer", level="intern", exact=False,
                           llm=lambda t: {"include": ["applied scientist", "data scientist", "ml researcher", "ai engineer"], "exclude": [], "search": []})
    for title in ("Applied Science Intern - PhD - 2027 - London", "Data Science PhD Intern, 2027", "ML Research Intern",
                  "AI Engineering Intern", "Applied Scientist Intern", "Data Scientists Intern"):
        assert spec.matches(title)[0], title
    assert not spec.matches("Computer Science Teacher Intern")[0]                  # 'science' alone is not 'data science'
    assert not spec.matches("Marketing Intern")[0]


# ─── regressions from a live graduate cyber-security scan ─────────────────────────────────────
def test_generic_business_words_in_the_model_family_cannot_match_everything():
    """The model's 'ai safety' map contained 'strategy' and 'operations', which matched every 'Operations Associate'."""
    spec = rs.resolve_spec(topic="ai safety", level="graduate", llm=lambda t: {
        "include": ["ai safety", "alignment researcher", "strategy", "operations", "control", "policy analyst", "game theory", "fairness"],
        "exclude": [], "search": []})
    for junk in ("Operations Associate", "AI Operations Associate", "Graduate Strategy Associate", "Graduate Operations Analyst",
                 "Graduate Policy Analyst", "Graduate Control Engineer"):
        assert not spec.matches(junk)[0], junk
    assert spec.matches("Graduate AI Safety Researcher")[0] and spec.matches("Junior Alignment Researcher")[0]
    assert "operations" not in spec.topic_terms and "strategy" not in spec.topic_terms


def test_a_stale_cached_family_with_generic_words_is_cleaned_when_read(tmp_path):
    import json as _j
    path = rs._cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _j.dump({"ai safety": {"include": ["ai safety", "operations", "strategy"], "exclude": [], "search": []}}, open(path, "w"))
    fam = rs.get_family("ai safety", llm=lambda t: (_ for _ in ()).throw(AssertionError("must use the cache")))
    assert fam.include == ["ai safety"]


def test_tester_testing_hacker_hacking_defence_defense_are_one_family():
    spec = rs.resolve_spec(topic="penetration testing, ethical hacking, cyber defence", level="graduate", exact=False,
                           llm=lambda t: {"include": [t.lower()], "exclude": [], "search": []})
    for title in ("Junior Penetration Tester", "Graduate Ethical Hacker", "Graduate Cyber Defense Analyst", "Graduate Penetration Testing Consultant"):
        assert spec.matches(title)[0], title


def test_all_levels_queries_cover_plain_intern_and_graduate_wordings():
    spec = rs.resolve_spec(topic="ai security engineer", llm=lambda t: {"include": ["ai security"], "exclude": [], "search": ["llm security", "ml security researcher"]})
    q = spec.queries
    assert q[0] == "ai security engineer" and "llm security" in q                     # plain titles first (they find experienced roles)
    assert "ai security engineer Intern" in q and "ai security engineer Graduate" in q and "llm security Graduate" in q
    assert 6 <= len(q) <= 28


def test_experienced_level_excludes_intern_and_graduate_titles():
    spec = rs.resolve_spec(topic="security", level="experienced", exact=True)
    assert spec.matches("Security Engineer")[0] and spec.matches("Senior Security Engineer")[0]
    assert not spec.matches("Security Intern")[0] and not spec.matches("Graduate Security Engineer")[0] and not spec.matches("Junior Security Analyst")[0]


def test_legal_and_privacy_roles_are_not_security_jobs(monkeypatch):
    fam = {"core": ["ai security"], "include": ["ai security", "privacy", "governance", "security", "privacy engineer"],
           "exclude": [], "search": []}
    monkeypatch.setattr(rs, "_llm_terms", lambda topic, llm=None: fam)
    monkeypatch.setattr(rs, "_cache_path", lambda: os.devnull + ".none")
    spec = rs.resolve_spec(topic="ai security", level="all", llm=lambda p: fam)
    for title in ("Senior Privacy Counsel", "Data Privacy Lawyer", "Corporate Governance Paralegal", "Head of Privacy"):
        assert not spec.matches(title)[0], title
    assert spec.matches("Privacy Engineer")[0] and spec.matches("AI Security Engineer")[0]
    # a search that is about legal work keeps legal titles
    legal = rs.resolve_spec(topic="privacy counsel", level="all", exact=True)
    assert legal.matches("Senior Privacy Counsel")[0]
