# Loam — Garden & Flowerbed Management Platform

## Spec Sheet v1.5

---

## 0. Branding & Identity

### Product Names

| Service | Name | Previous Name | Domain |
|---|---|---|---|
| Backend API | **LoamBase** | LoamBase | garden.willms.co/api |
| Garden Frontend | **LoamUI** | LoamUI | garden.willms.co |
| Admin / Ops Dashboard | **Mimus** | Mimus | mimus.io / control.willms.co |

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
| Framework | **FastAPI** (Python) | Async, auto-generated OpenAPI docs, type-safe, lightweight. You know Python. |
| Database | **PostgreSQL 16** | Relational data (plants, schedules, zones). Mature, great JSON support. |
| ORM | **SQLAlchemy 2.0 + Alembic** | Migrations, async support, well-documented. |
| Cache | **Redis** | Weather/API response caching, rate-limit buckets, task queues. |
| Task Queue | **ARQ** (async) | Scheduled jobs: weather polling, notification dispatch, recommendation refresh. |
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

Separate React app. Its own subdomain (`control.willms.co`), its own container. **Designed to be a general-purpose self-hosted ops dashboard** — garden/LoamBase is the first module, but the architecture supports plugging in monitoring for other self-hosted services later (e.g., other Docker apps on the NAS, domain health, backup status). Admin-only access enforced by role-based JWT claims.

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
- Background worker status (Celery/ARQ queue depth, failed jobs, last run times)
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
- Plant database sync status (last Perenual/Trefle pull, records synced, failures)
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

### Infrastructure (Synology NAS)

| Component | Details |
|---|---|
| Host | **Synology DS918+** — Intel Celeron J3455 (4-core, 1.5GHz), 8GB RAM |
| Storage | 4-bay: 3.6TB + 1.8TB + 3.6TB + 3.6TB — Volume 1: 8.7TB total, 4.5TB free (48% used) |
| Domain | `willms.co` — `garden.willms.co` (frontend + API), `control.willms.co` (admin) |
| Tunnel | Cloudflare Tunnel (already configured for existing services on willms.co) |
| SSL | Handled by Cloudflare |
| Backups | Synology Hyper Backup — schedule nightly DB dumps to a separate volume |
| Monitoring | **Uptime Kuma** (lightweight, self-hosted) — you may already run this |

**SSD Recommendation:** Optional but worthwhile. The DS918+ has **two M.2 NVMe slots** on the bottom — you can configure these as an SSD read/write cache for Volume 1 through DSM's Storage Manager. This transparently accelerates Postgres I/O without touching your drive array. Even a single cheap NVMe (128-256GB) would make a noticeable difference on search queries and dashboard loads. Start without it, add later if performance bothers you.

### Docker Compose Services

```
services:
  loambase-api       # FastAPI app (port 8000)
  loambase-worker    # Celery/ARQ background tasks
  postgres             # Database
  redis                # Cache + message broker
  loamui-web       # React frontend (nginx serving static build)
  mimus-web    # React admin panel (nginx serving static build)
  nginx-proxy          # Reverse proxy + SSL termination (if not using Synology's)
```

**Routing (Cloudflare Tunnel):**
```
garden.willms.co                → loamui-web
garden.willms.co/api            → loambase-api  (not publicly exposed separately)
control.willms.co               → mimus-web
```

**LoamBase API exposure:** The API does not need its own subdomain. It lives behind `garden.willms.co/api` — the frontend calls it from the same origin (no CORS headaches). If you later build a mobile app or want external access, you can add `plantdb.willms.co` as a second route to the same container at that point.

**Mimus scope:** `control.willms.co` is designed as a **general-purpose admin panel** — not garden-specific. It starts with LoamBase/LoamUI monitoring, but the architecture supports adding modules for any other self-hosted services you run. Think of it as your personal ops dashboard that happens to start with garden management.

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

---

## 4. External Data Sources & APIs

### Plant Data

| Source | What It Provides | Cost | Notes |
|---|---|---|---|
| **Perenual API** | 10,000+ species, care guides, hardiness maps, disease info, images | Free tier: 100 req/day. Premium: $6/mo for 10K/day | Best all-around for a garden app. Has watering, sunlight, growth data. |
| **Trefle API** | 400K+ species, taxonomic data, growth/distribution info | Free, open source | Good for botanical reference. Less care-guide oriented. |
| **USDA PLANTS Database** | US native/naturalized plants, traits, distributions | Free (no official REST API — scrape or use community wrappers) | Authoritative for native species data. |
| **Permapeople API** | Permaculture-focused plant data, companion planting | Free, CC BY-SA 4.0 | Great for companion planting and guild data. |

