from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import platform
import re
import shutil
import smtplib
import socket
import sqlite3
import ssl
import subprocess
import uuid
from datetime import UTC, date, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from docx import Document
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "masar.db"
MAX_CV_BYTES = 10 * 1024 * 1024
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Masar", version="0.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Secrets are intentionally ephemeral. Restarting the server clears them.
runtime_secrets: dict[str, Any] = {
    "ai_provider": "openrouter",
    "openrouter_key": "",
    "openrouter_model": "openai/gpt-5-mini",
    "openai_key": "",
    "openai_model": "gpt-5.4",
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3:8b",
        "search_api_key": "",
        "searxng_url": "",
        "connected": False,
        "models": [],
    },
    "smtp": {},
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS profile (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT NOT NULL,
                cv_filename TEXT,
                cv_path TEXT,
                cv_text TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT NOT NULL,
                workplace TEXT,
                employment_type TEXT,
                summary TEXT,
                requirements TEXT,
                url TEXT,
                source TEXT,
                contact_email TEXT,
                posted_date TEXT,
                closing_date TEXT,
                match_score INTEGER NOT NULL DEFAULT 50,
                match_reasons TEXT,
                gaps TEXT,
                selected INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'discovered',
                demo INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                opportunity_kind TEXT NOT NULL DEFAULT 'opening',
                confidence_score INTEGER NOT NULL DEFAULT 50,
                evidence_urls TEXT NOT NULL DEFAULT '[]',
                contact_name TEXT NOT NULL DEFAULT '',
                contact_role TEXT NOT NULL DEFAULT '',
                official_domain TEXT NOT NULL DEFAULT '',
                search_track TEXT NOT NULL DEFAULT 'open_roles',
                last_verified TEXT,
                discovered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE,
                recipient TEXT,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                method TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            """
        )
        existing_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        migrations = {
            "opportunity_kind": "TEXT NOT NULL DEFAULT 'opening'",
            "confidence_score": "INTEGER NOT NULL DEFAULT 50",
            "evidence_urls": "TEXT NOT NULL DEFAULT '[]'",
            "contact_name": "TEXT NOT NULL DEFAULT ''",
            "contact_role": "TEXT NOT NULL DEFAULT ''",
            "official_domain": "TEXT NOT NULL DEFAULT ''",
            "search_track": "TEXT NOT NULL DEFAULT 'open_roles'",
            "last_verified": "TEXT",
        }
        for column, definition in migrations.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
        connection.execute(
            """UPDATE jobs SET confidence_score=85, last_verified=COALESCE(last_verified, discovered_at)
               WHERE verified=1 AND demo=0 AND confidence_score=50"""
        )
        for row in connection.execute(
            "SELECT id, url FROM jobs WHERE demo=0 AND url IS NOT NULL AND url<>'' AND evidence_urls='[]'"
        ).fetchall():
            connection.execute(
                "UPDATE jobs SET evidence_urls=? WHERE id=?", (json.dumps([row["url"]]), row["id"])
            )


init_db()


class ProfilePayload(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: str
    phone: str = ""
    city: str = ""
    country: str = ""
    university: str = ""
    degree: str = ""
    graduation: str = ""
    linkedin: str = ""
    portfolio: str = ""
    preferred_roles: list[str] = Field(default_factory=list)
    disciplines: list[str] = Field(default_factory=list)
    search_locations: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    internship_type: str = "Any"
    workplace: list[str] = Field(default_factory=lambda: ["On-site", "Hybrid"])
    availability: str = ""
    weekly_hours: str = ""
    work_authorization: str = "Not specified"
    salary_preference: str = "Open to discuss"
    notes: str = ""
    ai_consent: bool = True


class OpenRouterPayload(BaseModel):
    api_key: str = ""
    model: str = "openai/gpt-5-mini"


class AIProviderPayload(BaseModel):
    provider: str = Field(pattern="^(openrouter|openai|ollama)$")
    api_key: str = ""
    model: str
    base_url: str = "http://127.0.0.1:11434"
    ollama_search_api_key: str = ""
    searxng_url: str = ""


class SMTPPayload(BaseModel):
    host: str
    port: int = 587
    username: str
    password: str
    from_email: str
    use_tls: bool = True


class DiscoverPayload(BaseModel):
    keywords: str = ""
    discipline: str = ""
    location: str = ""
    country: str = ""
    max_results: int = Field(default=20, ge=4, le=30)
    include_outreach: bool = True


class SelectionPayload(BaseModel):
    selected: bool


class JobIdsPayload(BaseModel):
    job_ids: list[str]


class ApplicationUpdatePayload(BaseModel):
    subject: str | None = None
    body: str | None = None
    recipient: str | None = None
    approved: bool | None = None


class SendPayload(BaseModel):
    application_ids: list[str]
    confirm_send: bool = False


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    for key in ("requirements", "match_reasons", "gaps", "evidence_urls"):
        if key in item:
            try:
                item[key] = json.loads(item[key] or "[]")
            except json.JSONDecodeError:
                item[key] = []
    for key in ("selected", "demo", "verified", "approved"):
        if key in item:
            item[key] = bool(item[key])
    return item


def current_profile() -> dict[str, Any] | None:
    with db() as connection:
        row = connection.execute("SELECT * FROM profile WHERE id = 1").fetchone()
    if not row:
        return None
    item = dict(row)
    item["data"] = json.loads(item["data"])
    item["cv_ready"] = bool(item.get("cv_text"))
    item.pop("cv_text", None)
    item.pop("cv_path", None)
    return item


def message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content or "")


def extract_json_array(content: Any) -> list[dict[str, Any]]:
    content = message_text(content).strip()
    candidates: list[str] = []
    tagged = re.search(r"<jobs_json>\s*(.*?)\s*</jobs_json>", content, re.S | re.I)
    if tagged:
        candidates.append(tagged.group(1))
    fenced = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", content, re.S | re.I)
    if fenced:
        candidates.append(fenced.group(1))
    if content.startswith(("[", "{")):
        candidates.append(content)
    start, end = content.find("["), content.rfind("]")
    if start >= 0 and end > start:
        candidates.append(content[start : end + 1])
    object_start, object_end = content.find("{"), content.rfind("}")
    if object_start >= 0 and object_end > object_start:
        candidates.append(content[object_start : object_end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, list):
                return [item for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                for key in ("jobs", "opportunities", "results", "companies"):
                    if isinstance(data.get(key), list):
                        return [item for item in data[key] if isinstance(item, dict)]
        except json.JSONDecodeError:
            continue
    raise ValueError("The model did not return a valid jobs array.")


def extract_json_object(content: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.S | re.I)
    candidates = [fenced.group(1)] if fenced else []
    start, end = content.find("{"), content.rfind("}")
    if start >= 0 and end > start:
        candidates.append(content[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise ValueError("The model did not return valid JSON.")


async def openrouter_chat(
    messages: list[dict[str, str]], *, web_search: bool = False, json_mode: bool = False
) -> dict[str, Any]:
    key = runtime_secrets.get("openrouter_key")
    if not key:
        raise HTTPException(409, "Add your OpenRouter key in Settings before running live discovery.")
    payload: dict[str, Any] = {
        "model": runtime_secrets.get("openrouter_model") or "openai/gpt-5-mini",
        "messages": messages,
        "temperature": 0.15,
        "max_tokens": 7000 if web_search else 2500,
    }
    if web_search:
        payload["tools"] = [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": "auto",
                    "max_results": 12,
                    "max_total_results": 24,
                    "search_context_size": "medium",
                },
            }
        ]
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8765",
        "X-OpenRouter-Title": "Masar Internship Finder",
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        raise HTTPException(exc.response.status_code, f"OpenRouter request failed: {detail}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Could not reach OpenRouter: {exc}") from exc
    if not data.get("choices"):
        raise HTTPException(502, "OpenRouter returned no result.")
    return data["choices"][0]["message"]


async def openai_chat(
    messages: list[dict[str, str]], *, web_search: bool = False, json_mode: bool = False
) -> dict[str, Any]:
    key = runtime_secrets.get("openai_key")
    if not key:
        raise HTTPException(409, "Add your OpenAI API key in Settings before using this provider.")
    payload: dict[str, Any] = {
        "model": runtime_secrets.get("openai_model") or "gpt-5.4",
        "input": messages,
        "store": False,
        "max_output_tokens": 7000 if web_search else 2500,
    }
    if web_search:
        payload["tools"] = [{"type": "web_search"}]
        payload["include"] = ["web_search_call.action.sources"]
    if json_mode:
        payload["text"] = {"format": {"type": "json_object"}}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                json=payload,
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            exc.response.status_code, f"OpenAI request failed: {exc.response.text[:500]}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Could not reach OpenAI: {exc}") from exc

    text_parts: list[str] = []
    annotations: list[dict[str, Any]] = []
    for output in data.get("output") or []:
        if output.get("type") != "message":
            continue
        for content in output.get("content") or []:
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                text_parts.append(content["text"])
            annotations.extend(item for item in content.get("annotations") or [] if isinstance(item, dict))
    content = data.get("output_text") or "\n".join(text_parts)
    if not content:
        raise HTTPException(502, "OpenAI returned no text result.")
    return {"content": content, "annotations": annotations}


async def ollama_search_context(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    ollama = runtime_secrets.get("ollama") or {}
    combined = "\n".join(message.get("content", "") for message in messages)
    match = re.search(r"<search_queries>\s*(\[.*?\])\s*</search_queries>", combined, re.S)
    try:
        queries = json.loads(match.group(1)) if match else []
    except json.JSONDecodeError:
        queries = []
    queries = [str(query).strip()[:300] for query in queries if str(query).strip()][:3]
    if not queries:
        raise HTTPException(422, "The local search plan did not contain usable queries.")

    results: list[dict[str, str]] = []
    search_key = ollama.get("search_api_key") or ""
    searxng_url = normalize_url(ollama.get("searxng_url"))
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for query in queries:
            if search_key:
                response = await client.post(
                    "https://ollama.com/api/web_search",
                    json={"query": query, "max_results": 8},
                    headers={"Authorization": f"Bearer {search_key}"},
                )
                response.raise_for_status()
                raw_results = response.json().get("results") or []
            elif searxng_url:
                response = await client.get(
                    f"{searxng_url.rstrip('/')}/search",
                    params={"q": query, "format": "json", "categories": "general"},
                )
                response.raise_for_status()
                raw_results = response.json().get("results") or []
            else:
                raise HTTPException(
                    409,
                    "Local Ollama needs a search source for live discovery. Add an Ollama Web Search key "
                    "or a local SearXNG URL in Settings. CV matching and drafting remain local.",
                )
            for item in raw_results:
                url = normalize_url(item.get("url"))
                if not url:
                    continue
                record = {
                    "title": str(item.get("title") or "")[:300],
                    "url": url,
                    "content": str(item.get("content") or item.get("snippet") or "")[:3000],
                }
                if not any(existing["url"] == url for existing in results):
                    results.append(record)
    context = "\n\n".join(
        f"SOURCE: {item['title']}\nURL: {item['url']}\nEXCERPT: {item['content']}" for item in results[:24]
    )
    annotations = [{"url_citation": item} for item in results[:24]]
    return context, annotations


async def ollama_chat(
    messages: list[dict[str, str]], *, web_search: bool = False, json_mode: bool = False
) -> dict[str, Any]:
    ollama = runtime_secrets.get("ollama") or {}
    if not ollama.get("connected"):
        raise HTTPException(409, "Connect Ollama in Settings before using the local provider.")
    request_messages = [dict(message) for message in messages]
    annotations: list[dict[str, Any]] = []
    if web_search:
        try:
            context, annotations = await ollama_search_context(request_messages)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                exc.response.status_code, f"Ollama search failed: {exc.response.text[:400]}"
            ) from exc
        request_messages[-1]["content"] += (
            "\n\nUse only the following search results as web evidence. Do not rely on model memory for current facts.\n"
            + context
        )
    payload: dict[str, Any] = {
        "model": ollama.get("model") or "qwen3:4b",
        "messages": request_messages,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 32768},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f"{ollama['base_url'].rstrip('/')}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            exc.response.status_code, f"Ollama request failed: {exc.response.text[:400]}"
        ) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"Could not reach Ollama: {exc}") from exc
    content = ((data.get("message") or {}).get("content") or "").strip()
    if not content:
        raise HTTPException(502, "Ollama returned no text result.")
    return {"content": content, "annotations": annotations}


async def ai_chat(
    messages: list[dict[str, str]], *, web_search: bool = False, json_mode: bool = False
) -> dict[str, Any]:
    provider = runtime_secrets.get("ai_provider") or "openrouter"
    if provider == "openai":
        return await openai_chat(messages, web_search=web_search, json_mode=json_mode)
    if provider == "ollama":
        return await ollama_chat(messages, web_search=web_search, json_mode=json_mode)
    return await openrouter_chat(messages, web_search=web_search, json_mode=json_mode)


def normalize_url(value: Any) -> str:
    value = str(value or "").strip()
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def normalize_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:160] for item in value if str(item).strip()][:limit]


def provider_is_connected(provider: str | None = None) -> bool:
    provider = provider or str(runtime_secrets.get("ai_provider") or "openrouter")
    if provider == "openai":
        return bool(runtime_secrets.get("openai_key"))
    if provider == "ollama":
        return bool((runtime_secrets.get("ollama") or {}).get("connected"))
    return bool(runtime_secrets.get("openrouter_key"))


def normalize_service_url(value: str, *, field_name: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, f"Enter a valid {field_name} URL without embedded credentials.")
    return value


async def verify_url(url: str) -> bool:
    if not url:
        return False
    hostname = urlparse(url).hostname
    if not hostname or hostname.lower() == "localhost":
        return False
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
        resolved = {item[4][0] for item in addresses}
        if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
            return False
        async with httpx.AsyncClient(
            timeout=7,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 MasarJobVerifier/0.1"},
        ) as client:
            async with client.stream("GET", url) as response:
                return response.status_code < 400
    except (httpx.HTTPError, OSError, ValueError):
        return False


def public_hostname(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return hostname if hostname else ""


async def inspect_source(url: str, contact_email: str = "") -> dict[str, Any]:
    """Reach a public source and verify a claimed email against its rendered HTML."""
    if not url:
        return {"reachable": False, "email_present": False}
    hostname = urlparse(url).hostname
    if not hostname or hostname.lower() == "localhost":
        return {"reachable": False, "email_present": False}
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
        resolved = {item[4][0] for item in addresses}
        if not resolved or any(not ipaddress.ip_address(address).is_global for address in resolved):
            return {"reachable": False, "email_present": False}
        async with httpx.AsyncClient(
            timeout=9,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 MasarOpportunityVerifier/0.2"},
        ) as client:
            response = await client.get(url)
            reachable = response.status_code < 400
            page_text = response.text[:750000].lower() if reachable else ""
            return {
                "reachable": reachable,
                "email_present": bool(contact_email and contact_email.lower() in page_text),
            }
    except (httpx.HTTPError, OSError, ValueError):
        return {"reachable": False, "email_present": False}


def citations_from_message(message: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for annotation in message.get("annotations") or []:
        citation = annotation.get("url_citation") if isinstance(annotation, dict) else None
        if isinstance(annotation, dict) and annotation.get("type") == "url_citation":
            citation = annotation
        if not isinstance(citation, dict):
            continue
        url = normalize_url(citation.get("url"))
        if url:
            citations.append(
                {
                    "title": str(citation.get("title") or "")[:300],
                    "url": url,
                    "content": str(citation.get("content") or "")[:3000],
                }
            )
    return citations


async def research_opportunity_track(
    *,
    track: str,
    profile: dict[str, Any],
    cv_text: str,
    keywords: str,
    discipline: str,
    location: str,
    country: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    today = date.today().isoformat()
    target_area = ", ".join(part for part in (location, country) if part)
    field = discipline or keywords or "the candidate's target field"
    search_queries = [
        f'{keywords or field} internship OR trainee OR "entry level" {target_area}',
        f'{field} companies careers contact {target_area}',
        f'{field} graduate program OR student opportunity {target_area}',
    ]
    if track == "open_roles":
        objective = f"""
Find CURRENT, OPEN internships, traineeships, graduate programs, or genuinely entry-level roles related
to {keywords or field}. Search exact role phrases, close synonyms, skills found in the CV, junior,
assistant, apprentice, placement, graduate, and university-student variants. Cover employer career pages,
reputable job boards, university career pages, professional associations, startups, consultancies, public
institutions, and established employers relevant to this field in {target_area}. Prefer direct employer
pages and direct job URLs.

For every result set opportunity_kind to "opening" and search_track to "open_roles". Exclude senior,
manager, expired, closed, and roles requiring more than two years of experience. A posted role needs a
direct source URL and evidence that it is open as of today. Never use a search-results URL when a direct
listing is available.
"""
    else:
        coverage = (
            f"Focus on specialist organizations whose main work is clearly connected to {field}."
            if track == "specialist_organizations"
            else f"Focus on established employers that have real teams, projects, or programs connected to {field}."
        )
        objective = f"""
Find organizations with a REAL office, team, program, or hiring presence in {target_area} that do meaningful
work related to {field}—even if they are not advertising an internship. {coverage}

For every result set opportunity_kind to "outreach", title to "Proactive Internship Inquiry — {field}",
and search_track to "{track}". Use the organization's official website, careers page, or a
public company/recruiting page as url. Only include a contact email, contact name, or HR/recruiting role
when it is explicitly published in a cited source. NEVER guess email patterns, infer private addresses,
or invent an HR person. It is valid and preferable to leave contact fields empty and use an official
careers/contact page. Exclude staffing lists, directories with no primary source, and companies whose
relevance to {field} or presence in {target_area} cannot be evidenced.
"""
    prompt = f"""
<search_queries>{json.dumps(search_queries, ensure_ascii=False)}</search_queries>

Today is {today}. You are researching opportunities for one candidate in {target_area}.
{objective}

Return at most {limit} high-quality, distinct results. Accuracy is more important than count.
Every result must have at least one reachable-looking evidence URL. Never invent facts, openings,
contacts, dates, requirements, or URLs. Score CV fit only from the supplied profile and CV. Put uncertainty,
student/graduate conflicts, and missing requirements in gaps. confidence_score measures source confidence,
not candidate fit: 90+ requires a direct official source; 75-89 may use a direct reputable job/company page;
below 75 should normally be excluded.

Candidate profile:
{json.dumps(profile, ensure_ascii=False)}

Candidate CV:
{cv_text[:14000]}

Return valid JSON with one key, "opportunities", containing objects with exactly these keys:
opportunity_kind, search_track, title, company, location, workplace, employment_type, summary,
requirements (array), url, source, official_domain, contact_email, contact_name, contact_role,
posted_date, closing_date, match_score (integer 0-100), confidence_score (integer 0-100),
match_reasons (array), gaps (array), evidence_urls (array).
"""
    message = await ai_chat(
        [
            {
                "role": "system",
                "content": "You are a skeptical employment researcher. Search broadly, cite primary sources, and never fabricate.",
            },
            {"role": "user", "content": prompt},
        ],
        web_search=True,
        json_mode=True,
    )
    citations = citations_from_message(message)
    try:
        return extract_json_array(message.get("content")), len(citations)
    except ValueError:
        repair_prompt = f"""
Convert the research response and citations below into valid JSON with one key named "opportunities".
Do not add facts or results. Preserve only results that meet the requested track. Every result needs a
non-empty direct URL. Use empty strings or arrays for missing fields. Required fields:
opportunity_kind, search_track, title, company, location, workplace, employment_type, summary,
requirements, url, source, official_domain, contact_email, contact_name, contact_role, posted_date,
closing_date, match_score, confidence_score, match_reasons, gaps, evidence_urls.

Track: {track}
Research response: {message_text(message.get("content"))[:22000]}
Citations: {json.dumps(citations, ensure_ascii=False)[:18000]}
"""
        repaired = await ai_chat(
            [
                {"role": "system", "content": "Extract only supported records. Output JSON only."},
                {"role": "user", "content": repair_prompt},
            ],
            json_mode=True,
        )
        return extract_json_array(repaired.get("content")), len(citations)


def profile_context() -> tuple[dict[str, Any], str]:
    with db() as connection:
        row = connection.execute("SELECT data, cv_text FROM profile WHERE id = 1").fetchone()
    if not row:
        raise HTTPException(409, "Complete your profile before discovering jobs.")
    return json.loads(row["data"]), (row["cv_text"] or "")[:14000]


def total_memory_bytes() -> int:
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_ulong),
                ("memory_load", ctypes.c_ulong),
                ("total_physical", ctypes.c_ulonglong),
                ("available_physical", ctypes.c_ulonglong),
                ("total_page_file", ctypes.c_ulonglong),
                ("available_page_file", ctypes.c_ulonglong),
                ("total_virtual", ctypes.c_ulonglong),
                ("available_virtual", ctypes.c_ulonglong),
                ("available_extended_virtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.total_physical)
    if platform.system() == "Linux":
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3, check=True
            )
            return int(result.stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return 0


def gpu_inventory() -> list[dict[str, Any]]:
    command = shutil.which("nvidia-smi")
    if not command:
        return []
    try:
        result = subprocess.run(
            [
                command,
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    gpus: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            continue
        try:
            gpus.append({"name": parts[0], "vram_mb": int(parts[1]), "free_vram_mb": int(parts[2])})
        except ValueError:
            continue
    return gpus


def system_capabilities() -> dict[str, Any]:
    memory_gb = round(total_memory_bytes() / (1024**3), 1)
    gpus = gpu_inventory()
    best_vram = max((gpu["vram_mb"] for gpu in gpus), default=0)
    if best_vram >= 15000 or (not gpus and memory_gb >= 48):
        model, size, tier = "qwen3:14b", "9.3 GB", "quality"
    elif best_vram >= 7000 or memory_gb >= 24:
        model, size, tier = "qwen3:8b", "5.2 GB", "balanced"
    elif best_vram >= 3500 or memory_gb >= 12:
        model, size, tier = "qwen3:4b", "2.5 GB", "efficient"
    elif memory_gb >= 8:
        model, size, tier = "qwen3:1.7b", "1.4 GB", "lightweight"
    else:
        model, size, tier = "qwen3:0.6b", "523 MB", "minimum"
    return {
        "os": platform.system(),
        "architecture": platform.machine(),
        "cpu_threads": os.cpu_count() or 1,
        "memory_gb": memory_gb,
        "gpus": gpus,
        "ollama_installed": bool(shutil.which("ollama")),
        "recommendation": {
            "model": model,
            "download_size": size,
            "tier": tier,
            "reason": (
                f"Chosen for {memory_gb:g} GB system RAM"
                + (f" and {round(best_vram / 1024, 1):g} GB VRAM" if best_vram else " with CPU inference")
                + "."
            ),
        },
    }


@app.get("/api/system/capabilities")
async def capabilities() -> dict[str, Any]:
    return system_capabilities()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": "Masar"}


@app.get("/api/state")
async def state() -> dict[str, Any]:
    with db() as connection:
        jobs = [
            row_dict(row)
            for row in connection.execute(
                "SELECT * FROM jobs ORDER BY selected DESC, match_score DESC, confidence_score DESC, discovered_at DESC"
            )
        ]
        applications = [
            row_dict(row)
            for row in connection.execute(
                """SELECT applications.*, jobs.title AS job_title, jobs.company,
                          jobs.url AS job_url, jobs.demo, jobs.opportunity_kind
                   FROM applications JOIN jobs ON jobs.id = applications.job_id
                   ORDER BY applications.created_at DESC"""
            )
        ]
    smtp = runtime_secrets.get("smtp") or {}
    provider = runtime_secrets.get("ai_provider") or "openrouter"
    ollama = runtime_secrets.get("ollama") or {}
    provider_models = {
        "openrouter": runtime_secrets.get("openrouter_model"),
        "openai": runtime_secrets.get("openai_model"),
        "ollama": ollama.get("model"),
    }
    provider_connected = {
        "openrouter": bool(runtime_secrets.get("openrouter_key")),
        "openai": bool(runtime_secrets.get("openai_key")),
        "ollama": bool(ollama.get("connected")),
    }
    return {
        "profile": current_profile(),
        "jobs": jobs,
        "applications": applications,
        "integrations": {
            "ai_provider": provider,
            "ai_connected": provider_connected.get(provider, False),
            "ai_model": provider_models.get(provider),
            "providers": {
                "openrouter": {
                    "connected": provider_connected["openrouter"],
                    "model": provider_models["openrouter"],
                },
                "openai": {
                    "connected": provider_connected["openai"],
                    "model": provider_models["openai"],
                },
                "ollama": {
                    "connected": provider_connected["ollama"],
                    "model": provider_models["ollama"],
                    "base_url": ollama.get("base_url"),
                    "models": ollama.get("models") or [],
                    "search_ready": bool(ollama.get("search_api_key") or ollama.get("searxng_url")),
                },
            },
            "openrouter_connected": bool(runtime_secrets.get("openrouter_key")),
            "model": provider_models.get(provider),
            "smtp_connected": bool(smtp.get("password")),
            "smtp_from": smtp.get("from_email", ""),
        },
    }


@app.put("/api/profile")
async def save_profile(payload: ProfilePayload) -> dict[str, Any]:
    if not EMAIL_RE.match(payload.email):
        raise HTTPException(422, "Enter a valid email address.")
    with db() as connection:
        existing = connection.execute("SELECT cv_filename, cv_path, cv_text FROM profile WHERE id=1").fetchone()
        connection.execute(
            """INSERT OR REPLACE INTO profile
               (id, data, cv_filename, cv_path, cv_text, updated_at)
               VALUES (1, ?, ?, ?, ?, ?)""",
            (
                payload.model_dump_json(),
                existing["cv_filename"] if existing else None,
                existing["cv_path"] if existing else None,
                existing["cv_text"] if existing else None,
                now_iso(),
            ),
        )
    return {"ok": True, "profile": current_profile()}


def read_cv(path: Path, suffix: str) -> str:
    if suffix == ".pdf":
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    raise HTTPException(415, "Use a PDF, DOCX, TXT, or MD file.")


@app.post("/api/cv")
async def upload_cv(file: UploadFile = File(...)) -> dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md"}:
        raise HTTPException(415, "Use a PDF, DOCX, TXT, or MD file.")
    content = await file.read(MAX_CV_BYTES + 1)
    if len(content) > MAX_CV_BYTES:
        raise HTTPException(413, "CV must be 10 MB or smaller.")
    safe_name = f"cv-{uuid.uuid4().hex}{suffix}"
    path = UPLOAD_DIR / safe_name
    path.write_bytes(content)
    try:
        text = read_cv(path, suffix).strip()
    except Exception as exc:
        path.unlink(missing_ok=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(422, f"Could not read this CV: {exc}") from exc
    if len(text) < 40:
        path.unlink(missing_ok=True)
        raise HTTPException(422, "The CV has too little readable text. Try a text-based PDF or DOCX.")
    with db() as connection:
        row = connection.execute("SELECT data, cv_path FROM profile WHERE id=1").fetchone()
        if not row:
            path.unlink(missing_ok=True)
            raise HTTPException(409, "Save your basic profile before uploading a CV.")
        old_path = Path(row["cv_path"]) if row["cv_path"] else None
        connection.execute(
            "UPDATE profile SET cv_filename=?, cv_path=?, cv_text=?, updated_at=? WHERE id=1",
            (file.filename, str(path), text[:80000], now_iso()),
        )
    if old_path and old_path.is_file() and old_path.parent.resolve() == UPLOAD_DIR.resolve():
        old_path.unlink(missing_ok=True)
    return {"ok": True, "filename": file.filename, "characters": len(text), "profile": current_profile()}


@app.post("/api/integrations/openrouter")
async def set_openrouter(payload: OpenRouterPayload) -> dict[str, Any]:
    key = payload.api_key.strip()
    if key and not key.startswith("sk-or-"):
        raise HTTPException(422, "This does not look like an OpenRouter key (expected sk-or-…).")
    # An empty key keeps an already-connected session, allowing model changes
    # without asking the user to paste their secret again.
    if key or not runtime_secrets.get("openrouter_key"):
        runtime_secrets["openrouter_key"] = key
    runtime_secrets["openrouter_model"] = payload.model.strip() or "openai/gpt-5-mini"
    runtime_secrets["ai_provider"] = "openrouter"
    return {
        "ok": True,
        "connected": bool(runtime_secrets.get("openrouter_key")),
        "provider": "openrouter",
        "model": runtime_secrets["openrouter_model"],
    }


@app.post("/api/integrations/ai")
async def set_ai_provider(payload: AIProviderPayload) -> dict[str, Any]:
    provider = payload.provider
    model = payload.model.strip()
    if not model:
        raise HTTPException(422, "Enter a model name.")

    if provider == "openrouter":
        key = payload.api_key.strip() or str(runtime_secrets.get("openrouter_key") or "")
        if not key.startswith("sk-or-"):
            raise HTTPException(422, "Enter a valid OpenRouter API key (it starts with sk-or-).")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {key}"}
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(422, "OpenRouter rejected this API key.") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Could not reach OpenRouter: {exc}") from exc
        runtime_secrets["openrouter_key"] = key
        runtime_secrets["openrouter_model"] = model
        result = {"connected": True, "model": model}
    elif provider == "openai":
        key = payload.api_key.strip() or str(runtime_secrets.get("openai_key") or "")
        if not key.startswith("sk-"):
            raise HTTPException(422, "Enter a valid OpenAI API key (it starts with sk-).")
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {key}"}
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(422, "OpenAI rejected this API key.") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"Could not reach OpenAI: {exc}") from exc
        runtime_secrets["openai_key"] = key
        runtime_secrets["openai_model"] = model
        result = {"connected": True, "model": model}
    else:
        base_url = normalize_service_url(payload.base_url, field_name="Ollama server")
        searxng_url = (
            normalize_service_url(payload.searxng_url, field_name="SearXNG server")
            if payload.searxng_url.strip()
            else ""
        )
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(f"{base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "Ollama responded, but its model list failed.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                502, "Could not connect to Ollama. Start it first, then try this connection again."
            ) from exc
        models = sorted(
            {
                str(item.get("model") or item.get("name") or "").strip()
                for item in data.get("models") or []
                if str(item.get("model") or item.get("name") or "").strip()
            }
        )
        old = runtime_secrets.get("ollama") or {}
        runtime_secrets["ollama"] = {
            "base_url": base_url,
            "model": model,
            "search_api_key": payload.ollama_search_api_key.strip() or old.get("search_api_key", ""),
            "searxng_url": searxng_url,
            "connected": True,
            "models": models,
        }
        result = {
            "connected": True,
            "model": model,
            "models": models,
            "model_ready": model in models,
            "search_ready": bool(
                runtime_secrets["ollama"]["search_api_key"]
                or runtime_secrets["ollama"]["searxng_url"]
            ),
        }
    runtime_secrets["ai_provider"] = provider
    return {"ok": True, "provider": provider, **result}


@app.post("/api/integrations/smtp")
async def set_smtp(payload: SMTPPayload) -> dict[str, Any]:
    if not EMAIL_RE.match(payload.from_email):
        raise HTTPException(422, "Enter a valid sender email.")
    if not EMAIL_RE.match(payload.username):
        raise HTTPException(422, "Use your full email address as the SMTP username.")
    if not 1 <= payload.port <= 65535:
        raise HTTPException(422, "Enter a valid SMTP port.")
    settings = payload.model_dump()
    if payload.host.strip().lower() == "smtp.gmail.com":
        if payload.username.strip().lower() != payload.from_email.strip().lower():
            raise HTTPException(422, "For Gmail, the username and From email must match.")
        # Google displays app passwords in four groups; SMTP expects no spaces.
        settings["password"] = re.sub(r"\s+", "", payload.password)
    try:
        await asyncio.to_thread(verify_smtp_credentials, settings)
    except smtplib.SMTPAuthenticationError as exc:
        raise HTTPException(
            422,
            "Gmail rejected the login. Use a Google App Password, not your normal Gmail password.",
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise HTTPException(502, f"Could not verify the email connection: {str(exc)[:220]}") from exc
    runtime_secrets["smtp"] = settings
    return {"ok": True, "connected": bool(payload.password), "from_email": payload.from_email}


def verify_smtp_credentials(settings: dict[str, Any]) -> None:
    """Authenticate and quit without sending a message."""
    context = ssl.create_default_context()
    with smtplib.SMTP(settings["host"], int(settings["port"]), timeout=30) as server:
        server.ehlo()
        if settings.get("use_tls", True):
            server.starttls(context=context)
            server.ehlo()
        server.login(settings["username"], settings["password"])


@app.post("/api/jobs/demo")
async def load_demo_jobs() -> dict[str, Any]:
    demos = [
        {
            "title": "Product Design Intern",
            "company": "Northstar Studio",
            "location": "Sample City",
            "workplace": "Hybrid",
            "employment_type": "Internship",
            "summary": "Support user research, interface concepts, and prototype testing with a product team.",
            "requirements": ["Portfolio", "Figma", "User research", "Clear communication"],
            "match_score": 91,
            "match_reasons": ["Relevant course projects", "Portfolio evidence", "Local availability"],
            "gaps": ["No shipped product example"],
            "posted_date": "Demo data",
        },
        {
            "title": "Environmental Lab Assistant",
            "company": "Riverbend Research",
            "location": "Sample City",
            "workplace": "On-site",
            "employment_type": "Internship",
            "summary": "Support sample preparation, field records, and quality-control documentation.",
            "requirements": ["Lab safety", "Record keeping", "Excel", "Analytical writing"],
            "match_score": 84,
            "match_reasons": ["Relevant coursework", "Strong analytical profile", "Local availability"],
            "gaps": ["Specific lab methods are not shown on the CV"],
            "posted_date": "Demo data",
        },
        {
            "title": "Finance Operations Trainee",
            "company": "Cedar & Co.",
            "location": "Remote",
            "workplace": "On-site",
            "employment_type": "Part-time internship",
            "summary": "Reconcile operating reports, document controls, and support monthly analysis.",
            "requirements": ["Accounting basics", "Spreadsheets", "Attention to detail", "Communication"],
            "match_score": 76,
            "match_reasons": ["Quantitative foundation", "Reporting experience", "Remote availability"],
            "gaps": ["No accounting internship yet"],
            "posted_date": "Demo data",
        },
    ]
    with db() as connection:
        connection.execute("DELETE FROM jobs WHERE demo=1")
        for item in demos:
            job_id = f"demo-{uuid.uuid4().hex[:10]}"
            connection.execute(
                """INSERT INTO jobs
                (id,title,company,location,workplace,employment_type,summary,requirements,url,source,
                 posted_date,match_score,match_reasons,gaps,demo,verified,discovered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id,
                    item["title"],
                    item["company"],
                    item["location"],
                    item["workplace"],
                    item["employment_type"],
                    item["summary"],
                    json.dumps(item["requirements"]),
                    "",
                    "Masar demo",
                    item["posted_date"],
                    item["match_score"],
                    json.dumps(item["match_reasons"]),
                    json.dumps(item["gaps"]),
                    1,
                    0,
                    now_iso(),
                ),
            )
    return {"ok": True, "count": len(demos)}


