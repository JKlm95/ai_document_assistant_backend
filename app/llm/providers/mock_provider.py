import re

from app.llm.models import LLMResult


class MockLLMProvider:
    provider_name = "mock"

    def __init__(self, *, model_name: str) -> None:
        self.model_name = model_name

    async def generate_answer(self, *, prompt: str, question: str, context: str) -> LLMResult:
        citation = _first_citation_marker(context)
        return LLMResult(
            answer=(
                "Based on the provided documents, the retrieved context contains "
                f"information relevant to: {question}. {citation}"
            ),
            provider=self.provider_name,
            model=self.model_name,
            confidence=0.8,
        )


def _first_citation_marker(context: str) -> str:
    match = re.search(r"\[\d+\]", context)
    return match.group(0) if match else "[1]"
