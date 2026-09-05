import pytest
from starlette.testclient import TestClient
from main import app

client = TestClient(app)


def test_healthz():
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "job-finder-backend"}


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "job-finder-backend"}


def test_auth_url():
    response = client.get("/auth/url")
    assert response.status_code == 200
    assert "url" in response.json()


def test_answer_question_deterministic_notice():
    response = client.post(
        "/answer_question",
        json={"question": "What is your notice period?", "company_name": "Granola"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Available immediately" in data["answer"]


def test_answer_question_deterministic_salary():
    response = client.post(
        "/answer_question",
        json={"question": "What are your salary expectations?", "company_name": "Granola"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Competitive market rate" in data["answer"]


def test_extension_parse_job_details():
    response = client.post(
        "/extension/parse_job_details",
        json={
            "page_title": "AI Engineer",
            "page_text": "We are looking for an AI Engineer at Granola to work on GenAI systems."
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["job_title"] == "AI Engineer"
    assert data["company"] == "Granola"


def test_get_session_resume_guest():
    response = client.get("/get_session_resume")
    assert response.status_code == 200
    assert "data" in response.json()


def test_applications_endpoint():
    response = client.get("/applications")
    assert response.status_code == 200
    assert "applications" in response.json()


def test_user_profile_sync():
    response = client.post(
        "/user/profile",
        headers={"Authorization": "Bearer test_sync_token"},
        json={
            "name": "Akhil Baja",
            "email": "akhilbaja.work@gmail.com",
            "location": "London, UK",
            "portfolio": "https://akhilbaja.dev",
            "notice_period": "1 month",
            "salary_expectations": "Competitive market rate",
            "work_auth": "Yes",
            "sponsorship": "No"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["profile"]["location"] == "London, UK"
    assert data["profile"]["portfolio"] == "https://akhilbaja.dev"
    assert data["profile"]["notice_period"] == "1 month"
    assert data["profile"]["work_auth"] == "Yes"
    assert data["profile"]["sponsorship"] == "No"


def test_download_extension_personalized_zip():
    import io
    import zipfile
    response = client.get("/download_extension?key=GABY48")
    assert response.status_code == 200
    assert response.headers.get("content-type") == "application/zip"
    
    zip_bytes = io.BytesIO(response.content)
    with zipfile.ZipFile(zip_bytes, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "popup.html" in namelist
        assert "popup.js" in namelist
        assert "content.js" in namelist
        
        popup_js_content = zf.read("popup.js").decode("utf-8")
        assert 'const DEFAULT_SYNC_KEY = "GABY48";' in popup_js_content


def test_user_archetypes_lifecycle():
    auth_headers = {"Authorization": "Bearer test_archetype_user_token"}
    
    # 1. Initial list
    res = client.get("/user/archetypes", headers=auth_headers)
    assert res.status_code == 200
    assert "archetypes" in res.json()

    # 2. Save GenAI Archetype
    res_save1 = client.post(
        "/user/archetypes/save",
        json={"archetype_name": "GenAI Systems Specialist", "latex_code": "% GenAI LaTeX"},
        headers=auth_headers
    )
    assert res_save1.status_code == 200
    assert res_save1.json()["active_archetype"] == "GenAI Systems Specialist"

    # 3. Save Data Science Archetype
    res_save2 = client.post(
        "/user/archetypes/save",
        json={"archetype_name": "Data Scientist", "latex_code": "% Data Science LaTeX"},
        headers=auth_headers
    )
    assert res_save2.status_code == 200
    assert res_save2.json()["active_archetype"] == "Data Scientist"

    # 4. Switch back to GenAI Archetype
    res_switch = client.post(
        "/user/archetypes/switch",
        json={"archetype_name": "GenAI Systems Specialist"},
        headers=auth_headers
    )
    assert res_switch.status_code == 200
    assert res_switch.json()["active_archetype"] == "GenAI Systems Specialist"

    # 5. Delete Data Scientist Archetype
    res_delete = client.post(
        "/user/archetypes/delete",
        json={"archetype_name": "Data Scientist"},
        headers=auth_headers
    )
    assert res_delete.status_code == 200
    archetype_names = [a["name"] for a in res_delete.json()["archetypes"]]
    assert "Data Scientist" not in archetype_names
    assert "GenAI Systems Specialist" in archetype_names


def test_job_analysis_tailoring_intensity_schema():
    from routes.ai_routes import JobAnalysisRequest, TailorResumeRequest
    
    req1 = JobAnalysisRequest(job_title="SWE", tailoring_intensity="impact")
    assert req1.tailoring_intensity == "impact"

    req2 = TailorResumeRequest(job_title="SWE", job_description="Python Docker", tailoring_intensity="conservative")
    assert req2.tailoring_intensity == "conservative"


def test_search_jobs_request_schema():
    from routes.job_routes import SearchJobsRequest
    # When user leaves role and keywords blank, role should be None
    req_blank = SearchJobsRequest(keywords=None, role=None)
    assert req_blank.role is None
    assert req_blank.keywords is None

    # When user specifies role
    req_role = SearchJobsRequest(role="Product Engineer", timeframe="7d")
    assert req_role.role == "Product Engineer"
    assert req_role.timeframe == "7d"



