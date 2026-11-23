# PRD: Personal Job Radar & Application Triage System

## 1. Overview & Objective
Build a single-user, automated job discovery, LLM-powered evaluation, and application tracking system tailored for senior engineering leadership roles (e.g., Head of Engineering, VP of Engineering, Director of QA/Quality Engineering, Senior Engineering Manager, Principal/Staff Engineer).

The system aggregates listings from reliable job sources, deduplicates cross-posted roles, scores each job against a local candidate CV using an LLM (with a deterministic heuristic fallback when offline/unconfigured), and surfaces high-signal matches in a lightweight Kanban triage dashboard and daily digest.

### Non-Goals (Explicitly Out of Scope for MVP)
* **No custom LinkedIn/Indeed anti-bot bypasses:** Do not build headless browser scrapers to fight LinkedIn CAPTCHAs or login walls. Use managed APIs (Apify/SerpApi) for those sources.
* **No automated job applications:** The system assists discovery and tailoring; all applications are submitted manually.
* **No multi-tenant authentication or billing:** This is a personal tool (local-first or self-hosted behind a private Tailscale network).

---

## 2. Candidate Baseline & Target Profile
The scoring engine loads a local Markdown file (`config/cv.md`) and a preferences file (`config/preferences.yaml`) as ground truth (also editable live via the in-app dashboard settings drawer and persisted in MongoDB + synced to disk).

* **Baseline Experience:** 10+ years in logistics technology progressing from QA Automation Engineer to Head of Engineering. Led up to 41 QA engineers at peak and later managed a cross-country engineering and QA organization across Indonesia and Vietnam.
* **Key Differentiators to Match Against:** Automation-first QA (92% coverage across 23K tests), AI-assisted engineering workflows (up to 75% cycle-time reduction), build-vs-buy internal tooling (custom device farm, test case management saving $23K/year), and backend/mobile/web release ownership.
* **Target Role Tracks:**
  1. `Engineering Leadership` (Head of Engineering, VP of Engineering, Senior EM)
  2. `Quality Engineering Leadership` (Head/Director of QA, Quality Engineering Manager)
  3. `Hands-on Strategic IC` (Principal / Staff Engineer — Platform, DevEx, or AI Tooling)
* **Target Geographies (Configurable):** `Jakarta / Indonesia (Hybrid/On-site/Remote), Remote APAC, Singapore`

---

## 3. System Architecture & Tech Stack

```text
[Sources: Greenhouse / Lever / Ashby APIs + Apify / SerpApi]
                                  │
                                  ▼
             [Python Ingestion & Deduplication Worker]
                                  │
                                  ▼
   [MiniMax 3 / OpenAI-Compatible Scorer + Heuristic Fallback]
                                  │
                                  ▼
             [MongoDB 7 (jobs, scrape_runs, settings)]
                                  │
                 ┌────────────────┴────────────────┐
                 ▼                                 ▼
    [FastAPI Backend + Next.js Kanban UI]   [Daily Telegram Digest]
```

