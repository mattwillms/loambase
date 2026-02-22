# LoamBase API

Backend service for LoamUI and Mimus. FastAPI + PostgreSQL + Redis + ARQ.

## Setup

```bash
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, SECRET_KEY, PERENUAL_API_KEY
```

Generate a strong secret key:
```bash
openssl rand -hex 32
```

## Run

```bash
docker-compose up -d
```

## Migrations

```bash
# Generate initial migration (first time)
docker exec loambase-api alembic revision --autogenerate -m "initial schema"

# Apply migrations
docker exec loambase-api alembic upgrade head

# Rollback one
docker exec loambase-api alembic downgrade -1
```

## Tests

Tests run against a dedicated `loambase_test` database. Create it first:
```bash
docker exec postgres psql -U loambase -c "CREATE DATABASE loambase_test;"
```

Then:
```bash
docker exec loambase-api pytest --cov=app --cov-report=term-missing
```

## API Docs

- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Project Structure

```
app/
  api/v1/endpoints/   # Route handlers
  core/               # Config, security, deps
  db/                 # Session, base
  models/             # SQLAlchemy models
  schemas/            # Pydantic schemas
  services/           # Business logic / DB ops
  tasks/              # ARQ task functions (placeholder)
  worker.py           # ARQ worker entrypoint
  main.py             # FastAPI app
alembic/              # DB migrations
tests/
  api/                # Endpoint tests
  unit/               # Logic unit tests
  integration/        # External API mocking tests
```
