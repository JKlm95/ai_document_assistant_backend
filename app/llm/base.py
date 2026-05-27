from typing import Protocol

from app.llm.models import LLMResult


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    async def generate_answer(self, *, prompt: str, question: str, context: str) -> LLMResult:
        raise NotImplementedError


class LLMProviderError(Exception):
    """Base class for LLM provider errors."""


class LLMProviderUnavailableError(LLMProviderError):
    """Raised when a configured provider cannot be used."""


class UnsupportedLLMProviderError(LLMProviderError):
    """Raised when provider registry does not support a provider key."""
