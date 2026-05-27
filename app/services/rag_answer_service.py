from uuid import UUID

from app.llm.base import LLMProvider, LLMProviderError
from app.rag.models import AnswerStatus, GroundedAnswer
from app.rag.prompt_builder import PromptBuilder
from app.rag.retriever import ProjectRetriever

INSUFFICIENT_CONTEXT_ANSWER = "I could not find enough information in the provided documents."


class RagAnswerService:
    def __init__(
        self,
        *,
        project_retriever: ProjectRetriever,
        llm_provider: LLMProvider,
        prompt_builder: PromptBuilder,
    ) -> None:
        self._project_retriever = project_retriever
        self._llm_provider = llm_provider
        self._prompt_builder = prompt_builder

    async def answer_question(
        self,
        *,
        project_id: UUID,
        owner_id: UUID,
        question: str,
        retrieval_limit: int | None,
        include_context: bool,
    ) -> GroundedAnswer:
        retrieval = await self._project_retriever.search_project(
            project_id=project_id,
            owner_id=owner_id,
            query=question,
            limit=retrieval_limit,
            include_context=True,
        )

        context = retrieval.context or ""
        if not retrieval.results or not context.strip():
            return GroundedAnswer(
                answer=INSUFFICIENT_CONTEXT_ANSWER,
                project_id=project_id,
                question=question,
                citations=[],
                sources=[],
                used_context=context if include_context else None,
                confidence=None,
                status=AnswerStatus.INSUFFICIENT_CONTEXT,
            )

        prompt = self._prompt_builder.build_prompt(
            question=question,
            context=context,
            citations=retrieval.citations,
        )
        try:
            llm_result = await self._llm_provider.generate_answer(
                prompt=prompt,
                question=question,
                context=context,
            )
        except LLMProviderError:
            return GroundedAnswer(
                answer="Answer generation failed because the LLM provider is unavailable.",
                project_id=project_id,
                question=question,
                citations=retrieval.citations,
                sources=retrieval.results,
                used_context=context if include_context else None,
                confidence=None,
                status=AnswerStatus.FAILED,
            )

        return GroundedAnswer(
            answer=llm_result.answer,
            project_id=project_id,
            question=question,
            citations=retrieval.citations,
            sources=retrieval.results,
            used_context=context if include_context else None,
            confidence=llm_result.confidence,
            status=AnswerStatus.ANSWERED,
        )
