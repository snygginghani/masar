from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from masar_app import app as app_module


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