**Strategy:** Seed your local LoamBase database by pulling from Perenual + Trefle on initial setup. Cache locally. Refresh periodically. Users can add/override plant data. This way you're not dependent on any single API long-term.

### Weather

| Source | What It Provides | Cost | Notes |
|---|---|---|---|
| **Open-Meteo** | Current + 16-day forecast, hourly resolution, historical data | **Free, no API key needed** for personal/non-commercial | Top pick. No signup friction. Accurate. |
| **OpenWeatherMap** | Current, forecast, historical, alerts | Free tier: 1,000 calls/day (One Call 3.0) | Good fallback. NOAA alert integration. |
| **Visual Crossing** | Current, forecast, 50+ years historical, CSV export | Free tier: 1,000 calls/day | Strongest historical data if you want trend analysis. |

**Strategy:** Use **Open-Meteo** as primary (free, no key). Cache aggressively in Redis (weather doesn't change by the minute for garden purposes). Poll every 2-4 hours. Store daily summaries in WeatherCache table for historical tracking.

### Hardiness Zone

| Source | Details |
|---|---|
| **phzmapi.org** | Free static JSON API — lookup by ZIP code. Returns zone + temp range. Based on USDA/PRISM data. |
| **Perenual** | Also includes hardiness maps per species. |

### Soil Data

| Source | Details |
|---|---|
| **USDA Soil Data Access (SSURGO)** | Free web services (WMS/WFS + REST). Query by lat/lon for soil type, drainage class, pH, organic matter. |
| **Web Soil Survey** | Interactive tool for manual lookup — useful for initial garden setup. |

### Frost Dates / Growing Season

Derive from Open-Meteo historical data, or use precomputed datasets (available from NOAA) keyed to ZIP/station. Store last-frost-spring and first-frost-fall per user location.

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
- **Watering groups** — cluster plants with similar needs into shared schedules
- **Weather-adjusted watering** — if rain >= 0.25" in the next 24h, suppress or delay watering reminder. If heat index > threshold, suggest supplemental watering.
- Manual watering log (record what you actually did)
- Weekly water summary view

### 5.5 Fertilizer Management
- Per-plant fertilizer recommendations (type, NPK ratio, frequency)
- Calendar-based fertilizer schedule
- Application log with product, amount, date
- Soil test result input → adjusted recommendations

### 5.6 Pest, Disease & Treatment Management
- Common pest/disease lookup per plant
- Treatment schedule (preventive sprays, organic options highlighted)
- Application log (herbicide, insecticide, fungicide) with weather conditions at time of application
- "Don't spray before rain" warnings from weather integration
- Product inventory tracker (optional: what's in the shed)

### 5.7 Smart Recommendations Engine
- **Planting time windows** — "Plant tomatoes between March 15 – April 15 in your zone"
- **Companion planting suggestions** — "Plant basil near your tomatoes"
- **Weather alerts** — frost warning → "Cover your peppers tonight"
- **Seasonal task lists** — auto-generated based on what's planted and the time of year
- **Watering adjustments** — real-time based on precipitation forecast
- **Treatment timing** — "Apply pre-emergent before soil temps hit 55°F"

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
| **Plant Identification** | Camera upload → AI identification (Perenual has an ID API in beta) |
| **Seed Inventory** | Track what seeds you have, expiration, source |
| **Harvest Tracker** | Log yields per plant, compare year-over-year |
| **Crop Rotation Planner** | Track what was planted where by year, suggest rotations |
| **Moon Phase Gardening** | Optional lunar calendar integration for planting timing |
| **Home Assistant Integration** | Expose garden data as sensors (e.g., "next watering due in 3 hours") |
| **Shared Family View** | Family members see their own tasks/notifications for shared gardens |
| **Export / Reports** | End-of-season summary, yearly comparison, PDF export |
| **Soil Moisture Sensors** | MQTT integration with ESP32 sensors for real-time bed moisture data |
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
GET    /recommendations/tasks          (today's smart task list)
GET    /recommendations/alerts         (frost, rain, heat)

# Journal
GET    /journal?garden_id=&tag=
POST   /journal

# ———— Admin endpoints (Mimus) ————
# Requires admin role JWT

# System Health
GET    /admin/health                  (API, DB, Redis, worker status)
GET    /admin/health/external         (Open-Meteo, Perenual, phzmapi status)
GET    /admin/metrics                 (request counts, latency, error rates)

# Users
GET    /admin/users
GET    /admin/users/{id}
PATCH  /admin/users/{id}              (edit, disable, change role)
DELETE /admin/users/{id}

# Data Pipeline
GET    /admin/pipelines               (all sync jobs: weather, plants, zones)
GET    /admin/pipelines/{id}/history  (run history with status/duration)
POST   /admin/pipelines/{id}/trigger  (force a sync now)

# Analytics
GET    /admin/analytics/gardens       (aggregate stats)
GET    /admin/analytics/plantings     (species breakdown, status distribution)
GET    /admin/analytics/schedules     (compliance, adjustments, overdue)
GET    /admin/analytics/treatments    (product usage, frequency, conditions)
GET    /admin/analytics/weather       (historical cache, trend data)
GET    /admin/analytics/recommendations (generated vs. acted on)

# Notifications
GET    /admin/notifications/log       (delivery history, filterable)
GET    /admin/notifications/stats     (type breakdown, failure rates)

# Logs
GET    /admin/logs?level=&service=&since=
GET    /admin/audit?user_id=&action=&since=

# Data Management
GET    /admin/plants/browse           (full plant DB with overrides)
PATCH  /admin/plants/{id}             (override external data)
POST   /admin/data/export             (trigger CSV/JSON export)
POST   /admin/data/import             (bulk import)
POST   /admin/backup/trigger          (pg_dump now)
POST   /admin/cache/flush             (clear Redis)
```

### API Design Principles
- All responses use consistent envelope: `{ "data": ..., "meta": { "page": 1, "total": 50 } }`
- Pagination via `?page=&per_page=`
- Filtering via query params
- Versioned: `/api/v1/` — so you can evolve without breaking consumers
- OpenAPI spec auto-generated by FastAPI — import into Postman, generate client SDKs, etc.

---

## 8. Infrastructure & Deployment

### Synology Resource Budget (DS918+)

| Service | Est. RAM | Est. CPU | Notes |
|---|---|---|---|
| PostgreSQL | ~256-512MB | Low-medium | Biggest beneficiary of SSD |
| Redis | ~50-100MB | Minimal | Lightweight for this use case |
| LoamBase API | ~150-256MB | Low | FastAPI is lean |
| LoamBase Worker | ~128-256MB | Spiky | Peaks during weather sync / recommendation refresh |
| LoamUI (nginx) | ~20MB | Minimal | Static file serving |
| Mimus (nginx) | ~20MB | Minimal | Static file serving |
| **Total estimated** | **~1-1.5GB** | | Leaves 6.5GB+ for DSM and other containers |

The J3455 will handle this fine — it's not doing heavy computation, just API serving and periodic background jobs. The spinning drives are the main bottleneck. If you add an SSD later, mount the Postgres data directory on it.

### DNS & Access
- Add CNAME records in Cloudflare: `garden` and `control` on `willms.co`
- Add both as public hostnames in your Cloudflare Tunnel config
- `garden.willms.co` → nginx-proxy → loamui-web + loambase-api (path-based)
- `control.willms.co` → nginx-proxy → mimus-web
- SSL handled by Cloudflare edge
- `arda.willms.co` (DSM) remains unexposed — internal only

### Repository

**GitHub:** [mattwillms/loambase](https://github.com/mattwillms/loambase)

Claude Code is configured as the primary development assistant.

### Deployment Flow
1. Clone repo to Synology (or build images on dev machine, push to local registry)
2. `docker-compose up -d`
3. Run Alembic migrations: `docker exec loambase-api alembic upgrade head`
4. Seed plant database from external APIs
5. Add `garden.willms.co` and `control.willms.co` to Cloudflare Tunnel config

### Backup Strategy
- **Database:** `pg_dump` cron job → Synology shared folder → Hyper Backup to cloud
- **Uploads (photos):** Docker volume → Synology shared folder → Hyper Backup
- **Config:** `docker-compose.yml` + `.env` in a git repo

---

## 9. Testing Strategy

### Backend (LoamBase) — pytest

| Layer | What to Test | Tools |
|---|---|---|
| **Unit tests** | Individual functions: recommendation logic, weather parsing, schedule calculations, watering group assignment, frost date math | `pytest` + `pytest-asyncio` |
| **API tests** | Every endpoint: request validation, response shape, auth enforcement, error handling, pagination | `pytest` + `httpx` (FastAPI's `TestClient`) |
| **Database tests** | Model relationships, migrations, constraint enforcement, seed data integrity | `pytest` + test database (Postgres in Docker) |
| **Integration tests** | External API mocking (Open-Meteo, Perenual, phzmapi), full request → DB → response flows | `pytest` + `respx` or `responses` for HTTP mocking |
| **Task tests** | Background jobs: weather sync, notification dispatch, recommendation refresh | `pytest` + Celery/ARQ test helpers |

### Frontend (LoamUI + Mimus) — Vitest

| Layer | What to Test | Tools |
|---|---|---|
| **Component tests** | Individual React components render correctly, handle props/state | `Vitest` + `React Testing Library` |
| **Hook tests** | Custom hooks (useWeather, useSchedule, etc.) return expected data | `Vitest` + `renderHook` |
| **Integration tests** | Full page flows: add a garden → add a bed → add a planting | `Vitest` + MSW (Mock Service Worker) for API mocking |
| **E2E tests (Phase 3+)** | Critical user paths through actual browser | `Playwright` |

### Test Infrastructure

```
# Run all backend tests
docker exec loambase-api pytest --cov=app --cov-report=term-missing

# Run frontend tests
docker exec loamui-web npm run test
docker exec mimus-web npm run test

# Run E2E (when implemented)
npx playwright test
```

**Test database:** Dedicated `loambase_test` Postgres database, created/torn down per test session. Never test against the real DB.

**CI pipeline (optional but recommended):** GitHub Actions or Gitea (self-hosted). On push: lint → type check → unit tests → integration tests → build Docker images. Even for a personal project, this catches regressions before you deploy to the NAS.

### Coverage Targets

| Service | Target | Notes |
|---|---|---|
| LoamBase API | **80%+** | Focus on recommendation engine, schedule logic, and auth. Not every CRUD getter needs a test. |
| LoamUI | **60%+** | Component tests for anything with logic. Pure display components can be lighter. |
| Mimus | **50%+** | Dashboard widgets and data transformations. Less critical than the API layer. |

### What to Test First (Phase 1 priorities)
- Auth flow (register, login, token refresh, admin role enforcement)
- Garden/Bed/Planting CRUD operations
- Plant search and filtering
- Weather data fetch and caching
- Hardiness zone lookup
- Schedule creation and "next due" calculations

---

## 10. Development Phases

### Phase 1 — Foundation (MVP)
- [x] Backend scaffold: FastAPI + Postgres + Redis + Docker Compose (API + worker services)
- [x] All 14 database models defined (SQLAlchemy ORM)
- [x] Alembic migrations (initial schema)
- [x] Auth endpoints: register, login, JWT access/refresh tokens, admin role
- [x] Gardens CRUD
- [x] Beds CRUD
- [ ] Plant library (seed from Perenual, basic search) ← **next**
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
- [ ] **Mimus**: Recommendation engine stats, data management tools (import/export/backup UI), plant DB editor, external API status monitor

---

## 11. Key Design Decisions to Make

| Decision | Options | Recommendation |
|---|---|---|
| **Primary plant data source** | Perenual (richest), Trefle (biggest), both | Start with Perenual free tier, supplement with Trefle for species coverage |
| **Weather provider** | Open-Meteo, OpenWeatherMap, Visual Crossing | Open-Meteo (free, no key, accurate) |
| **Notifications** | Email, PWA push, ntfy.sh, Gotify | ntfy.sh or Gotify (self-hosted, simple, works on phone) |
| **Frontend framework** | React, Vue, Svelte | React (largest ecosystem, you'll find more examples/components) |
| **Database** | PostgreSQL, SQLite, MySQL | PostgreSQL (proper relational, JSON support, scales fine for this) |
| **Auth approach** | JWT, session-based, Authelia | JWT for simplicity. Add Authelia later if you want SSO across your self-hosted apps. |
| **Expose NAS to internet** | Port forward, Cloudflare Tunnel, Tailscale | Cloudflare Tunnel (already in use for willms.co). DSM (arda) stays internal-only. |

---

## 12. Mississippi Zone 8a/8b Specifics

Since you're in Madison County, MS (Zone 8a/8b, ~32.4°N):

- **Growing season:** ~240 days (mid-March through mid-November)
- **Last spring frost:** ~March 10-20
- **First fall frost:** ~November 10-20
- **Key challenges:** Summer heat/humidity (fungal pressure), clay soil typical of the area, fire ants, Japanese beetles, armyworms
- **Soil:** Likely Loring or Memphis silt loam series (SSURGO can confirm for your exact parcel)
- **Default recommendations should account for:** high humidity fungicide schedules, deep summer watering needs, cool-season veggie windows (fall planting is huge in Zone 8)

The app should pre-populate these defaults when you enter your ZIP code during setup.

---

*This spec is a living document. Iterate as you build.*
