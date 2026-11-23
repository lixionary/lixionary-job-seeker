# Lixionary Job Seeker — Personal Job Radar & Application Triage System

A single-user, automated job discovery, LLM fit evaluation, and Kanban application triage system tailored for **Engineering Leadership**, **Quality Engineering Leadership**, and **Strategic IC** roles across **Jakarta/Indonesia, Singapore, and Remote APAC**.

## Architecture
- **Backend (`backend/`)**: Python 3.12, FastAPI, Motor (async MongoDB), APScheduler, HTTPX.
  - Connectors: **Greenhouse**, **Lever**, **Ashby**, plus optional **Apify LinkedIn** and **SerpApi Google Jobs**.
  - Deduplication (`sha256(normalize(company) + "|" + normalize(title))`) & pre-LLM title/location pre-filtering.
  - **MiniMax 3 / OpenAI-Compatible Scorer** with deterministic heuristic fallback when `LLM_API_KEY` is not yet set.
  - On-demand **Tailored Pitch Generator** (3–4 line CV summary, top 3 metrics bullets, and hiring manager outreach).
  - Scheduled **Daily Telegram Digest** (`08:30 WIB`).
- **Frontend (`frontend/`)**: Next.js 15 (App Router, TypeScript, Tailwind CSS) standalone Docker container with runtime `/api/*` proxy to the FastAPI backend.
- **Database (`mongo`)**: MongoDB 7 with persistent Docker volume (`mongo_data`).
- **Configuration (`config/`)**:
  - `config/cv.md` — Candidate baseline CV in Markdown
  - `config/preferences.yaml` — Target tracks, geographies, exclude/include keywords, score threshold
  - `config/companies.yaml` — Watchlist of Greenhouse, Lever, and Ashby company slugs
  - All three files can also be edited live via the **"CV & Config"** button in the dashboard UI.

## Quick Start (Docker Compose)

```bash
cp .env.example .env
# Optional: Add LLM_API_KEY (MiniMax) and TELEGRAM_BOT_TOKEN in .env
docker compose up -d --build
```

- **Kanban Dashboard UI (Tailscale Service)**: `https://job-seeker.fluffy-oratrice.ts.net` (local host binding `127.0.0.1:9210`)
- **Backend OpenAPI Docs**: `https://job-seeker.fluffy-oratrice.ts.net:9211/docs` (local host binding `127.0.0.1:9211/docs`)

## CLI Commands

```bash
# Manually run ingestion connectors from CLI
docker compose exec backend python -m app.cli run-ingest

# Preview / send daily digest from CLI
docker compose exec backend python -m app.cli send-digest

# Run backend unit tests
docker compose run --rm backend pytest -v
```
