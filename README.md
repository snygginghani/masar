# Masar

Masar is a local, approval-first opportunity engine for internships, traineeships, graduate programs, and entry-level roles. It works with any major, city, region, or country. It finds posted opportunities and relevant organizations worth contacting proactively, then stops and waits for the candidate to choose what moves forward.

Nothing is sent automatically.

## Highlights

- Candidate-defined fields, roles, skills, cities, countries, and search locations
- PDF, DOCX, TXT, and Markdown CV extraction on the user's computer
- Three research lanes: posted roles, specialist organizations, and established employers with relevant teams
- Direct-source preference, URL reachability checks, evidence links, source confidence, CV-fit reasons, and honest gaps
- Proactive internship inquiries that never pretend an advertised vacancy exists
- Published-contact verification; guessed and unconfirmed email addresses are discarded
- Toggle-based shortlist, editable drafts, per-message approval, and a final send confirmation
- Gmail, Microsoft 365, and custom SMTP support with CV attachment
- OpenRouter, OpenAI, or local Ollama model support
- Automatic RAM/GPU inspection and a practical Ollama model recommendation
- Local SQLite storage; API keys and email passwords stay in server memory and disappear on restart

## Quick start

Python 3.11 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe main.py
```

On macOS or Linux, activate `.venv` or run `.venv/bin/python` instead. Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

## First run

1. Complete the profile, including target disciplines and search locations, then upload a CV.
2. In **Settings**, choose OpenRouter, OpenAI, or Ollama and connect it.
3. Run an opportunity scan and inspect the evidence for every result.
4. Toggle only the opportunities you want, then prepare applications.
5. Review and edit each draft. Approve only messages you want to send.
6. Connect an email sender for email applications. External forms are opened for manual completion.

## AI provider choices

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
6. Proactive targets are deduplicated when the same employer already has a posted role.

Search engines and public pages can still be wrong or stale. Always open the evidence and verify the closing date, eligibility, recipient, and message before approval.

## Privacy and safety

- CV files live in `data/uploads/`; profile, leads, and drafts live in `data/masar.db`.
- `data/`, secrets, editor settings, and temporary files are excluded from Git.
- Restarting Masar clears all API and SMTP credentials.
- External application forms are never submitted silently.
- Email sending requires a real opportunity, explicit selection, a prepared draft, draft approval, a valid recipient, configured SMTP, and a final confirmation.
- Use the app only for truthful, relevant applications and respect employer terms, local laws, and reasonable outreach rates.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The suite covers profile/CV storage, demo safety, provider dispatch, hardware recommendations, generalized location rules, three-lane discovery, verification and deduplication, selections, draft approval, and the SMTP send gate.

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md) first. Masar is released under the [MIT License](LICENSE).
