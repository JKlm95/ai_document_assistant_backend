from uuid import UUID

from app.models.project import Project
from app.repositories.project_repository import ProjectRepository


class ProjectService:
    def __init__(self, project_repository: ProjectRepository) -> None:
        self._project_repository = project_repository

    async def create_project(
        self,
        *,
        user_id: UUID,
        name: str,
        description: str | None,
    ) -> Project:
        existing_project = await self._project_repository.get_by_user_and_name(
            user_id=user_id,
            name=name,
        )
        if existing_project is not None:
            raise ProjectNameAlreadyExistsError

        project = await self._project_repository.create(
            user_id=user_id,
            name=name,
            description=description,
        )
        await self._project_repository.commit()
        await self._project_repository.refresh(project)
        return project

    async def list_projects(
        self,
        *,
        user_id: UUID,
        limit: int,
        offset: int,
    ) -> tuple[list[Project], int]:
        projects = await self._project_repository.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
        )
        total = await self._project_repository.count_for_user(user_id=user_id)
        return projects, total

    async def get_project(self, *, project_id: UUID, user_id: UUID) -> Project:
        project = await self._project_repository.get_by_id(project_id)
        self._ensure_project_access(project=project, user_id=user_id)
        if project is None or project.is_archived:
            raise ProjectNotFoundError
        return project

    async def update_project(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        name: str | None,
        description: str | None,
        description_set: bool,
    ) -> Project:
        project = await self.get_project(project_id=project_id, user_id=user_id)

        if name is not None and name != project.name:
            existing_project = await self._project_repository.get_by_user_and_name(
                user_id=user_id,
                name=name,
            )
            if existing_project is not None:
                raise ProjectNameAlreadyExistsError
            project.name = name

        if description_set:
            project.description = description

        await self._project_repository.commit()
        await self._project_repository.refresh(project)
        return project

    async def archive_project(self, *, project_id: UUID, user_id: UUID) -> None:
        project = await self.get_project(project_id=project_id, user_id=user_id)
        project.is_archived = True
        await self._project_repository.commit()

    @staticmethod
    def _ensure_project_access(project: Project | None, user_id: UUID) -> None:
        if project is None:
            raise ProjectNotFoundError
        if project.user_id != user_id:
            raise ProjectAccessDeniedError


class ProjectNotFoundError(Exception):
    """Raised when a project does not exist or is archived."""


class ProjectAccessDeniedError(Exception):
    """Raised when a user tries to access another user's project."""


class ProjectNameAlreadyExistsError(Exception):
    """Raised when a user tries to reuse a project name."""
