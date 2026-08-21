import re
from pathlib import Path
from typing import Any

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.providers.base import ChatProvider
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import ChatData, CitationData
from app.services.retrieval_service import RetrievalService
from app.services.vector_store import VectorHit

CITATION_PATTERN = re.compile(r"\[(\d+)\]")


class RAGService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        chat_provider: ChatProvider,
        retrieval_service: RetrievalService,
    ) -> None:
        self.settings = settings
        self.chat_provider = chat_provider
        self.retrieval_service = retrieval_service
        self.conversations = ConversationRepository(db)
        self.system_prompt = Path(settings.rag_system_prompt_path).read_text(encoding="utf-8")

    def ask(
        self,
        *,
        question: str,
        conversation_id: str | None,
        document_ids: list[str] | None,
        top_k: int | None,
        score_threshold: float | None,
    ) -> ChatData:
        conversation = self._get_or_create_conversation(conversation_id, question)
        history = self.conversations.recent_messages(
            conversation.id, self.settings.conversation_history_messages
        )
        self.conversations.add_message(conversation, role="user", content=question)

        retrieval = self.retrieval_service.retrieve(
            query=question,
            document_ids=document_ids,
            top_k=top_k,
            score_threshold=score_threshold,
            conversation_id=conversation.id,
        )
        prompt = self._build_prompt(question=question, history=history, hits=retrieval.hits)
        generated = self.chat_provider.generate(
            system_instruction=self.system_prompt,
            prompt=prompt,
        )
        citations = self._extract_citations(generated.content, retrieval.hits)
        assistant_message = self.conversations.add_message(
            conversation,
            role="assistant",
            content=generated.content,
            citations=[citation.model_dump(mode="json") for citation in citations],
        )

        return ChatData(
            conversation_id=conversation.id,
            message_id=assistant_message.id,
            answer=generated.content,
            citations=citations,
            retrieval_trace_id=retrieval.trace_id,
            provider=generated.provider,
            model=generated.model,
            retrieved_chunk_count=len(retrieval.hits),
        )

    def _get_or_create_conversation(self, conversation_id: str | None, question: str):
        if conversation_id:
            conversation = self.conversations.get(conversation_id)
            if conversation is None:
                raise AppError(
                    message="Conversation not found.",
                    code="CONVERSATION_NOT_FOUND",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return conversation

        title = question.strip().replace("\n", " ")[:80]
        return self.conversations.create(title=title)

    def _build_prompt(
        self,
        *,
        question: str,
        history: list[Any],
        hits: list[VectorHit],
    ) -> str:
        history_text = (
            "\n".join(f"{message.role.upper()}: {message.content}" for message in history)
            or "No previous conversation history."
        )

        if hits:
            contexts: list[str] = []
            for index, hit in enumerate(hits, start=1):
                contexts.append(
                    "\n".join(
                        [
                            (
                                f'<document_context citation="{index}" '
                                f'document="{hit.payload.get("filename", "unknown")}" '
                                f'page="{hit.payload.get("page_number", 0)}">'
                            ),
                            str(hit.payload.get("text", "")),
                            "</document_context>",
                        ]
                    )
                )
            context_text = "\n\n".join(contexts)
        else:
            context_text = "No relevant document context was retrieved."

        return (
            f"CONVERSATION HISTORY:\n{history_text}\n\n"
            f"RETRIEVED CONTEXT:\n{context_text}\n\n"
            f"CURRENT QUESTION:\n{question}\n"
        )

    @staticmethod
    def _extract_citations(answer: str, hits: list[VectorHit]) -> list[CitationData]:
        cited_numbers: list[int] = []
        for raw in CITATION_PATTERN.findall(answer):
            number = int(raw)
            if number not in cited_numbers:
                cited_numbers.append(number)

        citations: list[CitationData] = []
        for number in cited_numbers:
            if number < 1 or number > len(hits):
                continue
            hit = hits[number - 1]
            text = str(hit.payload.get("text", ""))
            citations.append(
                CitationData(
                    citation_number=number,
                    chunk_id=hit.id,
                    document_id=str(hit.payload.get("document_id", "")),
                    filename=str(hit.payload.get("filename", "")),
                    page_number=int(hit.payload.get("page_number", 0)),
                    score=round(hit.score, 6),
                    excerpt=text[:400],
                )
            )
        return citations
