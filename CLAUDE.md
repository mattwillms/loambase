# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LoamBase is the FastAPI backend for LoamUI (frontend) and Mimus (admin panel). Stack: FastAPI + PostgreSQL (asyncpg) + Redis + ARQ. Everything runs in Docker.

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

`app/worker.py` defines ARQ cron jobs: weather sync (every 3h), hardiness zone refresh (daily), plant DB sync from Perenual (weekly). The worker runs as a separate Docker service (`loambase-worker`). Job functions are stubs pending implementation.

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
