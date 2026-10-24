from __future__ import annotations

import asyncio
import json
import sqlite3
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from masar_app import app as app_module
from pypdf import PdfReader


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(app_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(app_module, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(app_module, "DB_PATH", tmp_path / "test.db")
    app_module.runtime_secrets["ai_provider"] = "openrouter"
    app_module.runtime_secrets["openrouter_key"] = ""
    app_module.runtime_secrets["openai_key"] = ""
    app_module.runtime_secrets["ollama"] = {
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3:4b",
        "search_api_key": "",
        "searxng_url": "",
        "connected": False,
        "models": [],
    }
    app_module.runtime_secrets["smtp"] = {}
    app_module.init_db()
    return TestClient(app_module.app)


def profile_payload() -> dict:
    return {
        "full_name": "Dana Haddad",
        "email": "dana@example.com",
        "phone": "+962 7 9000 0000",
        "city": "Amman",
        "country": "Jordan",
        "university": "University of Jordan",
        "degree": "BSc Computer Science",
        "graduation": "June 2027",
        "preferred_roles": ["Data science intern"],
        "disciplines": ["Computer science", "Data science"],
        "search_locations": ["Amman"],
        "skills": ["Python", "SQL", "pandas"],
        "workplace": ["On-site", "Hybrid"],
        "ai_consent": True,
    }


def test_profile_cv_and_demo_safety(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.put("/api/profile", json=profile_payload()).status_code == 200

    cv = b"Dana Haddad\nComputer Science student\nPython, SQL, pandas\nBuilt a classification project."
    response = client.post("/api/cv", files={"file": ("Dana-CV.txt", cv, "text/plain")})
    assert response.status_code == 200
    assert response.json()["characters"] > 40

    assert client.post("/api/jobs/demo", json={}).status_code == 200
    state = client.get("/api/state").json()
    assert state["profile"]["cv_ready"] is True
    assert len(state["jobs"]) == 3
    assert all(job["demo"] for job in state["jobs"])

    demo_id = state["jobs"][0]["id"]
    blocked = client.patch(f"/api/jobs/{demo_id}/selection", json={"selected": True})
    assert blocked.status_code == 409


def test_approval_gates_for_real_job(client: TestClient) -> None:
    client.put("/api/profile", json=profile_payload())
    client.post(
        "/api/cv",
        files={
            "file": (
                "Dana-CV.txt",
                b"Dana Haddad\nPython and SQL student with data analysis projects and strong communication.",
                "text/plain",
            )
        },
    )
    with sqlite3.connect(app_module.DB_PATH) as connection:
        connection.execute(
            """INSERT INTO jobs
            (id,title,company,location,workplace,employment_type,summary,requirements,url,source,
             contact_email,posted_date,match_score,match_reasons,gaps,selected,demo,verified,discovered_at)
            VALUES ('real-1','Data Intern','Example Co','Amman, Jordan','Hybrid','Internship',
                    'Analyze data','[\"Python\"]','https://example.com/job','Example Co',
                    'careers@example.com','Today',88,'[\"Python\"]','[]',0,0,1,'2026-08-29T00:00:00Z')"""
        )

    # Preparation ignores jobs that were not explicitly selected.
    result = client.post("/api/applications/prepare", json={"job_ids": ["real-1"]})
    assert result.json()["count"] == 0

    client.patch("/api/jobs/real-1/selection", json={"selected": True})
    result = client.post("/api/applications/prepare", json={"job_ids": ["real-1"]})
    assert result.status_code == 200
    assert result.json()["count"] == 1

    state = client.get("/api/state").json()
    application = state["applications"][0]
    assert application["approved"] is False
    assert application["status"] == "draft"

    client.patch(f"/api/applications/{application['id']}", json={"approved": True})
    send = client.post(
        "/api/applications/send",
        json={"application_ids": [application["id"]], "confirm_send": True},
    )
    assert send.status_code == 409
    assert "Connect your email" in send.json()["detail"]


def test_url_verifier_rejects_local_addresses() -> None:
    assert asyncio.run(app_module.verify_url("http://127.0.0.1:8765/api/health")) is False
    assert asyncio.run(app_module.verify_url("http://localhost:8765")) is False


def test_job_parser_accepts_structured_object_and_content_parts() -> None:
    content = [
        {"type": "text", "text": '```json\n{"jobs":[{"title":"AI Intern"}]}\n```'},
    ]
    assert app_module.extract_json_array(content) == [{"title": "AI Intern"}]


def test_prepare_opportunity_enforces_quality_rules() -> None:
    base = {
        "company": "Example AI",
        "title": "Senior AI Engineer",
        "location": "Amman, Jordan",
        "url": "https://example.com/jobs/ai",
        "confidence_score": 90,
    }
    assert app_module.prepare_opportunity(base, "open_roles") is None

    outreach = app_module.prepare_opportunity(
        {
            **base,
            "title": "Company profile",
            "url": "https://example.com/about",
            "contact_email": "careers@example.com",
            "match_score": "88",
        },
        "company_outreach",
    )
    assert outreach is not None
    assert outreach["opportunity_kind"] == "outreach"
    assert outreach["title"] == "Proactive Internship Inquiry"
    assert outreach["contact_email"] == "careers@example.com"


def test_three_track_discovery_deduplicates_and_verifies_contacts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/profile", json=profile_payload())
    client.post(
        "/api/cv",
        files={
            "file": (
                "Dana-CV.txt",
                b"Dana Haddad\nAI student with Python, SQL, machine learning and data analysis projects.",
                "text/plain",
            )
        },
    )

    async def fake_research(**kwargs):
        if kwargs["track"] == "open_roles":
            return ([{
                "title": "AI Intern",
                "company": "Alpha AI",
                "location": "Amman, Jordan",
                "url": "https://alpha.example/jobs/ai-intern",
                "source": "Alpha careers",
                "match_score": 91,
                "confidence_score": 94,
                "requirements": ["Python"],
                "match_reasons": ["Python projects"],
            }], 5)
        return ([
            {
                "company": "Alpha AI",
                "location": "Amman, Jordan",
                "url": "https://alpha.example/about",
                "summary": "AI company",
                "match_score": 87,
                "confidence_score": 90,
            },
            {
                "company": "Beta Data",
                "location": "Amman, Jordan",
                "url": "https://beta.example/careers",
                "summary": "Data engineering consultancy",
                "contact_email": "jobs@beta.example",
                "match_score": 84,
                "confidence_score": 89,
            },
        ], 6)

    async def fake_inspect(url: str, contact_email: str = ""):
        return {"reachable": True, "email_present": False}

    monkeypatch.setattr(app_module, "research_opportunity_track", fake_research)
    monkeypatch.setattr(app_module, "inspect_source", fake_inspect)
    response = client.post(
        "/api/jobs/discover",
        json={
            "keywords": "AI, data science",
            "location": "Amman, Jordan",
            "max_results": 6,
            "include_outreach": True,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["openings"] == 1
    assert result["outreach"] == 1
    assert result["sources_scanned"] == 17

    jobs = client.get("/api/state").json()["jobs"]
    assert len(jobs) == 2
    assert {job["opportunity_kind"] for job in jobs} == {"opening", "outreach"}
    beta = next(job for job in jobs if job["company"] == "Beta Data")
    assert beta["contact_email"] == ""
    assert beta["confidence_score"] == 82
    assert any("could not be confirmed" in gap for gap in beta["gaps"])


def test_location_quality_rule_uses_runtime_search_target() -> None:
    item = {
        "company": "Atelier Exemple",
        "title": "Architecture Intern",
        "location": "Paris, France",
        "url": "https://example.fr/careers/intern",
        "confidence_score": 91,
    }
    assert app_module.prepare_opportunity(item, "open_roles", "Paris", "France") is not None
    assert app_module.prepare_opportunity(item, "open_roles", "Berlin", "Germany") is None


def test_company_key_collapses_descriptive_and_legal_suffixes() -> None:
    assert app_module.company_key("Zain Jordan (Zain Careers)") == app_module.company_key("Zain Jordan")
    assert app_module.company_key("Example Labs, LLC") == app_module.company_key("Example Labs")


def test_ai_dispatch_uses_selected_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_openai(*args, **kwargs):
        calls.append("openai")
        return {"content": "ok"}

    monkeypatch.setattr(app_module, "openai_chat", fake_openai)
    app_module.runtime_secrets["ai_provider"] = "openai"
    result = asyncio.run(app_module.ai_chat([{"role": "user", "content": "hello"}]))
    assert result["content"] == "ok"
    assert calls == ["openai"]


def test_system_capabilities_has_actionable_recommendation(client: TestClient) -> None:
    response = client.get("/api/system/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["memory_gb"] >= 0
    assert data["recommendation"]["model"].startswith("qwen3:")
    assert data["recommendation"]["download_size"]


def test_public_contact_enrichment_keeps_only_verified_professional_contacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = [{
        "company": "Example Labs",
        "url": "https://example.com/careers",
        "official_domain": "example.com",
        "contact_email": "",
        "contact_name": "",
        "contact_role": "",
        "public_contacts": [],
    }]

    async def fake_research(*args, **kwargs):
        return ([
            {
                "company": "Example Labs, LLC",
                "name": "Dana Recruiter",
                "role": "Talent Acquisition Partner",
                "email": "dana@example.com",
                "url": "https://example.com/team/dana",
                "source": "Example team page",
            },
            {
                "company": "Example Labs",
                "name": "Pat Engineer",
                "role": "Software Engineer",
                "email": "pat@gmail.com",
                "url": "https://example.com/team/pat",
                "source": "Example team page",
            },
        ], 2)

    async def fake_inspect(url: str, email: str = "", name: str = "", company: str = ""):
        return {
            "reachable": True,
            "email_present": email == "dana@example.com",
            "name_present": name == "Dana Recruiter",
            "hr_signal": True,
            "company_present": company == "Example Labs",
        }

    monkeypatch.setattr(app_module, "research_public_contacts", fake_research)
    monkeypatch.setattr(app_module, "inspect_source", fake_inspect)
    count, sources = asyncio.run(
        app_module.enrich_public_contacts(jobs, field="Biology", location="Paris", country="France")
    )
    assert count == 1
    assert sources == 2
    assert jobs[0]["public_contacts"][0]["email"] == "dana@example.com"
    assert jobs[0]["public_contacts"][0]["source_type"] == "official_company_page"
    assert jobs[0]["contact_name"] == "Dana Recruiter"
    assert all(contact["email"] != "pat@gmail.com" for contact in jobs[0]["public_contacts"])


def test_public_contact_research_uses_small_company_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_sizes: list[int] = []
    jobs = [
        {
            "company": f"Company {index}",
            "url": f"https://company{index}.example/careers",
            "official_domain": f"company{index}.example",
            "public_contacts": [],
        }
        for index in range(9)
    ]

    async def fake_batch(batch, **kwargs):
        batch_sizes.append(len(batch))
        company = batch[0]["company"]
        return ([{
            "company": company,
            "name": f"Recruiter at {company}",
            "role": "Recruiter",
            "email": "",
            "url": f"https://linkedin.com/in/recruiter-{company.lower().replace(' ', '-')}",
            "source": "LinkedIn",
            "source_type": "linkedin_profile",
        }], 2)

    monkeypatch.setattr(app_module, "research_public_contacts_batch", fake_batch)
    contacts, sources = asyncio.run(
        app_module.research_public_contacts(
            jobs, field="Data Science", location="Amman", country="Jordan"
        )
    )
    assert sorted(batch_sizes) == [1, 4, 4]
    assert len(contacts) == 3
    assert sources == 6


def test_public_contact_source_type_is_inferred_from_verified_url() -> None:
    job = {"official_domain": "example.com"}
    assert app_module.public_contact_source_type(
        "https://www.linkedin.com/in/dana-recruiter", job
    ) == "linkedin_profile"
    assert app_module.public_contact_source_type(
        "https://linkedin.com/posts/dana_hiring-activity-123", job
    ) == "linkedin_post"
    assert app_module.public_contact_source_type(
        "https://careers.example.com/people", job
    ) == "official_company_page"


def test_cv_review_export_and_stale_source_guard(client: TestClient) -> None:
    client.put("/api/profile", json=profile_payload())
    source = b"Dana Haddad\ndana@example.com\nEDUCATION\nBSc Computer Science\nEXPERIENCE\nBuilt data science tools for 500 students.\nSKILLS\nPython, SQL\nPROJECTS\nDeveloped reporting tools with 23 tests."
    client.post("/api/cv", files={"file": ("cv.txt", source, "text/plain")})
    result = client.post("/api/cv/review", json={"use_ai": False})
    assert result.status_code == 200
    review = result.json()["review"]
    assert review["score"] == sum(item["score"] for item in review["criteria"])
    assert review["rewrite_mode"] == "original"
    edited = review["document"]
    edited["sections"] = [{"heading": "Experience", "body": "## Analyst\n- Built reporting tools for 500 students.\n- Escaped <script> & content."}]
    assert client.put("/api/cv/review/document", json={"source_hash":review["source_hash"], "document":edited}).status_code == 200
    pdf = client.get("/api/cv/review/pdf?download=true")
    assert pdf.status_code == 200
    assert "attachment" in pdf.headers["content-disposition"]
    parsed = PdfReader(BytesIO(pdf.content))
    text = "".join(page.extract_text() for page in parsed.pages)
    assert "500 students" in text and "<script>" in text
    assert client.post("/api/cv/review/use", json={"source_hash":review["source_hash"],"confirmed":False}).status_code == 422
    # A profile change invalidates the review, export, saved edits and adoption.
    updated = profile_payload(); updated["preferred_roles"] = ["Design intern"]
    client.put("/api/profile", json=updated)
    assert client.get("/api/state").json()["cv_review"]["stale"] is True
    assert client.get("/api/cv/review/pdf").status_code == 409
    assert client.put("/api/cv/review/document", json={"source_hash":review["source_hash"],"document":edited}).status_code == 409
    assert client.post("/api/cv/review/use", json={"source_hash":review["source_hash"],"confirmed":True}).status_code == 409


def test_cv_rewrite_consent_and_evidence_validation(client: TestClient, monkeypatch) -> None:
    profile = profile_payload(); profile["ai_consent"] = False
    client.put("/api/profile", json=profile)
    source = b"Dana Haddad built data tools for 500 students using Python and SQL."
    client.post("/api/cv", files={"file":("cv.txt",source,"text/plain")})
    app_module.runtime_secrets["openrouter_key"] = "test-only-key"
    assert client.post("/api/cv/review",json={"use_ai":True}).status_code == 409
    profile["ai_consent"] = True
    client.put("/api/profile",json=profile)
    client.post("/api/cv/review",json={"use_ai":False})
    original = client.get("/api/state").json()["cv_review"]
    async def unsupported(*args, **kwargs):
        return {"content":json.dumps({"name":"Dana Haddad","sections":[{"heading":"Experience","body":"Built a rocket.","evidence":"This quote was invented by the model."}]})}
    monkeypatch.setattr(app_module,"ai_chat",unsupported)
    assert client.post("/api/cv/review",json={"use_ai":True}).status_code == 502
    assert client.get("/api/state").json()["cv_review"]["document"] == original["document"]


def test_adopt_cv_preserves_original_and_clear_removes_versions(client: TestClient) -> None:
    client.put("/api/profile",json=profile_payload())
    client.post("/api/cv",files={"file":("cv.txt",b"Dana Haddad built data tools for 500 students using Python and SQL.","text/plain")})
    original_files = set(app_module.UPLOAD_DIR.iterdir())
    review = client.post("/api/cv/review",json={"use_ai":False}).json()["review"]
    response = client.post("/api/cv/review/use",json={"source_hash":review["source_hash"],"confirmed":True})
    assert response.status_code == 200
    assert original_files.issubset(set(app_module.UPLOAD_DIR.iterdir()))
    assert response.json()["profile"]["cv_filename"] == "Masar-CV.pdf"
    client.delete("/api/data")
    assert client.get("/api/state").json()["cv_review"] is None
    assert not list(app_module.UPLOAD_DIR.iterdir())


def test_cv_rewrite_valid_evidence_and_edited_label(client: TestClient, monkeypatch) -> None:
    client.put("/api/profile", json=profile_payload())
    source = "Dana Haddad built data tools for 500 students using Python and SQL."
    client.post("/api/cv", files={"file": ("cv.txt", source.encode(), "text/plain")})
    app_module.runtime_secrets["openrouter_key"] = "test-only-key"
    async def supported(*args, **kwargs):
        return {"content": json.dumps({"name": "Dana Haddad", "sections": [{"heading": "Projects", "body": "- Built data tools for 500 students using Python and SQL.", "evidence": source}]})}
    monkeypatch.setattr(app_module, "ai_chat", supported)
    result = client.post("/api/cv/review", json={"use_ai": True})
    assert result.status_code == 200
    review = result.json()["review"]
    assert review["rewrite_mode"] == "assisted"
    review["document"]["headline"] = "Data science student"
    edited = client.put("/api/cv/review/document", json={"source_hash": review["source_hash"], "document": review["document"]})
    assert edited.json()["review"]["rewrite_mode"] == "edited"
    repeated = client.post("/api/cv/review", json={"use_ai": False}).json()["review"]
    assert repeated["document"]["headline"] == "Data science student"
    assert repeated["rewrite_mode"] == "edited"
    assert client.get("/api/cv/review/pdf").content.startswith(b"%PDF")


def test_profile_extraction_requires_consent_and_does_not_save(client, monkeypatch):
    client.put("/api/profile", json=profile_payload())
    client.post("/api/cv", files={"file": ("cv.txt", b"Dana Haddad has built Python and SQL tools for 500 students.", "text/plain")})
    original = client.get("/api/state").json()["profile"]
    assert client.post("/api/profile/extract", json={}).status_code == 422
    assert client.post("/api/profile/extract", json={"consent": True}).status_code == 409
    async def fake_extraction(*args):
        return {"suggestions": [{"field": "full_name", "value": "Dana Haddad"}], "model": {}, "rejected_fields": []}
    monkeypatch.setattr(app_module, "extract_profile", fake_extraction)
    result = client.post("/api/profile/extract", json={"consent": True})
    assert result.status_code == 200
    assert result.json()["source_hash"] == client.get("/api/profile/extraction-source").json()["source_hash"]
    assert client.get("/api/state").json()["profile"] == original
    async def changing_source(*args):
        with app_module.db() as connection:
            connection.execute("UPDATE profile SET cv_text='New CV text' WHERE id=1")
        return {"suggestions": []}
    monkeypatch.setattr(app_module, "extract_profile", changing_source)
    assert client.post("/api/profile/extract", json={"consent": True}).status_code == 409