* **Ingestion Worker & API:** Python 3.12+, `FastAPI`, `httpx`, `pydantic`, `motor` (async MongoDB driver), `APScheduler`.
* **Database:** **MongoDB 7** (`mongo:7` container with persistent Docker volume) storing normalized job documents, nested `llm_analysis`, `tailored_pitch`, `scrape_runs`, and synced configuration.
* **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS (standalone Docker output with `/api/*` proxy rewrite to FastAPI backend).
* **LLM Integration:** OpenAI-compatible client configured by default for **MiniMax 3** (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`), supporting structured JSON extraction and on-demand CV tailoring. Includes a deterministic heuristic fallback scorer when `LLM_API_KEY` is not yet configured so ingestion works immediately and jobs can be re-scored with one click.
* **Containerization & Deployment:** Multi-arch compatible Dockerfiles (`python:3.12-slim`, `node:22-alpine`, `mongo:7`) supporting `linux/arm64` for local macOS verification and `linux/amd64` for deployment on `lixsu@mini-pc-2.fluffy-oratrice.ts.net` (`~/workspace/lixionary/lixionary-job-seeker`).

---

## 4. Functional Requirements

### FR-1: Modular Job Source Connectors
Implement a `BaseConnector` abstract class returning a normalized list of `RawJob` objects.
* **Tier 1 — Direct ATS Feeds (Required for MVP):**
  * **Greenhouse:** `GET https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true`
  * **Lever:** `GET https://api.lever.co/v0/postings/{company}?mode=json`
  * **Ashby:** `GET https://api.ashbyhq.com/posting-api/job-board/{company}`
  * Driven by a user-editable `config/companies.yaml` watchlist (editable in UI). Each company slug is isolated so an inactive slug does not fail the connector run.
* **Tier 2 — Managed Aggregators (Optional via API Key):**
  * **Apify LinkedIn Jobs** and **SerpApi Google Jobs** connectors.
  * Gracefully skip if API keys (`APIFY_TOKEN`, `SERPAPI_KEY`) are absent from `.env`.

### FR-2: Deduplication & Cheap Pre-Filtering
* **Deduplication:** Compute `dedup_hash = sha256(normalize(company) + "|" + normalize(title))`. If a job already exists, append the new source URL to its `source_urls` list and update `last_seen_at` without resetting its triage status or re-scoring it.
* **Pre-Filter (Pre-LLM):** Before invoking the LLM, filter out obvious non-matches using configurable rules in `config/preferences.yaml` (e.g., reject titles containing `Intern`, `Junior`, `Sales`, `Account Executive`, `Marketing` unless overridden by an allowlist). Mark filtered jobs as `status = 'filtered_out'` so they are not re-evaluated.

### FR-3: LLM Fit Scoring & Extraction
For every new job passing the pre-filter, send the Job Description + `config/cv.md` + `config/preferences.yaml` to the LLM (or heuristic fallback if `LLM_API_KEY` is unset) and store a structured JSON analysis:

```json
{
  "match_score": 8,
  "role_track": "Engineering Leadership",
  "location_policy": "Hybrid - Jakarta",
  "relocation_or_visa_note": "Local role, no sponsorship needed",
  "summary": "2-sentence explanation of why this role fits.",
  "match_reasons": [
    "Strong match on scaling QA + Engineering teams across multi-product orgs",
    "Values AI-assisted SDLC productivity improvements"
  ],
  "red_flags": [
    "Requires deep Rust production experience"
  ],
  "tailoring_angle": "Highlight the 75% AI workflow cycle-time reduction and Ops Hub ownership.",
  "scored_by": "llm"
}
```

### FR-4: Kanban Triage Dashboard (Frontend)
A clean, single-page Kanban board with the following columns:
1. `New` (default filter: `match_score >= 7`, with a toggle to show all scores / filtered jobs)
2. `Shortlisted`
3. `Applied`
4. `Interviewing`
5. `Archived / Rejected`

**UI Capabilities:**
* **Job Card:** Displays Company, Title, `match_score` badge (color-coded), `role_track`, `location_policy`, source badges, and age (`2d ago`).
* **Job Detail Drawer (on click):**
  * LLM breakdown (`summary`, `match_reasons`, `red_flags`, `tailoring_angle`, and `Re-score` action).
  * Full cleaned Job Description + direct external apply link(s).
  * Status dropdown + free-text Markdown notes field (for recruiter contacts, interview notes, salary range).
  * **"Generate Tailored Pitch" button:** Calls the LLM on demand to produce:
    1. A tailored 3–4 line CV summary aligned to the JD.
    2. Top 3 CV bullet points to emphasize.
    3. A concise LinkedIn/email outreach message to a hiring manager or recruiter.
* **Manual Job Entry Modal:** Allows pasting a job URL or raw JD text (e.g., roles shared via WhatsApp/recruiters), automatically runs it through the scorer, and adds it to the board.
* **Trigger Scrape & Runs Drawer:** Manually runs ingestion connectors and displays run history, metrics, and errors.
* **In-App CV & Config Editor:** View and edit `config/cv.md`, `config/preferences.yaml`, and `config/companies.yaml` directly from the dashboard.

### FR-5: Daily Digest Notification
* Scheduled job (default `08:30 WIB` / `Asia/Jakarta`) that queries newly discovered jobs from the past 24 hours with `match_score >= 7`.
* Sends a concise formatted message via **Telegram Bot API** listing up to the top 5 roles with score, company, title, 1-line rationale, and link to the dashboard/apply URL, plus an in-app preview & manual send modal.

---

## 5. Core Data Model (MongoDB Collections)

### Collection: `jobs`
```json
{
  "id": "uuid-v4",
  "dedup_hash": "sha256(normalize(company)|normalize(title))",
  "company": "Grab",
  "title": "Head of Quality Engineering",
  "location_raw": "Jakarta, Indonesia",
  "description": "Cleaned plain-text job description...",
  "source_urls": [
    { "source": "greenhouse", "url": "https://..." }
  ],
  "status": "new",
  "match_score": 9,
  "role_track": "Quality Engineering Leadership",
  "location_policy": "Hybrid - Jakarta",
  "llm_analysis": {
    "match_score": 9,
    "role_track": "Quality Engineering Leadership",
    "location_policy": "Hybrid - Jakarta",
    "relocation_or_visa_note": "Local role in Jakarta",
    "summary": "...",
    "match_reasons": ["..."],
    "red_flags": [],
    "tailoring_angle": "...",
    "scored_by": "minimax"
  },
  "tailored_pitch": {
    "cv_summary": "...",
    "emphasized_bullets": ["..."],
    "outreach_message": "...",
    "generated_at": "2026-11-23T03:30:00Z"
  },
  "notes": "",
  "first_seen_at": "2026-11-23T03:00:00Z",
  "last_seen_at": "2026-11-23T03:00:00Z",
  "updated_at": "2026-11-23T03:00:00Z"
}
```

### Collection: `scrape_runs`
```json
{
  "id": "uuid-v4",
  "connector_name": "greenhouse",
  "started_at": "2026-11-23T03:00:00Z",
  "finished_at": "2026-11-23T03:00:12Z",
  "status": "success",
  "jobs_fetched": 142,
  "jobs_new": 18,
  "jobs_scored": 9,
  "jobs_filtered": 9,
  "tokens_used": 14500,
  "error_message": null
}
```

### Collection: `settings`
Stores the active `cv_markdown`, `preferences_yaml`, and `companies_yaml` synced with `config/cv.md`, `config/preferences.yaml`, and `config/companies.yaml`.

---

## 6. Non-Functional Requirements & Guardrails
* **Idempotency:** Running the scraper multiple times a day must never create duplicate rows or re-score already-scored jobs.
* **Rate Limiting & Resilience:** Each connector and company slug isolates failures, implements request timeouts (15s), and logs results to `scrape_runs`.
* **Cost Control:** Log LLM input/output token counts per run. Enforce a configurable `MAX_LLM_SCORES_PER_RUN` safety cap (default: `50`).
* **Clean Configuration:** All secrets (`LLM_API_KEY`, `APIFY_TOKEN`, `SERPAPI_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) live in `.env` with `.env.example` committed to the repo.

---

## 7. Pre-Handoff Configuration Checklist (Finalized)
- [x] **Target Geographies:** *Jakarta/Indonesia, Remote APAC, Singapore*
- [x] **LLM Provider & Model:** *MiniMax 3 (OpenAI-compatible client via `.env` + heuristic fallback)*
- [x] **Database Choice:** *MongoDB 7 inside Docker Compose with persistent volume*
- [x] **Initial Company Watchlist:** *20+ SEA/APAC & Remote-friendly tech companies across Greenhouse, Lever, and Ashby*
- [x] **Deployment Target:** *Docker Compose on `lixsu@mini-pc-2.fluffy-oratrice.ts.net` (`~/workspace/lixionary/lixionary-job-seeker`), ports `:3000` (UI) and `:8000` (API)*
