from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: UUID, name: str, description: str | None) -> Project:
        project = Project(user_id=user_id, name=name, description=description)
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def get_by_id(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_by_user_and_name(self, *, user_id: UUID, name: str) -> Project | None:
        result = await self._session.execute(
            select(Project).where(Project.user_id == user_id, Project.name == name)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, *, user_id: UUID, limit: int, offset: int) -> list[Project]:
        result = await self._session.execute(
            select(Project)
            .where(Project.user_id == user_id, Project.is_archived.is_(False))
            .order_by(Project.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def count_for_user(self, *, user_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(Project)
            .where(Project.user_id == user_id, Project.is_archived.is_(False))
        )
        return result.scalar_one()

    async def commit(self) -> None:
        await self._session.commit()

    async def refresh(self, project: Project) -> None:
        await self._session.refresh(project)
