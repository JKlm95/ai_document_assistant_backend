from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResult:
    answer: str
    provider: str
    model: str
    confidence: float | None = None
