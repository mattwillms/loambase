from httpx import AsyncClient


async def test_register(client: AsyncClient):
    res = await client.post("/api/v1/auth/register", json={
        "first_name": "Test",
        "last_name": "User",
        "email": "test@example.com",
        "password": "securepassword",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "test@example.com"
    assert data["first_name"] == "Test"
    assert data["last_name"] == "User"
    assert data["role"] == "user"


async def test_register_duplicate_email(client: AsyncClient):
    payload = {"first_name": "Alice", "email": "alice@example.com", "password": "pw123"}
    await client.post("/api/v1/auth/register", json=payload)
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 400


async def test_login(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "first_name": "Bob", "email": "bob@example.com", "password": "testpass"
    })
    res = await client.post("/api/v1/auth/login", data={
        "username": "bob@example.com", "password": "testpass"
    })
    assert res.status_code == 200
    tokens = res.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens


async def test_login_wrong_password(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "first_name": "Carol", "email": "carol@example.com", "password": "correct"
    })
    res = await client.post("/api/v1/auth/login", data={
        "username": "carol@example.com", "password": "wrong"
    })
    assert res.status_code == 401


async def test_me(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "first_name": "Dave", "email": "dave@example.com", "password": "pw"
    })
    login = await client.post("/api/v1/auth/login", data={
        "username": "dave@example.com", "password": "pw"
    })
    token = login.json()["access_token"]
    res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["email"] == "dave@example.com"


async def test_refresh(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "first_name": "Eve", "email": "eve@example.com", "password": "pw"
    })
    login = await client.post("/api/v1/auth/login", data={
        "username": "eve@example.com", "password": "pw"
    })
    refresh_token = login.json()["refresh_token"]
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    assert "access_token" in res.json()