def prepare_opportunity(
    item: dict[str, Any], track: str, location_target: str = "", country_target: str = ""
) -> dict[str, Any] | None:
    kind = "opening" if track == "open_roles" else "outreach"
    company = str(item.get("company") or "").strip()[:160]
    title = str(item.get("title") or "").strip()[:160]
    if kind == "outreach":
        title = "Proactive Internship Inquiry"
    location = str(item.get("location") or "").strip()[:160]
    url = normalize_url(item.get("url"))
    if not company or not title or not url:
        return None
    target_terms: list[str] = []
    for raw_target in (location_target, country_target):
        for term in (raw_target, *raw_target.split(",")):
            term = term.strip().casefold()
            if len(term) >= 2 and term not in target_terms:
                target_terms.append(term)
    location_folded = location.casefold()
    is_remote = "remote" in location_folded or "remote" in " ".join(target_terms)
    if target_terms and location and not is_remote and not any(term in location_folded for term in target_terms):
        return None
    if kind == "opening" and re.search(r"\b(senior|manager|director|lead|head|principal)\b", title, re.I):
        return None
    if kind == "opening" and re.search(r"/(jobs/)?search(?:[/?#]|$)", urlparse(url).path, re.I):
        return None

    evidence_urls = [url]
    for evidence_url in normalize_list(item.get("evidence_urls"), 6):
        normalized = normalize_url(evidence_url)
        if normalized and normalized not in evidence_urls:
            evidence_urls.append(normalized)
    email = str(item.get("contact_email") or "").strip().lower()
    if email and not EMAIL_RE.match(email):
        email = ""
    try:
        match_score = int(item.get("match_score") or 50)
    except (TypeError, ValueError):
        match_score = 50
    try:
        confidence_score = int(item.get("confidence_score") or 65)
    except (TypeError, ValueError):
        confidence_score = 65
    if confidence_score < 60:
        return None

    official_domain = str(item.get("official_domain") or "").strip().lower()[:160]
    if normalize_url(official_domain):
        official_domain = public_hostname(official_domain)
    official_domain = re.sub(r"[^a-z0-9.-]", "", official_domain) or public_hostname(url)
    return {
        "id": uuid.uuid4().hex,
        "opportunity_kind": kind,
        "search_track": track,
        "title": title,
        "company": company,
        "location": location or ", ".join(part for part in (location_target, country_target) if part),
        "workplace": str(item.get("workplace") or "Not stated")[:60],
        "employment_type": str(
            item.get("employment_type") or ("Proactive outreach" if kind == "outreach" else "Internship")
        )[:80],
        "summary": str(item.get("summary") or "")[:1200],
        "requirements": normalize_list(item.get("requirements"), 10),
        "url": url,
        "source": str(item.get("source") or public_hostname(url))[:120],
        "official_domain": official_domain,
        "contact_email": email,
        "contact_name": str(item.get("contact_name") or "")[:120],
        "contact_role": str(item.get("contact_role") or "")[:120],
        "posted_date": str(
            item.get("posted_date") or ("No posted role — proactive outreach" if kind == "outreach" else "Not stated")
        )[:80],
        "closing_date": str(item.get("closing_date") or "Not stated")[:60],
        "match_score": max(0, min(100, match_score)),
        "confidence_score": max(0, min(100, confidence_score)),
        "match_reasons": normalize_list(item.get("match_reasons"), 5),
        "gaps": normalize_list(item.get("gaps"), 5),
        "evidence_urls": evidence_urls,
    }


