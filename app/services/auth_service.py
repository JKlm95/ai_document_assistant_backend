from uuid import UUID

from app.core.config import Settings
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository


class AuthService:
    def __init__(self, user_repository: UserRepository, settings: Settings) -> None:
        self._user_repository = user_repository
        self._settings = settings

    async def register_user(
        self,
        *,
        email: str,
        password: str,
        full_name: str | None,
    ) -> User:
        existing_user = await self._user_repository.get_by_email(email)
        if existing_user is not None:
            raise EmailAlreadyRegisteredError

        user = await self._user_repository.create(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
        )
        await self._user_repository.commit()
        return user

    async def authenticate_user(self, *, email: str, password: str) -> User:
        user = await self._user_repository.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError
        if not user.is_active:
            raise InactiveUserError
        return user

    def create_access_token_for_user(self, user: User) -> str:
        return create_access_token(subject=user.id, settings=self._settings)

    async def get_user_from_token(self, token: str) -> User:
        try:
            user_id: UUID = decode_access_token(token, settings=self._settings)
        except InvalidTokenError as exc:
            raise InvalidCredentialsError from exc

        user = await self._user_repository.get_by_id(user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError
        return user


class EmailAlreadyRegisteredError(Exception):
    """Raised when a user tries to register an already used email address."""


class InvalidCredentialsError(Exception):
    """Raised when credentials or access token are invalid."""


class InactiveUserError(Exception):
    """Raised when an inactive user tries to authenticate."""
