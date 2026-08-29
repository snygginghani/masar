# Contributing to Masar

Thanks for helping make opportunity discovery more useful and accountable.

## Development setup

1. Fork and clone the repository.
2. Create a Python 3.11+ virtual environment.
3. Install the project with `python -m pip install -e ".[dev]"`.
4. Run `python main.py` and open `http://127.0.0.1:8765`.
5. Run `python -m pytest` before opening a pull request.

## Pull requests

- Keep changes focused and explain the candidate-facing behavior.
- Add or update tests for engine, safety-gate, or API changes.
- Preserve the explicit selection, draft approval, and final-send gates.
- Never add guessed personal email addresses, scraping bypasses, automatic bulk sending, or silent form submission.
- Do not commit CVs, SQLite databases, API keys, SMTP passwords, screenshots containing personal details, or copied job-board content.
- Keep UI controls keyboard accessible and usable at narrow screen widths.

## Research providers

Provider integrations should return a common message shape: `content` plus optional URL annotations. Current information must come from a search tool or supplied sources, not model memory. New search adapters must document what leaves the computer.

## Reporting bugs

Include the operating system, Python version, selected provider, model name, exact error, and a minimal reproduction. Remove secrets and personal CV data before posting logs.
