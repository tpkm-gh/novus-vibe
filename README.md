# Fund Screen PDF Copilot (prototype)

Built as a demo for a forward-deployed-engineer conversation at NovusMinds AI
(WealthOS). Not affiliated with NovusMinds -- built independently, informed
by the company's own public description of WealthOS as "AI workflow and
compliance automation for RIAs, TAMPs, and private banks."

**Full writeup — discovery, architecture, decisions, assumptions,
limitations, and scaling plan — is in [`docs/PLAYBOOK.md`](docs/PLAYBOOK.md).
Start there.** This file is just how to run it.

## What it does

Advisor pastes the URL of a fund-listing/screener webpage. A **DocGen
agent** turns it into a durable PDF snapshot via Adobe PDF Services
(HTML-to-PDF-from-URL), self-reviews its own output, and retries once or
twice if the result looks wrong -- rather than silently handing back a
broken or blank document. A **Controller agent** keeps a small dashboard in
sync with every request/response stored in Postgres, so an advisor (or an
ops person watching the pipeline) can see status, retries, and download or
re-retrieve any prior document.

## Run it -- zero setup (SQLite + mock provider)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults: SQLite fallback, mock PDF provider, rule-based reflection
uvicorn app.main:app --reload --port 8000
# open http://localhost:8000
```

No Adobe account, no Anthropic key, no Postgres needed. The mock provider
makes a best-effort real fetch of whatever URL you paste and renders it to
an actual PDF; if the fetch fails (no network, bot-blocked page) it falls
back to a deterministic synthetic fund listing so the pipeline still runs
end to end.

```bash
pytest -q   # 32 tests: unit tests per component + a 5-scenario eval harness
```

## Run it against real Postgres

```bash
docker compose up -d db          # postgres:16 on localhost:5432
# in .env: USE_SQLITE_FALLBACK=0, DATABASE_URL=postgresql+psycopg://novus:novus@localhost:5432/novus_vibe
uvicorn app.main:app --reload --port 8000
```

Verified during development against a real local PostgreSQL 16 instance
(not just SQLite) -- see `docs/PLAYBOOK.md`, "Build & operate".

## Flip on the live Adobe PDF Services API

Free tier: 500 document transactions/month, no credit card.
[Get credentials](https://developer.adobe.com/document-services/docs/overview/pdf-services-api/gettingstarted/),
then in `.env`:

```
PDF_PROVIDER=live
PDF_SERVICES_CLIENT_ID=...
PDF_SERVICES_CLIENT_SECRET=...
```

See `docs/PLAYBOOK.md`, "Assumptions" for what to verify before relying on
this path live in front of an interviewer.

## Repo layout

```
app/
  agents/
    docgen_agent.py        Agent 1: plan -> act -> observe -> reflect -> retry loop
    controller_agent.py    Agent 2: DB -> view-model for the dashboard
    providers/              mock (offline, default) / live (real Adobe SDK) PDF generation
    reflection/              rule_based (default) / llm (optional Anthropic critique)
  main.py                  FastAPI routes
  models.py, repository.py  Postgres/SQLAlchemy schema + CRUD
  static/index.html        the dashboard (vanilla JS, no build step)
tests/                     32 tests: unit + API + 5-scenario eval harness
docs/PLAYBOOK.md           the actual writeup
```
