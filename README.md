# LoamBase

Backend API for the Loam garden management platform.

**Stack:** FastAPI · PostgreSQL · Redis · ARQ · Docker

## Quick Start

```bash
docker-compose up -d
docker exec loambase-loambase-api-1 alembic upgrade head
```

API runs at `http://localhost:8000`
Swagger UI at `http://localhost:8000/docs`

## Repos

- Frontend: [loamui](https://github.com/mattwillms/loamui)
- Admin: mimus