@app.post("/api/jobs/discover")
async def discover_jobs(payload: DiscoverPayload) -> dict[str, Any]:
    profile, cv_text = profile_context()
    if not cv_text:
        raise HTTPException(409, "Upload your CV before running live discovery.")
    if not profile.get("ai_consent"):
        raise HTTPException(409, "Enable CV analysis consent in your profile before using an AI provider.")

    locations = normalize_list(profile.get("search_locations"), 8)
    location = payload.location.strip() or (locations[0] if locations else str(profile.get("city") or ""))
    country = payload.country.strip() or str(profile.get("country") or "")
    discipline = payload.discipline.strip() or ", ".join(
        normalize_list(profile.get("disciplines"), 5)
    ) or str(profile.get("degree") or "")
    keywords = payload.keywords.strip() or ", ".join(
        normalize_list(profile.get("preferred_roles"), 8) or normalize_list(profile.get("skills"), 8)
    )
    if not location and not country:
        raise HTTPException(422, "Enter at least a city, region, or country to search.")
    if not keywords and not discipline:
        raise HTTPException(422, "Enter target roles, keywords, a major, or a discipline.")

    tracks = ["open_roles"]
    if payload.include_outreach:
        tracks.extend(["specialist_organizations", "major_employers"])
    per_track = max(4, (payload.max_results + len(tracks) - 1) // len(tracks))
    research = await asyncio.gather(
        *(
            research_opportunity_track(
                track=track,
                profile=profile,
                cv_text=cv_text,
                keywords=keywords,
                discipline=discipline,
                location=location,
                country=country,
                limit=per_track,
            )
            for track in tracks
        ),
        return_exceptions=True,
    )
    raw_items: list[tuple[dict[str, Any], str]] = []
    sources_scanned = 0
    failures: list[str] = []
    for track, result in zip(tracks, research, strict=True):
        if isinstance(result, Exception):
            failures.append(f"{track}: {str(result)[:180]}")
            continue
        records, citations_count = result
        sources_scanned += citations_count
        raw_items.extend((record, track) for record in records)
    if not raw_items and failures:
        raise HTTPException(502, "Opportunity research failed: " + " · ".join(failures))

    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item, track in raw_items:
        item = prepare_opportunity(raw_item, track, location, country)
        if not item:
            continue
        key = re.sub(r"\W+", "", f"{item['opportunity_kind']}{item['title']}{item['company']}".lower())
        if key in seen:
            continue
        seen.add(key)
        prepared.append(item)

    opening_companies = {
        re.sub(r"\W+", "", item["company"].lower())
        for item in prepared
        if item["opportunity_kind"] == "opening"
    }
    prepared = [
        item
        for item in prepared
        if item["opportunity_kind"] == "opening"
        or re.sub(r"\W+", "", item["company"].lower()) not in opening_companies
    ]
    prepared.sort(
        key=lambda item: (item["confidence_score"], item["match_score"], item["opportunity_kind"] == "opening"),
        reverse=True,
    )
    prepared = prepared[: payload.max_results]

    checks = await asyncio.gather(
        *(inspect_source(item["url"], item["contact_email"]) for item in prepared)
    )
    verified_items: list[dict[str, Any]] = []
    for item, check in zip(prepared, checks, strict=True):
        if not check["reachable"]:
            continue
        item["verified"] = True
        item["last_verified"] = now_iso()
        if item["contact_email"] and not check["email_present"]:
            item["contact_email"] = ""
            item["contact_name"] = ""
            item["contact_role"] = ""
            item["gaps"] = normalize_list(
                item["gaps"] + ["A published contact could not be confirmed on the saved source page."], 5
            )
            item["confidence_score"] = min(item["confidence_score"], 82)
        verified_items.append(item)
    prepared = verified_items

    with db() as connection:
        for item in prepared:
            duplicate = connection.execute(
                """SELECT id FROM jobs WHERE lower(title)=lower(?) AND lower(company)=lower(?)
                   AND opportunity_kind=? AND demo=0""",
                (item["title"], item["company"], item["opportunity_kind"]),
            ).fetchone()
            values = (
                item["location"], item["workplace"], item["employment_type"], item["summary"],
                json.dumps(item["requirements"]), item["url"], item["source"], item["contact_email"],
                item["posted_date"], item["closing_date"], item["match_score"],
                json.dumps(item["match_reasons"]), json.dumps(item["gaps"]), int(item["verified"]),
                item["opportunity_kind"], item["confidence_score"], json.dumps(item["evidence_urls"]),
                item["contact_name"], item["contact_role"], item["official_domain"], item["search_track"],
                item["last_verified"], now_iso(),
            )
            if duplicate:
                connection.execute(
                    """UPDATE jobs SET location=?, workplace=?, employment_type=?, summary=?, requirements=?,
                       url=?, source=?, contact_email=?, posted_date=?, closing_date=?, match_score=?,
                       match_reasons=?, gaps=?, verified=?, opportunity_kind=?, confidence_score=?,
                       evidence_urls=?, contact_name=?, contact_role=?, official_domain=?, search_track=?,
                       last_verified=?, discovered_at=? WHERE id=?""",
                    values + (duplicate["id"],),
                )
            else:
                connection.execute(
                    """INSERT INTO jobs
                    (id,title,company,location,workplace,employment_type,summary,requirements,url,source,
                     contact_email,posted_date,closing_date,match_score,match_reasons,gaps,demo,verified,
                     opportunity_kind,confidence_score,evidence_urls,contact_name,contact_role,official_domain,
                     search_track,last_verified,discovered_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?,?,?)""",
                    (item["id"], item["title"], item["company"]) + values,
                )

    openings = sum(item["opportunity_kind"] == "opening" for item in prepared)
    outreach = sum(item["opportunity_kind"] == "outreach" for item in prepared)
    return {
        "ok": True,
        "count": len(prepared),
        "openings": openings,
        "outreach": outreach,
        "verified": len(prepared),
        "email_ready": sum(bool(item["contact_email"]) for item in prepared),
        "sources_scanned": sources_scanned,
        "tracks_completed": len(tracks) - len(failures),
        "track_warnings": failures,
        "note": "Only reachable source pages were saved. Public contacts are kept only when present on the saved page.",
    }


@app.patch("/api/jobs/{job_id}/selection")
async def select_job(job_id: str, payload: SelectionPayload) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT demo FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job not found.")
        if row["demo"] and payload.selected:
            raise HTTPException(409, "Demo jobs cannot be selected for application.")
        connection.execute("UPDATE jobs SET selected=? WHERE id=?", (int(payload.selected), job_id))
    return {"ok": True, "selected": payload.selected}


def fallback_draft(profile: dict[str, Any], job: dict[str, Any]) -> tuple[str, str]:
    first_name = profile.get("full_name", "Candidate").split()[0]
    skills = ", ".join(profile.get("skills") or []) or "the projects and skills described in my CV"
    field = ", ".join(profile.get("disciplines") or []) or profile.get("degree") or "this field"
    if job.get("opportunity_kind") == "outreach":
        subject = f"Internship Inquiry — {field} — {profile.get('full_name', '')}"
        body = f"""Hello {job['company']} team,

I am reaching out proactively because your work relates closely to the direction I am building toward in {field}. I am currently studying {profile.get('degree') or 'a relevant degree'} at {profile.get('university') or 'university'}, with hands-on experience in {skills}.

Although I did not find a posted internship, I would be grateful to be considered for an internship, student project, or junior opportunity where I could contribute and learn from your team. My CV is attached for context.

Thank you for your time. I would be happy to share project examples or discuss where my background may be useful.

Best regards,
{profile.get('full_name', first_name)}
{profile.get('phone', '')}
{profile.get('linkedin', '')}"""
        return subject, body.strip()
    subject = f"Application — {job['title']} — {profile.get('full_name', '')}"
    body = f"""Hello {job['company']} team,

I am writing to apply for the {job['title']} opportunity in {job.get('location') or 'your team'}. I am currently studying {profile.get('degree') or 'a relevant degree'} at {profile.get('university') or 'university'}, and my experience with {skills} aligns well with the role.

I would value the opportunity to contribute, learn from your team, and discuss how my projects and coursework could support your work. My CV is attached for review.

Thank you for your time.

Best regards,
{profile.get('full_name', first_name)}
{profile.get('phone', '')}
{profile.get('linkedin', '')}"""
    return subject, body.strip()


async def generate_draft(profile: dict[str, Any], cv_text: str, job: dict[str, Any]) -> tuple[str, str]:
    if not provider_is_connected():
        return fallback_draft(profile, job)
    prompt = f"""
Write a concise, truthful internship email for this candidate and opportunity. Use a warm, professional
tone appropriate for the candidate's location and field. If opportunity_kind is "outreach", explicitly acknowledge that there is no
advertised role and make a respectful proactive inquiry; do not imply the company is hiring. Mention only
skills and experience supported by the profile/CV. Do not invent metrics, contacts, openings, or company
projects. Keep the email body under 220 words. Return JSON with keys subject and body.

Candidate: {json.dumps(profile, ensure_ascii=False)}
CV: {cv_text[:10000]}
Job: {json.dumps(job, ensure_ascii=False)}
"""
    try:
        message = await ai_chat(
            [
                {"role": "system", "content": "You write brief, specific and honest application emails."},
                {"role": "user", "content": prompt},
            ]
        )
        result = extract_json_object(message.get("content") or "")
        subject = str(result.get("subject") or "")[:200].strip()
        body = str(result.get("body") or "")[:5000].strip()
        if subject and body:
            return subject, body
    except (HTTPException, ValueError):
        pass
    return fallback_draft(profile, job)


@app.post("/api/applications/prepare")
async def prepare_applications(payload: JobIdsPayload) -> dict[str, Any]:
    profile, cv_text = profile_context()
    if not payload.job_ids:
        raise HTTPException(422, "Select at least one job.")
    created: list[str] = []
    for job_id in list(dict.fromkeys(payload.job_ids))[:20]:
        with db() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            continue
        job = row_dict(row)
        if job["demo"] or not job["selected"]:
            continue
        subject, body = await generate_draft(profile, cv_text, job)
        method = "email" if job.get("contact_email") else "external"
        app_id = uuid.uuid4().hex
        with db() as connection:
            existing = connection.execute("SELECT id FROM applications WHERE job_id=?", (job_id,)).fetchone()
            if existing:
                connection.execute(
                    "UPDATE applications SET subject=?, body=?, recipient=?, method=?, status='draft' WHERE job_id=?",
                    (subject, body, job.get("contact_email") or "", method, job_id),
                )
                created.append(existing["id"])
            else:
                connection.execute(
                    """INSERT INTO applications
                       (id,job_id,recipient,subject,body,method,status,approved,created_at)
                       VALUES (?,?,?,?,?,?, 'draft',0,?)""",
                    (app_id, job_id, job.get("contact_email") or "", subject, body, method, now_iso()),
                )
                created.append(app_id)
            connection.execute("UPDATE jobs SET status='drafted' WHERE id=?", (job_id,))
    return {"ok": True, "count": len(created), "application_ids": created}


@app.patch("/api/applications/{application_id}")
async def update_application(application_id: str, payload: ApplicationUpdatePayload) -> dict[str, Any]:
    fields: list[str] = []
    values: list[Any] = []
    for name in ("subject", "body", "recipient"):
        value = getattr(payload, name)
        if value is not None:
            if name == "recipient" and value and not EMAIL_RE.match(value):
                raise HTTPException(422, "Enter a valid recipient email.")
            fields.append(f"{name}=?")
            values.append(value[:5000])
    if payload.approved is not None:
        fields.append("approved=?")
        values.append(int(payload.approved))
    if not fields:
        return {"ok": True}
    values.append(application_id)
    with db() as connection:
        cursor = connection.execute(
            f"UPDATE applications SET {', '.join(fields)} WHERE id=?", values  # noqa: S608 (fixed field names)
        )
        if not cursor.rowcount:
            raise HTTPException(404, "Application not found.")
    return {"ok": True}


def send_one_email(application: dict[str, Any], profile_row: sqlite3.Row) -> None:
    smtp = runtime_secrets.get("smtp") or {}
    message = EmailMessage()
    message["Subject"] = application["subject"]
    message["From"] = smtp["from_email"]
    message["To"] = application["recipient"]
    message.set_content(application["body"])

    cv_path = Path(profile_row["cv_path"]) if profile_row["cv_path"] else None
    if cv_path and cv_path.is_file() and cv_path.parent.resolve() == UPLOAD_DIR.resolve():
        suffix = cv_path.suffix.lower()
        subtype = "pdf" if suffix == ".pdf" else "vnd.openxmlformats-officedocument.wordprocessingml.document"
        maintype = "application"
        if suffix in {".txt", ".md"}:
            maintype, subtype = "text", "plain"
        message.add_attachment(
            cv_path.read_bytes(),
            maintype=maintype,
            subtype=subtype,
            filename=profile_row["cv_filename"] or f"CV{suffix}",
        )

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp["host"], int(smtp["port"]), timeout=30) as server:
        if smtp.get("use_tls", True):
            server.starttls(context=context)
        server.login(smtp["username"], smtp["password"])
        server.send_message(message)


