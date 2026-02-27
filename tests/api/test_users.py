from httpx import AsyncClient


async def _register_and_login(
    client: AsyncClient,
    email: str,
    first_name: str = "Test",
    last_name: str | None = "User",
) -> str:
    payload: dict = {"first_name": first_name, "email": email, "password": "testpass"}
    if last_name is not None:
        payload["last_name"] = last_name
    await client.post("/api/v1/auth/register", json=payload)
    login = await client.post("/api/v1/auth/login", data={
        "username": email, "password": "testpass"
    })
    return login.json()["access_token"]


async def test_get_me(client: AsyncClient):
    token = await _register_and_login(client, "getme@example.com", "Get", "Me")
    res = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "getme@example.com"
    assert data["first_name"] == "Get"
    assert data["last_name"] == "Me"
    assert "id" in data
    assert "role" in data


async def test_patch_me_name(client: AsyncClient):
    token = await _register_and_login(client, "patchme@example.com", "Original", "Name")
    res = await client.patch(
        "/api/v1/users/me",
        json={"first_name": "New", "last_name": "Name"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["first_name"] == "New"
    assert data["last_name"] == "Name"
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
    token = await _register_and_login(client, "partial@example.com", "Partial", "User")
    # Set timezone first
    await client.patch(
        "/api/v1/users/me",
        json={"timezone": "America/Denver"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Patch only first_name — timezone should be unchanged
    res = await client.patch(
        "/api/v1/users/me",
        json={"first_name": "Updated"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["first_name"] == "Updated"
    assert data["timezone"] == "America/Denver"


async def test_get_me_unauthenticated(client: AsyncClient):
    res = await client.get("/api/v1/users/me")
    assert res.status_code == 401


async def test_patch_me_unauthenticated(client: AsyncClient):
    res = await client.patch("/api/v1/users/me", json={"first_name": "Hacker"})
    assert res.status_code == 401
