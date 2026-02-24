# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## On Session Start

Read `docs/spec.md` in full before doing anything else. It is the project roadmap and source of truth for what has been built, what is in progress, and what comes next.

## What this is

LoamBase is the FastAPI backend for LoamUI (frontend) and Mimus (admin panel). Stack: FastAPI + PostgreSQL (asyncpg) + Redis + ARQ. Everything runs in Docker.

## Development Workflow

This project uses a two-context workflow:

- **claude.ai (browser)** — high-level planning, gameplan formation, prompt crafting, spec updates
- **Claude Code** — implementation only, directed by prompts from the browser session

Claude Code should not make architectural decisions independently. If something is ambiguous, flag it and ask rather than assume.

**Standing rule — non-negotiable:** Every implementation session must end with both `docs/spec.md` AND `CLAUDE.md` updated to reflect what was built. A task is not complete until both files are current. This means: phase checklist updated, decisions log entries added, new gotchas recorded, background job statuses corrected.

## Commands

```bash
# Start all services (API, worker, postgres, redis)
docker-compose up -d

# Run all tests
docker exec loambase-api pytest --cov=app --cov-report=term-missing

# Run a single test file
docker exec loambase-api pytest tests/api/test_auth.py

# Run a single test
docker exec loambase-api pytest tests/api/test_auth.py::test_login

# Migrations
docker exec loambase-api alembic revision --autogenerate -m "description"
docker exec loambase-api alembic upgrade head
docker exec loambase-api alembic downgrade -1
```

First-time setup requires creating the test database:

```bash
docker exec postgres psql -U loambase -c "CREATE DATABASE loambase_test;"
```

## Known Gotchas

- Container naming: `loambase-loambase-api-1`, `loambase-loambase-worker-1` (not just `loambase-api`)
- Scripts in `~/dev/loambase/scripts/` are not mounted in containers — use `docker cp` to get them in
- After `.env` changes, restart both: `docker-compose restart loambase-worker loambase-api`
- Plant table: seeder has only completed one run. Many records have NULL fields. All plant schema fields beyond PK and name must be Optional.
- `image_url` on Plant model is `Text` type (not String) — Perenual S3 URLs exceed 500 chars
- Garden model has no lat/lon fields — weather endpoints use the garden owner's `User.latitude` / `User.longitude`. Users without location set get a 422 response.
- Open-Meteo snaps coordinates to nearest grid point — response `latitude`/`longitude` will differ slightly from the requested values
- `sync_weather` ARQ cron is fully implemented (not a stub) as of 2026-02-24
- PHZMapi returns coordinates as strings (not floats) — `ZoneCoordinates.lat`/`.lon` are `str`, not `float`
- `GET /users/me/zone` returns only the stored zone string (no metadata) — use `POST /users/me/zone/refresh` to get temperature_range and coordinates from PHZMapi

## Architecture

### Request flow

`app/main.py` → CORS middleware → HTTP logging middleware (writes `ApiRequestLog` to DB on every request) → `app/api/v1/router.py` → endpoint → service function → SQLAlchemy model

### Layers

- **Endpoints** (`app/api/v1/endpoints/`): Route handlers only. DB queries that are more than one-liners belong in services.
- **Services** (`app/services/`): Async functions taking `AsyncSession` + data, returning ORM models. No FastAPI imports.
- **Models** (`app/models/`): SQLAlchemy ORM using `Mapped`/`mapped_column` syntax. All in separate files imported by `app/models/__init__.py` for Alembic discovery.
- **Schemas** (`app/schemas/`): Pydantic v2 models for request validation and response serialization. Separate `*Create`, `*Update`, `*Read` schemas per domain.

### Auth

`app/core/deps.py` defines `CurrentUser` and `AdminUser` as `Annotated` type aliases used directly as route parameter types — no explicit `Depends()` call needed at the call site. JWTs carry a `"type"` claim (`"access"` or `"refresh"`) that is checked explicitly before trusting the token.

### Background jobs

`app/worker.py` defines ARQ cron jobs. The worker runs as a separate Docker service (`loambase-worker`).

- `sync_weather` — **implemented** (2026-02-24): runs every 3h, fetches Open-Meteo for all active users with lat/lon, caches in Redis, upserts `WeatherCache` daily records, logs result to `PipelineRun`
- `refresh_hardiness_zones` — **implemented** (2026-02-24): runs daily at 02:30, back-fills `User.hardiness_zone` for all active users who have `zip_code` but no zone, caches each zone in Redis for 30 days, logs to `PipelineRun`
- `sync_plant_database` — stub (actual seeding is handled by the separate `seed_plants` task below)
- `seed_plants` — **implemented**: daily Perenual seeder at 04:00, resume-safe (see Perenual Plant Seeder section)

### Data model hierarchy

```
User
└── Garden
    ├── Bed
    │   └── Planting (links to Plant catalog)
    │       ├── Schedule
    │       └── TreatmentLog
    └── WateringGroup

Plant (global catalog; source: perenual | trefle | usda | user)

Logs: WeatherCache, JournalEntry, AuditLog, ApiRequestLog, NotificationLog, PipelineRun
```

### External services (configured via env)

- **Perenual** (`PERENUAL_API_KEY`): Plant catalog data
- **Open-Meteo** (`OPEN_METEO_BASE_URL`): Weather data
- **PHZMapi** (`PHZMAPI_BASE_URL`): USDA hardiness zones by zip code
- **SMTP**: Email notifications (placeholder, not yet implemented)

## Testing

Tests use `pytest-asyncio` with `asyncio_mode = auto` (no `@pytest.mark.asyncio` needed). The `client` fixture in `conftest.py` wires `httpx.AsyncClient` with `ASGITransport` and overrides `get_db` to use a test session that rolls back after each test. The `setup_db` fixture is session-scoped and drops/recreates all tables.

The test DB URL is hardcoded in `tests/conftest.py`: `postgresql+asyncpg://loambase:changeme@postgres:5432/loambase_test`.

## Configuration

All settings live in `app/core/config.py` as a `pydantic-settings` `BaseSettings` class reading from `.env`. Required vars: `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `SECRET_KEY`. `ALLOWED_ORIGINS` is a comma-separated string parsed into a list via a `@property`.
