# GameJob Scout

Human-in-the-loop job discovery for game studios and technology companies.

GameJob Scout monitors a configurable list of companies, collects jobs from their **official**
public careers sources, normalizes and deduplicates them, scores them against a structured
candidate profile, and presents the best matches for review. No applications are submitted
automatically — the human stays in the loop.

> **Status: early development.** Phase 1 (reliable job ingestion) is in progress.
> Complete so far: the project scaffold, the validated domain models, a responsible HTTP
> layer (robots.txt enforcement, per-host rate limiting, bounded retries, redirect
> validation, typed failures), and the Greenhouse collector.
> Not built yet: the Lever collector, normalization, persistence, deduplication, the CLI,
> matching, the dashboard, and the discovery agent.

## Design principle

Deterministic code does everything that should be predictable. An LLM is used only where
semantic judgment genuinely helps.

| Deterministic (plain Python) | LLM-assisted |
| --- | --- |
| HTTP fetching, retries, rate limiting | Interpreting ambiguous job descriptions |
| Known ATS parsing (Greenhouse, Lever) | Comparing a job against the candidate profile |
| Normalization and validation | Explaining compatibility and skill gaps |
| Hard eligibility filters | Drafting application material (after approval) |
| Deduplication, persistence, scheduling | Tool selection during company discovery |

## Planned architecture

```
config → collectors (per-ATS) → normalization → deduplication → SQLite
                                                      ↓
                              eligibility filters → LLM matching → MatchResult
                                                      ↓
                                    Streamlit review dashboard + daily digest
                                                      ↓
                                 approved jobs → tailored application drafts
```

A separate, genuinely agentic workflow (Phase 3) discovers recently funded game companies,
resolves their official websites and careers pages, detects the ATS in use, and flags anything
uncertain for human review. It never trusts or adds an unverified URL on its own.

## Requirements

- Python 3.12 or newer (developed on 3.13)
- No API keys are required for Phase 1

## Quickstart

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Then copy the environment template and adjust as needed:

```bash
cp .env.example .env   # PowerShell: Copy-Item .env.example .env
```

## Development commands

```bash
ruff check .            # lint
ruff format --check .   # formatting check (drop --check to reformat)
mypy                    # strict type checking (src + tests)
pytest                  # tests (fully offline, no network, no API calls)
```

CI runs these same four commands on Python 3.12 and 3.13.

## Project layout

```
src/gamejob_scout/   application package (grows one milestone at a time)
tests/               offline tests and fixtures
.github/workflows/   continuous integration
```

## Roadmap

1. **Phase 1 — Reliable job ingestion**: domain models, collector interface, Greenhouse and Lever
   collectors, normalization, SQLite persistence, deduplication, CLI, offline fixtures and tests.
2. **Phase 2 — Semantic job matching**: deterministic eligibility filters, a provider-independent
   structured LLM client, validated `MatchResult` with required evidence, a fake LLM for tests.
3. **Phase 3 — Agentic company discovery**: funded-company discovery, official site and careers
   page resolution, ATS detection, guardrails, tracing, human review for anything uncertain.
4. **Phase 4 — Human review and digest**: Streamlit dashboard, job status workflow, match
   explanations, application drafts for approved jobs, daily digest.
5. **Phase 5 — Deployment and portfolio presentation**: scheduling, failure notifications, CI,
   architecture and evaluation documentation, demo script, limitations.

## Source coverage

Supported ATS integrations and per-company status will be listed here as they are **verified**.
Nothing is listed until its careers URL and ATS have been confirmed against the company's own
public pages — no guessed URLs, no assumed ATS.

| Company | Careers source | ATS | Status |
| --- | --- | --- | --- |
| Good Job Games | [Greenhouse job board](https://job-boards.greenhouse.io/goodjobgames) | Greenhouse | Verified — readable by the Greenhouse collector |

Greenhouse is the first supported ATS. A board is read through its public Job Board API,
which needs no authentication, returns a whole board in one response, and whose
`robots.txt` permits the endpoint we use.

## Responsible use

- Only official company careers pages, permitted public ATS endpoints, and legitimate public
  sources are used. **LinkedIn is not scraped.**
- `robots.txt`, rate limits, and timeouts are respected. CAPTCHA, authentication, and anti-bot
  protections are never bypassed.
- Applications are never submitted automatically, and emails are not sent without explicit
  configuration.
- No real personal data, CV, or secrets are committed to this repository. Example candidate data
  is fictional. Secrets live in environment variables (see `.env.example`).
- Tests require no internet access, no personal data, and no paid API calls.

## License

MIT — see [LICENSE](LICENSE).
