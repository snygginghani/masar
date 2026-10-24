<p align="center"><img src="static/assets/masar-symbol.png" width="88" alt="Masar logo"></p>

<h1 align="center">Masar</h1>

<p align="center">Your career search. Your evidence. Your approval.</p>

<p align="center">
  <a href="https://github.com/snygginghani/masar/actions/workflows/tests.yml"><img src="https://github.com/snygginghani/masar/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-174d3c" alt="Python 3.11 or newer">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-174d3c" alt="MIT License"></a>
</p>

Masar is a local, approval-first opportunity engine for internships, traineeships, graduate programs, and entry-level roles. It works with any major, city, region, or country. It finds posted opportunities and relevant organizations worth contacting proactively, then stops and waits for the candidate to choose what moves forward.

Nothing is sent automatically.

**Status: active development.** Built for personal, local use—not a hosted multi-user service. Review generated content and source evidence before applying. Masar cannot guarantee an internship, exhaustive search coverage, or recruiter accuracy.

[Get started](#quick-start) · [CV autofill](#cv-to-profile-autofill) · [Privacy](#privacy-and-safety) · [Contribute](CONTRIBUTING.md)

## The workflow

**Profile → CV Studio → Discover → Shortlist → Review drafts → Approve & send**

Build a profile from your CV, improve its presentation, research relevant opportunities and public recruiting contacts, then decide exactly what moves forward.

## Highlights

- Candidate-defined fields, roles, skills, cities, countries, and search locations
- PDF, DOCX, TXT, and Markdown CV extraction on the user's computer
- CV Studio with a transparent writing-readiness rubric, editable sections, optional evidence-backed AI rewriting, and selectable-text A4 PDF export
- Responsive four-step workspace: profile, CV review, discovery, and application approval
- Evidence-linked candidate-detail extraction via dedicated low-cost OpenRouter models, with per-field selection before saving
- Three research lanes: posted roles, specialist organizations, and established employers with relevant teams
- Direct-source preference, URL reachability checks, evidence links, source confidence, CV-fit reasons, and honest gaps
- Proactive internship inquiries that never pretend an advertised vacancy exists
- Dedicated small-batch research across public LinkedIn profiles, public LinkedIn hiring posts, and official company pages for recruiters, talent-acquisition, people-operations, campus-hiring, and early-careers contacts
- Every saved contact needs a reachable professional source; guessed, personal, and unconfirmed email addresses are discarded
- Toggle-based shortlist, editable drafts, per-message approval, and a final send confirmation
- Gmail, Microsoft 365, and custom SMTP support with CV attachment
- OpenRouter, OpenAI, or local Ollama model support
- Automatic RAM/GPU inspection and a practical Ollama model recommendation
- Local SQLite storage; API keys and email passwords stay in server memory and disappear on restart

## Quick start

Python 3.11 or newer is required.

Clone the source first:

```sh
git clone https://github.com/snygginghani/masar.git
cd masar
```

Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe main.py
```

macOS / Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python main.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). Keep the terminal running. No AI account is required for local CV review and PDF editing; discovery and AI assistance require the relevant provider configuration.

## First run

1. Complete the profile, including target disciplines and search locations, then upload a CV.
2. In **Settings**, choose OpenRouter, OpenAI, or Ollama and connect it.
   Open **CV Studio** to review your writing, edit the single-column document, and preview/download a PDF. The local review and editor need no AI key. AI rewriting requires consent and a usable model. The score is a writing checklist, not an ATS certification or hiring prediction. The PDF template is intended for Latin-script CVs.
3. Run an opportunity scan and inspect the evidence for every result.
   Use **Search HR on LinkedIn** in the opportunity radar whenever you want to refresh contacts for saved employers without repeating the full opportunity scan.
4. Toggle only the opportunities you want, then prepare applications.
5. Review and edit each draft. Approve only messages you want to send.
6. Connect an email sender for email applications. External forms are opened for manual completion.

Revised CVs are drafts until you explicitly confirm their facts and choose to use them. Uploading or adopting a different CV resets unsent application approvals; review those messages again before sending. Non-secret connection preferences persist locally, but keys and passwords do not. Generated personal documents in `output/` are excluded from Git.

## AI provider choices

### CV-to-profile autofill

In **My profile → Fill details from your CV**, choose an extraction model, give explicit consent, and extract your uploaded CV. Inspect the supporting quotations, select the fields to use, then save the profile. Existing values are unchecked by default. Edits made while extraction is running are protected; stale results from a different CV/profile cannot be applied. Extraction does not send applications or change the discovery model. Even with Ollama selected for discovery, this optional feature explicitly sends CV text through OpenRouter.

Model selection reviewed **14 October 2026** against the live OpenRouter catalog:

| Model | Input / million | Output / million | Role |
| --- | --- | --- | --- |
| [Mercury 2.5](https://openrouter.ai/inception/mercury-2.5) | $0.04 | $0.15 | Default value/latency candidate; schema-aligned output |
| [Nex-N2.5-Mini](https://openrouter.ai/nex-agi/nex-n2.5-mini) | $0.025 | $0.10 | Lower-cost alternative |

Both were released in September 2026. These are engineering choices, **not a claim of benchmark-proven best CV accuracy or absolute lowest price**. Older and free models can cost less; an HTML-specialized extraction model is not automatically best for PDF-extracted resume text. Mercury's displayed pricing is promotional and can change. Each request checks the live catalog and uses provider-level ceilings of $0.10/M input and $0.40/M output, a 24,000-character source limit and 2,200 output-token limit. No automatic model escalation or paid retries are performed. A 3,000-input/1,000-output example costs approximately $0.00027 on Mercury at the cited rates; actual billable usage, including reasoning, varies.

Strict JSON validation and source-quote checks remove unsupported values. They do not prove semantic correctness: users must check whether a university is an education institution rather than an employer, and whether dates are graduation dates. Unstated preferences, availability and work authorization must be entered manually. Automated extraction tests use synthetic responses; live accuracy requires evaluation with a funded key and representative CVs.

| Provider | Model processing | Live discovery | What you need |
| --- | --- | --- | --- |
| OpenRouter | Hosted | OpenRouter web-search tool | OpenRouter API key and a tool-capable model |
| OpenAI | Hosted | Responses API web-search tool | OpenAI API key and a web-search-capable model |
| Ollama | Local | Ollama Web Search or your own SearXNG | Running Ollama, an installed model, and one optional search source |

Masar verifies hosted keys during connection without making a paid model request. Provider and SMTP secrets are never returned by `/api/state` and are not written to disk.

### Ollama

Install and start [Ollama](https://ollama.com/), then open Masar Settings. Masar inspects system RAM and supported NVIDIA VRAM and recommends a Qwen3 size. Pull the recommendation shown in the UI, for example:

```powershell
ollama pull qwen3:8b
ollama serve
```

Masar lists models already installed on the connected Ollama server. Local CV matching and draft generation require no hosted model account.

Live job discovery still needs current web evidence. Choose one:

- **Ollama Web Search:** requires an Ollama account/API key; only search queries use that hosted search service.
- **SearXNG:** point Masar to your self-hosted SearXNG JSON endpoint for a fully self-hosted AI-and-search path.
- **None:** local matching and drafting work, but live discovery is intentionally disabled instead of using stale model memory.

## Gmail App Password

Gmail does not accept a normal account password over this SMTP flow. Enable 2-Step Verification, create a 16-character App Password, and paste that into Masar. The app removes display spaces automatically.

- [Google's official App Password instructions](https://support.google.com/accounts/answer/185833?hl=en)
- [Video tutorial included in the app](https://www.youtube.com/watch?v=ckfyTVgF1T4)

## Accuracy model

Masar favors precision over result count:

1. It asks the model to search role synonyms and CV-supported adjacent titles.
2. It separately researches specialist organizations and larger employers with relevant teams.
3. It rejects senior roles, generic search-result pages, low-confidence records, and location mismatches.
4. It fetches each saved source. Unreachable records are discarded.
5. A contact email survives only when it appears on the saved public page.
6. A dedicated enrichment pass searches small employer batches across public LinkedIn profiles, public LinkedIn hiring posts, and official company pages. It keeps up to three current recruiting contacts per organization only after verifying the role plus the person's name or published work email on the cited page.
7. Proactive targets are deduplicated when the same employer already has a posted role.

Search engines and public pages can still be wrong or stale. Always open the evidence and verify the closing date, eligibility, recipient, and message before approval.

## Privacy and safety

- CV files live in `data/uploads/`; profile, leads, and drafts live in `data/masar.db`.
- `data/`, secrets, editor settings, and temporary files are excluded from Git.
- Restarting Masar clears all API and SMTP credentials.
- External application forms are never submitted silently.
- Contact research excludes free/personal email providers, inferred address patterns, enrichment databases, former employees, and profiles with unclear current affiliation.
- Email sending requires a real opportunity, explicit selection, a prepared draft, draft approval, a valid recipient, configured SMTP, and a final confirmation.
- Use the app only for truthful, relevant applications and respect employer terms, local laws, and reasonable outreach rates.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite covers profile/CV storage, demo safety, provider dispatch, hardware recommendations, generalized location rules, three-lane discovery, verification and deduplication, selections, draft approval, and the SMTP send gate.

It also covers CV exports, stale-source protection, extraction consent, schema validation, source evidence, and price caps. CI uses isolated temporary storage and mocked provider responses: no real CV, API key, paid request or email account is required.

## Project structure

```text
masar_app/
  app.py                 API, research engine, storage and approval gates
  cv_studio.py           CV checks, editable documents and PDF generation
  profile_extraction.py  Low-cost, evidence-checked profile suggestions
static/                  Accessible HTML, CSS and JavaScript workspace
tests/                   Isolated API and integration tests
data/                    Private local storage (not published)
```

## Limitations

- Public LinkedIn pages may block access; Masar does not bypass authentication or access controls.
- A reachable source or matching quotation is evidence, not proof of correctness.
- The CV score is a transparent writing checklist, not an ATS score or hiring prediction.
- The current generated-PDF template is intended for Latin-script CVs; scanned PDFs may require OCR elsewhere.
- API pricing and model availability change. Extraction checks live rates and fails if its price ceiling cannot be met.
- Do not expose the unauthenticated local server to the internet or a shared network.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) first. Masar is released under the [MIT License](LICENSE).
