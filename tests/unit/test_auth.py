from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_auth_service
from app.core.config import Settings
from app.main import create_app
from app.models.user import User
from app.services.auth_service import AuthService


class InMemoryUserRepository:
    def __init__(self) -> None:
        self.users_by_id: dict[UUID, User] = {}
        self.users_by_email: dict[str, User] = {}

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.users_by_id.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def create(self, *, email: str, hashed_password: str, full_name: str | None) -> User:
        user = User(email=email, hashed_password=hashed_password, full_name=full_name)
        user.id = uuid4()
        user.is_active = True
        self.users_by_id[user.id] = user
        self.users_by_email[user.email] = user
        return user

    async def commit(self) -> None:
        return None


@pytest.fixture
def auth_client() -> TestClient:
    app = create_app()
    user_repository = InMemoryUserRepository()
    settings = Settings(jwt_secret="test-jwt-secret", access_token_expire_minutes=5)

    def override_auth_service() -> AuthService:
        return AuthService(user_repository=user_repository, settings=settings)  # type: ignore[arg-type]

    app.dependency_overrides[get_auth_service] = override_auth_service

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_register_creates_user(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "USER@example.com",
            "password": "strong-password",
            "full_name": "Test User",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "user@example.com"
    assert response.json()["full_name"] == "Test User"
    assert "hashed_password" not in response.json()


def test_register_rejects_duplicate_email(auth_client: TestClient) -> None:
    payload = {
        "email": "user@example.com",
        "password": "strong-password",
        "full_name": "Test User",
    }

    first_response = auth_client.post("/api/v1/auth/register", json=payload)
    second_response = auth_client.post("/api/v1/auth/register", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_login_and_me_return_authenticated_user(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "strong-password",
            "full_name": "Test User",
        },
    )

    login_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "strong-password"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    assert login_response.json()["token_type"] == "bearer"

    me_response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"


def test_login_rejects_invalid_credentials(auth_client: TestClient) -> None:
    auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": "user@example.com",
            "password": "strong-password",
            "full_name": "Test User",
        },
    )

    wrong_password_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )
    unknown_email_response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )

    assert wrong_password_response.status_code == 401
    assert unknown_email_response.status_code == 401
    assert wrong_password_response.json()["detail"] == "Invalid email or password"
    assert unknown_email_response.json()["detail"] == "Invalid email or password"


def test_me_requires_bearer_token(auth_client: TestClient) -> None:
    response = auth_client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_me_rejects_invalid_token(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid-token"},
    )

    assert response.status_code == 401
