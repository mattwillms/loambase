from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str, name: str = "Test User") -> str:
    await client.post("/api/v1/auth/register", json={
        "name": name, "email": email, "password": "testpass"
    })
    login = await client.post("/api/v1/auth/login", data={
        "username": email, "password": "testpass"
    })
    return login.json()["access_token"]


async def test_get_me(client: AsyncClient):
    token = await _register_and_login(client, "getme@example.com", "Get Me User")
    res = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "getme@example.com"
    assert data["name"] == "Get Me User"
    assert "id" in data
    assert "role" in data


async def test_patch_me_name(client: AsyncClient):
    token = await _register_and_login(client, "patchme@example.com", "Original Name")
    res = await client.patch(
        "/api/v1/users/me",
        json={"name": "New Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "New Name"
    assert data["email"] == "patchme@example.com"


async def test_patch_me_timezone_and_zip(client: AsyncClient):
    token = await _register_and_login(client, "patchtz@example.com")
    res = await client.patch(
        "/api/v1/users/me",
        json={"timezone": "America/Chicago", "zip_code": "60601"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["timezone"] == "America/Chicago"
    assert data["zip_code"] == "60601"


async def test_patch_me_partial_update_preserves_other_fields(client: AsyncClient):
    token = await _register_and_login(client, "partial@example.com", "Partial User")
    # Set timezone first
    await client.patch(
        "/api/v1/users/me",
        json={"timezone": "America/Denver"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Patch only name — timezone should be unchanged
    res = await client.patch(
        "/api/v1/users/me",
        json={"name": "Updated Partial"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Updated Partial"
    assert data["timezone"] == "America/Denver"


async def test_get_me_unauthenticated(client: AsyncClient):
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401


async def test_patch_me_unauthenticated(client: AsyncClient):
    res = await client.patch("/api/v1/users/me", json={"name": "Hacker"})
    assert res.status_code == 401