@app.post("/api/applications/send")
async def send_applications(payload: SendPayload) -> dict[str, Any]:
    if not payload.confirm_send:
        raise HTTPException(400, "Final send confirmation is required.")
    smtp = runtime_secrets.get("smtp") or {}
    if not smtp.get("password"):
        raise HTTPException(409, "Connect your email account in Settings before sending.")
    sent: list[str] = []
    failed: list[dict[str, str]] = []
    with db() as connection:
        profile_row = connection.execute("SELECT * FROM profile WHERE id=1").fetchone()
    if not profile_row:
        raise HTTPException(409, "Profile not found.")
    for application_id in list(dict.fromkeys(payload.application_ids))[:20]:
        with db() as connection:
            row = connection.execute(
                """SELECT applications.*, jobs.selected, jobs.demo
                   FROM applications JOIN jobs ON jobs.id=applications.job_id
                   WHERE applications.id=?""",
                (application_id,),
            ).fetchone()
        if not row:
            continue
        application = dict(row)
        if (
            not application["approved"]
            or not application["selected"]
            or application["demo"]
            or application["method"] != "email"
            or not EMAIL_RE.match(application["recipient"] or "")
        ):
            failed.append({"id": application_id, "error": "Application is not eligible to send."})
            continue
        try:
            await asyncio.to_thread(send_one_email, application, profile_row)
            with db() as connection:
                connection.execute(
                    "UPDATE applications SET status='sent', sent_at=? WHERE id=?", (now_iso(), application_id)
                )
                connection.execute("UPDATE jobs SET status='applied' WHERE id=?", (application["job_id"],))
            sent.append(application_id)
        except (smtplib.SMTPException, OSError) as exc:
            failed.append({"id": application_id, "error": str(exc)[:240]})
    return {"ok": not failed, "sent": sent, "failed": failed}


@app.delete("/api/data")
async def clear_local_data() -> dict[str, Any]:
    with db() as connection:
        paths = [Path(row[0]) for row in connection.execute("SELECT cv_path FROM profile WHERE cv_path IS NOT NULL")]
        connection.execute("DELETE FROM applications")
        connection.execute("DELETE FROM jobs")
        connection.execute("DELETE FROM profile")
    for path in paths:
        if path.is_file() and path.parent.resolve() == UPLOAD_DIR.resolve():
            path.unlink(missing_ok=True)
    runtime_secrets["ai_provider"] = "openrouter"
    runtime_secrets["openrouter_key"] = ""
    runtime_secrets["openai_key"] = ""
    runtime_secrets["ollama"] = {
        "base_url": "http://127.0.0.1:11434",
        "model": system_capabilities()["recommendation"]["model"],
        "search_api_key": "",
        "searxng_url": "",
        "connected": False,
        "models": [],
    }
    runtime_secrets["smtp"] = {}
    return {"ok": True}
