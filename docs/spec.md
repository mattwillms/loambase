# Loam — Garden & Flowerbed Management Platform

## Spec Sheet v1.7

---

## 0. Branding & Identity

### Product Names

| Service | Name | Domain |
|---|---|---|
| Backend API | **LoamBase** | garden.willms.co/api |
| Garden Frontend | **LoamUI** | garden.willms.co |
| Admin / Ops Dashboard | **Mimus** | mimus.io / control.willms.co |

### Name Origins

**Loam** — Named after Natchez Silt Loam, the official state soil of Mississippi. Loam is the ideal garden soil: balanced, fertile, alive. The name grounds the product in place.

**Mimus** — The genus name of the Northern Mockingbird (*Mimus polyglottos*), Mississippi's state bird. The mockingbird watches everything, mimics and reflects the state of its environment back — a natural metaphor for a monitoring and ops dashboard.

### Logo Direction

**LoamBase / LoamUI (shared mark):**
- Wordmark: "loam" in lowercase, earthy serif or organic sans
- Icon concept: a cross-section of soil layers (dark topsoil over lighter subsoil) — simple, geometric, recognizable at small sizes
- Color palette: warm earth tones — deep soil brown, moss green, off-white cream
- Secondary mark: a single seedling emerging from a soil line

**Mimus:**
- Wordmark: "mimus" in lowercase, clean modern sans
- Icon concept: a mockingbird silhouette — sleek profile with the distinctive white wing flash, minimal and geometric
- The bird should feel watchful, sharp, alert — not decorative
- Color palette: cool contrast to Loam — slate, charcoal, white flash accent
- The white wing bar of the mockingbird is a strong graphic element to carry into UI accents

### Design Principles
- Loam and Mimus should feel like they come from the same hand but serve different moods — Loam is warm and organic, Mimus is precise and cool
- Both wordmarks lowercase — approachable, modern
- Mississippi-rooted without being kitschy

---

## 1. Project Overview

**Project Name:** LoamUI (frontend), LoamBase (backend/API), Mimus (admin panel)

**Purpose:** Personal garden and flowerbed management platform with intelligent recommendations based on location, weather, soil, and plant data. Designed for self-hosting on a Synology NAS via Docker.

**Users:** Personal use + a few family members (< 10 users).

**Architecture:** Three decoupled services sharing one API layer. LoamBase is the single source of truth for garden data. LoamUI (garden management UI) and Mimus (general-purpose admin/analytics panel) are both consumers of the LoamBase API. Mimus is designed to be expandable beyond garden management — it's your central ops dashboard. Future API consumers could include a mobile app, Home Assistant integration, CLI tool, or notification bot.

---

## 2. Architecture & Tech Stack

### Backend — LoamBase API

| Layer | Technology | Rationale |
|---|---|---|
| Framework | **FastAPI** (Python) | Async, auto-generated OpenAPI docs, type-safe, lightweight. |
| Database | **PostgreSQL 16** | Relational data (plants, schedules, zones). Mature, great JSON support. |
| ORM | **SQLAlchemy 2.0 + Alembic** | Migrations, async support, well-documented. |
| Cache | **Redis** | Weather/API response caching, rate-limit buckets, task queues. |
| Task Queue | **ARQ** (async) | Scheduled jobs: weather polling, notification dispatch, recommendation refresh, plant seeding. |
| Auth | **JWT tokens** (via `python-jose`) | Stateless auth. Simple for <10 users. Optional: basic OIDC if you want SSO later. |
| AI/Recommendations | **Claude API** or local rules engine | For natural language Q&A ("When should I plant tomatoes?"), with fallback to deterministic rules. |
| Containerization | **Docker + Docker Compose** | One `docker-compose.yml` to spin up API, DB, Redis, worker, and frontend. |

### Frontend — LoamUI

| Layer | Technology | Rationale |
|---|---|---|
| Framework | **React 18+** (Vite) | Component-based, massive ecosystem, works well with REST APIs. |
| UI Library | **Tailwind CSS + shadcn/ui** | Clean, modern look without heavy design work. |
| State | **TanStack Query (React Query)** | Server state management, caching, auto-refetch. |
| Router | **React Router v7** | Standard SPA routing. |
| Charts | **Recharts** | Watering history, temperature trends, growth tracking. |
| PWA | **Vite PWA plugin** | Installable on phone home screen, offline basic access. |

