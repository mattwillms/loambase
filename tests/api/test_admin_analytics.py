from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

from app.models.user import User


async def _create_admin_token(client: AsyncClient, db: AsyncSession, email: str) -> str:
    await client.post("/api/v1/auth/register", json={
        "first_name": "Admin", "email": email, "password": "adminpass"
    })
    await db.execute(update(User).where(User.email == email).values(role="admin"))
    await db.commit()
    login = await client.post("/api/v1/auth/login", data={
        "username": email, "password": "adminpass"
    })
    return login.json()["access_token"]


async def test_get_garden_analytics(client: AsyncClient, db: AsyncSession):
    token = await _create_admin_token(client, db, "analytics_admin@example.com")
    res = await client.get(
        "/api/v1/admin/analytics/gardens",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "totals" in data
    assert "plantings_by_status" in data
    assert "top_plants" in data
    totals = data["totals"]
    assert "users" in totals
    assert "gardens" in totals
    assert "beds" in totals
    assert "active_plantings" in totals
    assert isinstance(data["plantings_by_status"], list)
    assert isinstance(data["top_plants"], list)


async def test_get_logs(client: AsyncClient, db: AsyncSession):
    token = await _create_admin_token(client, db, "logs_admin@example.com")
    res = await client.get(
        "/api/v1/admin/logs",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert isinstance(data["items"], list)


async def test_get_audit(client: AsyncClient, db: AsyncSession):
    token = await _create_admin_token(client, db, "audit_admin@example.com")
    res = await client.get(
        "/api/v1/admin/audit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
