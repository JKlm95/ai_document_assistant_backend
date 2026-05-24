from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Header, HTTPException, status
from fastapi.testclient import TestClient
from httpx import Response

from app.api.deps import get_current_user, get_project_service
from app.main import create_app
from app.models.project import Project
from app.models.user import User
from app.services.project_service import ProjectService


class InMemoryProjectRepository:
    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}

    async def create(self, *, user_id: UUID, name: str, description: str | None) -> Project:
        now = datetime.now(UTC)
        project = Project(user_id=user_id, name=name, description=description)
        project.id = uuid4()
        project.is_archived = False
        project.created_at = now
        project.updated_at = now
        self.projects[project.id] = project
        return project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return self.projects.get(project_id)

    async def get_by_user_and_name(self, *, user_id: UUID, name: str) -> Project | None:
        return next(
            (
                project
                for project in self.projects.values()
                if project.user_id == user_id and project.name == name
            ),
            None,
        )

    async def list_for_user(self, *, user_id: UUID, limit: int, offset: int) -> list[Project]:
        projects = [
            project
            for project in self.projects.values()
            if project.user_id == user_id and not project.is_archived
        ]
        projects.sort(key=lambda project: project.updated_at, reverse=True)
        return projects[offset : offset + limit]

    async def count_for_user(self, *, user_id: UUID) -> int:
        return len(
            [
                project
                for project in self.projects.values()
                if project.user_id == user_id and not project.is_archived
            ]
        )

    async def commit(self) -> None:
        for project in self.projects.values():
            if project.is_archived:
                project.updated_at = datetime.now(UTC)

    async def refresh(self, project: Project) -> None:
        project.updated_at = datetime.now(UTC)


@pytest.fixture
def projects_client() -> Iterator[TestClient]:
    app = create_app()
    project_repository = InMemoryProjectRepository()
    project_service = ProjectService(project_repository=project_repository)  # type: ignore[arg-type]
    users = {
        "user-one": _build_user(email="one@example.com"),
        "user-two": _build_user(email="two@example.com"),
    }

    async def override_current_user(
        authorization: Annotated[str | None, Header()] = None,
    ) -> User:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        token = authorization.removeprefix("Bearer ")
        user = users.get(token)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return user

    def override_project_service() -> ProjectService:
        return project_service

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_project_service] = override_project_service

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_create_list_get_update_delete_project(projects_client: TestClient) -> None:
    create_response = _create_project(projects_client, name="Research")
    project_id = create_response.json()["id"]

    list_response = projects_client.get("/api/v1/projects", headers=_auth_headers())
    get_response = projects_client.get(f"/api/v1/projects/{project_id}", headers=_auth_headers())
    update_response = projects_client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Updated Research", "description": "Updated description"},
        headers=_auth_headers(),
    )
    delete_response = projects_client.delete(
        f"/api/v1/projects/{project_id}",
        headers=_auth_headers(),
    )
    get_archived_response = projects_client.get(
        f"/api/v1/projects/{project_id}",
        headers=_auth_headers(),
    )

    assert create_response.status_code == 201
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert get_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Updated Research"
    assert delete_response.status_code == 204
    assert get_archived_response.status_code == 404


def test_projects_require_auth(projects_client: TestClient) -> None:
    response = projects_client.get("/api/v1/projects")

    assert response.status_code == 401


def test_user_cannot_access_foreign_project(projects_client: TestClient) -> None:
    create_response = _create_project(projects_client, name="Foreign", token="user-two")
    project_id = create_response.json()["id"]

    get_response = projects_client.get(f"/api/v1/projects/{project_id}", headers=_auth_headers())
    update_response = projects_client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Hacked"},
        headers=_auth_headers(),
    )
    delete_response = projects_client.delete(
        f"/api/v1/projects/{project_id}",
        headers=_auth_headers(),
    )

    assert get_response.status_code == 403
    assert update_response.status_code == 403
    assert delete_response.status_code == 403


def test_projects_pagination(projects_client: TestClient) -> None:
    _create_project(projects_client, name="Project 1")
    _create_project(projects_client, name="Project 2")
    _create_project(projects_client, name="Project 3")

    response = projects_client.get("/api/v1/projects?limit=2&offset=1", headers=_auth_headers())

    assert response.status_code == 200
    assert response.json()["limit"] == 2
    assert response.json()["offset"] == 1
    assert response.json()["total"] == 3
    assert len(response.json()["items"]) == 2


def test_archived_projects_are_hidden_by_default(projects_client: TestClient) -> None:
    create_response = _create_project(projects_client, name="Archive me")
    project_id = create_response.json()["id"]

    delete_response = projects_client.delete(
        f"/api/v1/projects/{project_id}",
        headers=_auth_headers(),
    )
    list_response = projects_client.get("/api/v1/projects", headers=_auth_headers())

    assert delete_response.status_code == 204
    assert list_response.status_code == 200
    assert list_response.json()["items"] == []
    assert list_response.json()["total"] == 0


def _build_user(*, email: str) -> User:
    user = User(email=email, hashed_password="not-used")
    user.id = uuid4()
    user.is_active = True
    return user


def _auth_headers(token: str = "user-one") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_project(
    client: TestClient,
    *,
    name: str,
    token: str = "user-one",
) -> Response:
    return client.post(
        "/api/v1/projects",
        json={"name": name, "description": f"{name} description"},
        headers=_auth_headers(token),
    )