### Admin Panel — Mimus

Separate React app. Its own subdomain (`control.willms.co`), its own container. Designed to be a general-purpose self-hosted ops dashboard — garden/LoamBase is the first module, but the architecture supports plugging in monitoring for other self-hosted services later (e.g., other Docker apps on the NAS, domain health, backup status). Admin-only access enforced by role-based JWT claims.

| Layer | Technology | Rationale |
|---|---|---|
| Framework | **React 18+** (Vite) | Same stack as LoamUI — shared component library possible later. |
| UI Library | **Tailwind CSS + shadcn/ui** | Consistent look across both apps. |
| Charts/Viz | **Recharts + Tremor** | Tremor is built on top of Tailwind and designed specifically for dashboards/analytics. |
| Data Tables | **TanStack Table** | Sortable, filterable, paginated tables for logs, users, schedules. |
| State | **TanStack Query** | Same pattern as LoamUI. |

#### Mimus Features

**System Health Dashboard**
- API uptime, response times, error rates
- Background worker status (ARQ queue depth, failed jobs, last run times)
- Database size and connection pool stats
- Redis memory usage and cache hit rates
- External API status (Open-Meteo, Perenual, phzmapi — are they responding?)
- Docker container resource usage (CPU, RAM per service)

**User Management**
- User list with activity stats (last login, total plantings, gardens)
- Create/edit/disable accounts
- Role management (admin vs. regular user)
- Session/token management

**Data Pipeline Monitor**
- Weather data freshness (last poll, next poll, cache age)
- Plant database sync status (last Perenual pull, records synced, failures, current page)
- Hardiness zone data status
- Scheduled task execution log (ran, skipped, failed, duration)

**Garden Analytics (Aggregate)**
- Total gardens, beds, plantings across all users
- Most planted species
- Active vs. dormant plantings
- Planting timeline (what's going in / coming out by month)
- Watering compliance (scheduled vs. actually logged)
- Treatment application history (frequency, products used, conditions)
- Harvest yield summaries (if tracking enabled)

**Weather Analytics**
- Historical weather cache viewer (temp, precip, humidity over time for your location)
- Weather-triggered action log (how many watering schedules were auto-adjusted, frost alerts sent)
- Seasonal trend charts

**Recommendation Engine Stats**
- Recommendations generated vs. acted on
- Most common recommendation types
- Alert history (frost warnings, heat advisories, spray timing)

**Notification Audit**
- Notification delivery log (sent, delivered, failed)
- Notification type breakdown (water, fertilize, frost alert, etc.)
- Per-user notification preferences overview

**Logs & Diagnostics**
- Application log viewer (filterable by level, service, timestamp)
- API request log (endpoint, user, status code, latency)
- Error log with stack traces
- Audit trail (who changed what, when)

**Data Management**
- Plant database browser/editor (view, override, flag bad data)
- Bulk import/export tools (CSV, JSON)
- Database backup trigger and restore interface
- Cache flush controls

### Perenual Plant Seeder

The plant database is seeded from the Perenual API via an ARQ background task. Key details:

- **Task:** `app/tasks/seed_plants.py` — runs daily at 04:00 via ARQ cron
- **Client:** `app/services/perenual.py` — async, reads `PERENUAL_API_KEY` from `.env`
- **Email notifications:** `app/services/email.py` — async sender via `aiosmtplib`, STARTTLS on port 587, Gmail SMTP. Reads `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` from `.env`. Never crashes the caller — exceptions caught and logged.
- **Progress tracking:** `SeederRun` model (`app/models/logs.py`) stores `current_page`, `total_pages`, `records_synced`, `requests_used`, `status`, timestamps, and `error_message`
- **Strategy: list-then-detail** — fetch one species list page (1 request), then immediately fetch full detail for each of the 30 species on that page (30 requests), upsert fully-populated records, commit, advance to next page. Every plant in the DB is complete — no NULLs from skipped detail fetches.
- **Backfill phase:** Before paginating new pages each run, the seeder checks for existing plants where `source="perenual" AND water_needs IS NULL` and fetches their detail first. Counts against daily budget.
- **Budget cap:** `_REQUEST_BUDGET = 95` — checked before every API call. Stops cleanly when reached, commits partial page progress.
- **Resume-safe:** Resumes from `current_page + 1` of last failed run. Skips entirely if last run is `complete` or currently `running`.
- **Deduplication:** Upserts by `(source="perenual", external_id=str(perenual_id))` — no duplicates possible.
- **Free tier math:** 95 req/day → 1 list + 30 detail = 31 req/page → ~3 fully-populated pages/day → ~33 days to seed 3,000 species.
- **Completion detection:** After reaching the last page, backfill runs one final time. If it completes without hitting the budget and no NULL records remain, `SeederRun` marked `complete` — future invocations skip silently with no API calls or email.
- **Quota retry:** If first request of run returns 429 (quota not reset), sends "Quota Not Reset" email and enqueues a one-off retry for 05:00 via ARQ.
- **Manual trigger:** `docker exec loambase-loambase-api-1 python run_seeder.py`
- **Known fix:** `image_url` field is `Text` (not `String(500)`) — Perenual S3 URLs exceed 500 chars.

**Email notifications sent:**

| Event | Subject |
|---|---|
| Daily budget reached | "LoamBase Seeder — Daily Run Complete" |
| Quota not reset at 04:00 | "LoamBase Seeder — Quota Not Reset" |
| Unexpected error | "LoamBase Seeder — Error" |
| All species seeded | "LoamBase Seeder Complete" |

**Current seeder state (as of this session):** ~48 plants in DB, resuming from page 3 tomorrow. Seeder is functional and will complete autonomously.

### Infrastructure (Synology NAS)

| Component | Details |
|---|---|
| Host | **Synology DS918+** — Intel Celeron J3455 (4-core, 1.5GHz), 8GB RAM |
| Storage | 4-bay: 3.6TB + 1.8TB + 3.6TB + 3.6TB — Volume 1: 8.7TB total, 4.5TB free (48% used) |
| Domain | `willms.co` — `garden.willms.co` (frontend + API), `control.willms.co` (admin) |
| Tunnel | Cloudflare Tunnel (already configured for existing services on willms.co) |
| SSL | Handled by Cloudflare |
| Backups | Synology Hyper Backup — schedule nightly DB dumps to a separate volume |
| Monitoring | **Uptime Kuma** (lightweight, self-hosted) |

**SSD Recommendation:** The DS918+ has two M.2 NVMe slots on the bottom — configurable as SSD read/write cache for Volume 1 through DSM's Storage Manager. Even a single cheap NVMe (128-256GB) would meaningfully accelerate Postgres I/O. Start without it, add later if performance is a concern.

### Docker Compose Services

```
services:
  loambase-api       # FastAPI app (port 8000) — container: loambase-loambase-api-1
  loambase-worker    # ARQ background tasks — container: loambase-loambase-worker-1
  postgres           # Database
  redis              # Cache + message broker
  loamui-web         # React frontend (nginx serving static build)
  mimus-web          # React admin panel (nginx serving static build)
  nginx-proxy        # Reverse proxy + SSL termination (if not using Synology's)
```

**Routing (Cloudflare Tunnel):**
```
garden.willms.co        → loamui-web
garden.willms.co/api    → loambase-api (path-based, no CORS issues)
control.willms.co       → mimus-web
```

**Note on container naming:** Docker Compose prefixes containers with the project directory name. With the repo in `~/dev/loambase`, containers are named `loambase-loambase-api-1`, `loambase-loambase-worker-1`, etc. Always use these full names with `docker exec`.

### Repository & Development Environment

- **GitHub:** [mattwillms/loambase](https://github.com/mattwillms/loambase)
- **Local dev path:** `~/dev/loambase` (EndeavourOS Linux)
- **Primary editor:** Claude Code (direct file editing in the repo)
- **API testing:** Swagger UI (auto-generated by FastAPI)
- **Migrations:** Alembic — run inside the container: `docker exec loambase-loambase-api-1 alembic upgrade head`
- **Seeder (manual):** `docker exec loambase-loambase-api-1 python run_seeder.py`
- **Scripts location:** `~/dev/loambase/scripts/` (local) — must be copied into container or mounted to run inside Docker

**Important:** Scripts in `~/dev/loambase/scripts/` are not automatically available inside the container. Either copy with `docker cp` or ensure the scripts directory is mounted in `docker-compose.yml`.

### Deployment Flow
1. Clone repo to Synology (or build images on dev machine, push to local registry)
2. `docker-compose up -d`
3. Run Alembic migrations: `docker exec loambase-loambase-api-1 alembic upgrade head`
4. Seed plant database: `docker exec loambase-loambase-api-1 python run_seeder.py` (runs daily after that)
5. Add `garden.willms.co` and `control.willms.co` to Cloudflare Tunnel config

### DNS & Access
- Add CNAME records in Cloudflare: `garden` and `control` on `willms.co`
- Add both as public hostnames in your Cloudflare Tunnel config
- `garden.willms.co` → nginx-proxy → loamui-web + loambase-api (path-based)
- `control.willms.co` → nginx-proxy → mimus-web
- SSL handled by Cloudflare edge
- `arda.willms.co` (DSM) remains unexposed — internal only

### Backup Strategy
- **Database:** `pg_dump` cron job → Synology shared folder → Hyper Backup to cloud
- **Uploads (photos):** Docker volume → Synology shared folder → Hyper Backup
- **Config:** `docker-compose.yml` + `.env` in a git repo

---

## 3. Data Model (Core Entities)

### User
- id, name, email, hashed_password, timezone, zip_code, hardiness_zone, lat/lon

### Garden
- id, user_id, name, description, square_footage, sun_exposure (full/partial/shade), soil_type, irrigation_type

### Bed (Flowerbed / Raised Bed / Plot)
- id, garden_id, name, dimensions, sun_exposure_override, soil_amendments, notes

### Plant (Master Plant Data — from external sources + user additions)
- id, common_name, scientific_name, plant_type (annual/perennial/shrub/tree/herb/vegetable)
- hardiness_zones[], sun_requirement, water_needs (low/medium/high)
- days_to_maturity, spacing_inches, planting_depth_inches
- companion_plants[], antagonist_plants[]
- fertilizer_needs, common_pests[], common_diseases[]
- bloom_season, harvest_window
- source (perenual / trefle / usda / user-defined)
- external_id (str) — Perenual species ID or equivalent; unique constraint with source
- image_url (Text — not String, Perenual S3 URLs exceed 500 chars)

### Planting (Instance of a plant in a bed)
- id, bed_id, plant_id, date_planted, date_transplanted, quantity
- status (planned / seedling / growing / flowering / fruiting / harvesting / dormant / removed)
- notes, photos[]

### Schedule (Unified schedule engine)
- id, planting_id (or bed_id or garden_id), schedule_type (water / fertilize / spray / prune / harvest)
- frequency, next_due, last_completed, notes
- auto_adjusted (boolean — was this modified by weather logic?)

### WateringGroup
- id, garden_id, name, plantings[] (group plants with similar water needs)
- schedule_id

### TreatmentLog
- id, planting_id or bed_id, date, type (herbicide / insecticide / fungicide / fertilizer / amendment)
- product_name, amount, notes, weather_at_time

### WeatherCache
- id, lat, lon, date, high_temp, low_temp, humidity, precip_inches, wind_mph, conditions
- uv_index, soil_temp (if available), frost_warning (boolean)

### JournalEntry
- id, user_id, garden_id, date, text, photos[], tags[]

### AuditLog
- id, user_id, action (create / update / delete / login / export), entity_type, entity_id
- timestamp, ip_address, details (JSON — what changed)

### PipelineRun
- id, pipeline_name (weather_sync / plant_sync / zone_lookup / recommendation_refresh)
- status (running / success / failed / skipped), started_at, finished_at, duration_ms
- records_processed, error_message

### ApiRequestLog
- id, timestamp, method, endpoint, user_id, status_code, latency_ms, ip_address

### NotificationLog
- id, user_id, type (water / fertilize / frost / heat / spray / harvest / custom)
- channel (push / email / ntfy), status (sent / delivered / failed)
- timestamp, message_preview

### SeederRun *(added this session)*
- id, status (running / complete / failed)
- current_page, total_pages
- records_synced, requests_used
- started_at, finished_at, error_message
- Table: `seeder_runs`

---

## 4. External Data Sources & APIs

### Plant Data

| Source | What It Provides | Cost | Notes |
|---|---|---|---|
| **Perenual API** | 10,000+ species, care guides, hardiness maps, disease info, images | Free tier: 100 req/day, species 1–3000. Premium: $49.99/mo for 10K/day, 10K+ species | In use. Free tier sufficient to seed 3,000 species over ~3 days. |
| **Trefle API** | 400K+ species, taxonomic data, growth/distribution info | Free, open source | Good for botanical reference. Less care-guide oriented. Phase 2+ consideration. |
| **USDA PLANTS Database** | US native/naturalized plants, traits, distributions | Free (no official REST API) | Authoritative for native species data. Phase 3+ consideration. |
| **Permapeople API** | Permaculture-focused plant data, companion planting | Free, CC BY-SA 4.0 | Great for companion planting and guild data. Phase 3+ consideration. |

**Strategy:** Seed local LoamBase database from Perenual on initial setup (automated, resume-safe). Cache locally. Refresh periodically. Users can add/override plant data. Not dependent on any single API long-term.

### Weather

| Source | What It Provides | Cost | Notes |
|---|---|---|---|
| **Open-Meteo** | Current + 16-day forecast, hourly resolution, historical data | **Free, no API key needed** | Top pick. No signup friction. Accurate. |
| **OpenWeatherMap** | Current, forecast, historical, alerts | Free tier: 1,000 calls/day | Good fallback. |
| **Visual Crossing** | Current, forecast, 50+ years historical | Free tier: 1,000 calls/day | Strongest historical data. |

**Strategy:** Use Open-Meteo as primary. Cache aggressively in Redis (poll every 2-4 hours). Store daily summaries in WeatherCache for historical tracking.

### Hardiness Zone

| Source | Details |
|---|---|
| **phzmapi.org** | Free static JSON API — lookup by ZIP code. Returns zone + temp range. |
| **Perenual** | Also includes hardiness maps per species. |

### Soil Data

| Source | Details |
|---|---|
| **USDA Soil Data Access (SSURGO)** | Free web services. Query by lat/lon for soil type, drainage class, pH, organic matter. |

---

## 5. Core Features

### 5.1 Garden Setup & Profile
- Define gardens with location (auto-detect or manual ZIP)
- Auto-lookup hardiness zone, frost dates, soil type from location
- Define beds within gardens (dimensions, orientation, sun exposure)
- Support multiple gardens (front yard, back yard, community plot)

### 5.2 Plant Library & Search
- Searchable plant database with filters (zone-compatible, sun, water needs, type)
- Per-plant detail pages: care guide, companion info, pest/disease reference, images
- "Will it grow here?" indicator based on user's zone + conditions
- User-added plants with custom care data

### 5.3 Planting Management
- Add plantings to beds with date tracking
- Growth stage tracking with status transitions
- Photo journal per planting (upload + timestamp)
- Harvest tracking (date, yield estimate)

### 5.4 Watering System
- Per-plant recommended watering schedule (pulled from plant data)
- Watering groups — cluster plants with similar needs into shared schedules
- Weather-adjusted watering — if rain >= 0.25" in next 24h, suppress or delay reminder
- Manual watering log
- Weekly water summary view

### 5.5 Fertilizer Management
- Per-plant fertilizer recommendations (type, NPK ratio, frequency)
- Calendar-based fertilizer schedule
- Application log with product, amount, date
- Soil test result input → adjusted recommendations

### 5.6 Pest, Disease & Treatment Management
- Common pest/disease lookup per plant
- Treatment schedule (preventive sprays, organic options highlighted)
- Application log with weather conditions at time of application
- "Don't spray before rain" warnings from weather integration

### 5.7 Smart Recommendations Engine
- Planting time windows based on zone
- Companion planting suggestions
- Weather alerts (frost, heat)
- Seasonal task lists
- Watering adjustments from precipitation forecast
- Treatment timing based on soil temps

### 5.8 Calendar & Dashboard
- Unified calendar view: water, fertilize, spray, plant, harvest
- Today's tasks dashboard
- Upcoming week view
- Overdue task alerts

### 5.9 Notifications
- Push notifications via PWA or email
- Configurable: daily digest vs. real-time alerts
- Frost alerts, watering reminders, task due dates

### 5.10 Journal / Garden Log
- Free-form notes with date, tags, and photo attachments
- Tied to specific garden, bed, or planting
- Searchable history

---

## 6. Additional Feature Ideas (Future / Phase 2+)

| Feature | Value |
|---|---|
| **Garden Layout Designer** | Drag-and-drop bed planner with grid spacing guides |
| **Plant Identification** | Camera upload → AI identification |
| **Seed Inventory** | Track what seeds you have, expiration, source |
| **Harvest Tracker** | Log yields per plant, compare year-over-year |
| **Crop Rotation Planner** | Track what was planted where by year, suggest rotations |
| **Moon Phase Gardening** | Optional lunar calendar integration |
| **Home Assistant Integration** | Expose garden data as sensors |
| **Shared Family View** | Family members see their own tasks/notifications |
| **Export / Reports** | End-of-season summary, yearly comparison, PDF export |
| **Soil Moisture Sensors** | MQTT integration with ESP32 sensors |
| **Cost Tracking** | Track spending on seeds, soil, treatments, tools |
| **Native Mobile App** | React Native or Capacitor wrapper around the PWA |

---

## 7. API Design (LoamBase)

RESTful, versioned, OpenAPI-documented.

### Base URL
```
https://garden.willms.co/api/v1/
```

### Core Endpoints (abbreviated)

```
# Auth
POST   /auth/login
POST   /auth/register
POST   /auth/refresh

# Users
GET    /users/me
PATCH  /users/me

# Gardens
GET    /gardens
POST   /gardens
GET    /gardens/{id}
PATCH  /gardens/{id}
DELETE /gardens/{id}

# Beds
GET    /gardens/{id}/beds
POST   /gardens/{id}/beds
GET    /beds/{id}
PATCH  /beds/{id}

# Plants (library)
GET    /plants?search=&zone=&type=&sun=
GET    /plants/{id}
POST   /plants               (user-defined)

# Plantings
GET    /beds/{id}/plantings
POST   /beds/{id}/plantings
PATCH  /plantings/{id}
POST   /plantings/{id}/photos

# Schedules
GET    /schedules?type=&due_before=
POST   /schedules
PATCH  /schedules/{id}
POST   /schedules/{id}/complete

# Watering Groups
GET    /gardens/{id}/watering-groups
POST   /gardens/{id}/watering-groups

# Treatments
GET    /treatments?planting_id=&type=
POST   /treatments

# Weather
GET    /weather/current
GET    /weather/forecast
GET    /weather/history?start=&end=

# Recommendations
GET    /recommendations/planting-window?plant_id=
GET    /recommendations/companions?plant_id=
GET    /recommendations/tasks
GET    /recommendations/alerts

# Journal
GET    /journal?garden_id=&tag=
POST   /journal

# ———— Admin endpoints (Mimus) ————
# Requires admin role JWT

GET    /admin/health
GET    /admin/health/external
GET    /admin/metrics
GET    /admin/users
GET    /admin/users/{id}
PATCH  /admin/users/{id}
DELETE /admin/users/{id}
GET    /admin/pipelines
GET    /admin/pipelines/{id}/history
POST   /admin/pipelines/{id}/trigger
GET    /admin/analytics/gardens
GET    /admin/analytics/plantings
GET    /admin/analytics/schedules
GET    /admin/analytics/treatments
GET    /admin/analytics/weather
GET    /admin/analytics/recommendations
GET    /admin/notifications/log
GET    /admin/notifications/stats
GET    /admin/logs?level=&service=&since=
GET    /admin/audit?user_id=&action=&since=
GET    /admin/plants/browse
PATCH  /admin/plants/{id}
POST   /admin/data/export
POST   /admin/data/import
POST   /admin/backup/trigger
POST   /admin/cache/flush
```

### API Design Principles
- All responses use consistent envelope: `{ "data": ..., "meta": { "page": 1, "total": 50 } }`
- Pagination via `?page=&per_page=`
- Filtering via query params
- Versioned: `/api/v1/`
- OpenAPI spec auto-generated by FastAPI

---

## 8. Infrastructure & Deployment

### Synology Resource Budget (DS918+)

| Service | Est. RAM | Est. CPU | Notes |
|---|---|---|---|
| PostgreSQL | ~256-512MB | Low-medium | Biggest beneficiary of SSD cache |
| Redis | ~50-100MB | Minimal | Lightweight for this use case |
| LoamBase API | ~150-256MB | Low | FastAPI is lean |
| LoamBase Worker | ~128-256MB | Spiky | Peaks during weather sync / seeder runs |
| LoamUI (nginx) | ~20MB | Minimal | Static file serving |
| Mimus (nginx) | ~20MB | Minimal | Static file serving |
| **Total estimated** | **~1-1.5GB** | | Leaves 6.5GB+ for DSM and other containers |

The J3455 will handle this fine — it's not doing heavy computation, just API serving and periodic background jobs. The spinning drives are the main bottleneck. If you add an SSD later, mount the Postgres data directory on it.

---

## 9. Testing Strategy

### Backend (LoamBase) — pytest

| Layer | What to Test | Tools |
|---|---|---|
| **Unit tests** | Individual functions: recommendation logic, weather parsing, schedule calculations, seeder resume logic | `pytest` + `pytest-asyncio` |
| **API tests** | Every endpoint: request validation, response shape, auth enforcement, error handling, pagination | `pytest` + `httpx` |
| **Database tests** | Model relationships, migrations, constraint enforcement, seed data integrity | `pytest` + test database |
| **Integration tests** | External API mocking (Open-Meteo, Perenual, phzmapi), full request → DB → response flows | `pytest` + `respx` |
| **Task tests** | Background jobs: weather sync, notification dispatch, plant seeder | `pytest` + ARQ test helpers |

### Frontend (LoamUI + Mimus) — Vitest

| Layer | What to Test | Tools |
|---|---|---|
| **Component tests** | Individual React components render correctly, handle props/state | `Vitest` + `React Testing Library` |
| **Hook tests** | Custom hooks return expected data | `Vitest` + `renderHook` |
| **Integration tests** | Full page flows | `Vitest` + MSW |
| **E2E tests (Phase 3+)** | Critical user paths through actual browser | `Playwright` |

### Test Infrastructure

```bash
# Run all backend tests
docker exec loambase-loambase-api-1 pytest --cov=app --cov-report=term-missing

# Run frontend tests
docker exec loamui-web npm run test
docker exec mimus-web npm run test

# Run E2E (when implemented)
npx playwright test
```

**Test database:** Dedicated `loambase_test` Postgres database, created/torn down per test session.

### Coverage Targets

| Service | Target | Notes |
|---|---|---|
| LoamBase API | **80%+** | Focus on recommendation engine, schedule logic, seeder, and auth. |
| LoamUI | **60%+** | Component tests for anything with logic. |
| Mimus | **50%+** | Dashboard widgets and data transformations. |

---

## 10. Development Phases

### Phase 1 — Foundation (MVP)
- [x] Backend scaffold: FastAPI + Postgres + Redis + Docker Compose
- [x] All 14 database models defined (SQLAlchemy ORM)
- [x] Alembic migrations (initial schema)
- [x] Auth endpoints: register, login, JWT access/refresh tokens, admin role
- [x] Gardens CRUD
- [x] Beds CRUD
- [x] Perenual API client (`app/services/perenual.py`)
- [x] SeederRun model + migration
- [x] Plant seeder ARQ task (`app/tasks/seed_plants.py`) — resume-safe, daily cron at 04:00
- [x] `scripts/run_seeder.py` manual trigger
- [ ] Plant search + detail endpoints ← **next**
- [ ] Planting CRUD with status tracking
- [ ] Frontend (LoamUI): Dashboard, garden/bed views, plant search
- [ ] Basic weather integration (Open-Meteo, cached)
- [ ] Hardiness zone auto-lookup
- [ ] **Mimus MVP**: System health dashboard (API/DB/Redis/worker status), user list

### Phase 2 — Scheduling & Intelligence
- [ ] Watering schedules + watering groups
- [ ] Fertilizer schedules
- [ ] Treatment logging
- [ ] Weather-adjusted watering recommendations
- [ ] Calendar view
- [ ] Notifications (email or push)
- [ ] Frost/heat alerts
- [ ] **Mimus**: Data pipeline monitor, notification log, weather analytics

### Phase 3 — Polish & Expansion
- [ ] Garden journal with photos
- [ ] Companion planting recommendations
- [ ] Seasonal task auto-generation
- [ ] Soil data integration (SSURGO)
- [ ] PWA setup (installable)
- [ ] Family member accounts
- [ ] **Mimus**: Garden analytics (aggregate stats, planting trends, compliance), audit trail, API request log viewer

### Phase 4 — Advanced
- [ ] Garden layout designer
- [ ] Harvest tracking + yield history
- [ ] Crop rotation tracking
- [ ] Home Assistant integration
- [ ] AI-powered Q&A ("What's wrong with my squash?")
- [ ] Sensor integration (ESP32 + MQTT)
- [ ] **Mimus**: Recommendation engine stats, data management tools, plant DB editor, external API status monitor

---

## 11. Key Design Decisions

| Decision | Choice | Notes |
|---|---|---|
| **Primary plant data source** | Perenual (free tier) | Seeding 3,000 species over ~3 days. Supplement with Trefle later for coverage. |
| **Weather provider** | Open-Meteo | Free, no key, accurate. |
| **System notifications** | Gmail SMTP + aiosmtplib | In use for seeder status emails. App Password configured. ntfy.sh/Gotify still planned for user-facing garden notifications (Phase 2). |
| **Frontend framework** | React | Largest ecosystem. |
| **Database** | PostgreSQL | Proper relational, JSON support, scales fine. |
| **Auth approach** | JWT | Simple for <10 users. Add Authelia later if SSO needed. |
| **Expose NAS to internet** | Cloudflare Tunnel | Already in use for willms.co. DSM (arda) stays internal-only. |
| **Task queue** | ARQ | Async, lightweight. Celery references in earlier notes are outdated — ARQ is in use. |

---

## 12. Mississippi Zone 8a/8b Specifics

Since you're in Madison County, MS (Zone 8a/8b, ~32.4°N):

- **Growing season:** ~240 days (mid-March through mid-November)
- **Last spring frost:** ~March 10-20
- **First fall frost:** ~November 10-20
- **Key challenges:** Summer heat/humidity (fungal pressure), clay soil, fire ants, Japanese beetles, armyworms
- **Soil:** Likely Loring or Memphis silt loam series (SSURGO can confirm for your exact parcel)
- **Default recommendations should account for:** high humidity fungicide schedules, deep summer watering needs, cool-season veggie windows (fall planting is huge in Zone 8)

The app should pre-populate these defaults when you enter your ZIP code during setup.

---

## 13. Session Notes & Decisions Log

| Date | Decision / Change |
|---|---|
| Sessions 1–4 | Phase 1 backend foundation complete (see phase checklist) |
| 2026-02-23 | Signed up for Perenual free tier (Personal plan — 100 req/day, species 1–3000) |
| 2026-02-23 | Built and validated plant seeder end-to-end. 5 bugs found and fixed by Claude Code during live run. |
| 2026-02-23 | `image_url` field changed from `String(500)` to `Text` — Perenual S3 URLs are 800+ chars |
| 2026-02-23 | Confirmed ARQ (not Celery) is the task queue in use — all Celery references removed from spec |
| 2026-02-23 | Scripts in `~/dev/loambase/scripts/` are not auto-mounted in containers — use `docker cp` or add mount in compose |
| 2026-02-23 | Container naming pattern confirmed: `loambase-loambase-api-1`, `loambase-loambase-worker-1` |
| 2026-02-23 | After `.env` changes, always restart both: `docker-compose restart loambase-worker loambase-api` |
| 2026-02-23 | Seeder strategy changed from list-only to **list-then-detail** — fully populates each plant before moving to next page. ~33 days to seed 3,000 species on free tier. |
| 2026-02-23 | Added backfill phase — existing plants with NULL fields get detail fetched first on each run |
| 2026-02-23 | Email notifications added via Gmail SMTP + aiosmtplib (`app/services/email.py`) |
| 2026-02-23 | Quota retry logic added — if 429 on first request, sends email and enqueues retry at 05:00 |
| 2026-02-23 | Completion detection added — seeder marks itself complete and stops permanently when all species seeded and no NULLs remain |
| 2026-02-23 | DBeaver connected to local Postgres on localhost:5432, DB: loambase |
| 2026-02-23 | Containers currently running on dev machine (EndeavourOS). NAS deployment pending — consider moving once seeder completes or sooner for 24/7 reliability |

---

*This spec is a living document. Iterate as you build.*
