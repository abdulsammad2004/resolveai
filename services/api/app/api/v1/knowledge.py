import logging
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.ai.embeddings import EmbeddingClient, EmbeddingError, get_embedding_client
from app.core.deps import CurrentPrincipal, TenantDB
from app.modules.knowledge.retrieval import retrieve
from app.modules.knowledge.schemas import SearchRequest, SearchResponse, SearchResult

logger = logging.getLogger("app.api.knowledge")

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_embedder() -> EmbeddingClient:
    try:
        return get_embedding_client()
    except RuntimeError as exc:
        logger.error("Search unavailable: embedding client is not configured")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Search is not configured on this server"
        ) from exc


EmbedderDep = Annotated[EmbeddingClient, Depends(get_embedder)]


@router.post("/search", response_model=SearchResponse)
async def search_knowledge(
    body: SearchRequest, principal: CurrentPrincipal, db: TenantDB, embedder: EmbedderDep
) -> SearchResponse:
    """Semantic search over the workspace's ready documents. Any member may search."""
    try:
        result = await retrieve(
            db, body.query, workspace_id=principal.workspace_id, embedder=embedder
        )
    except EmbeddingError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Search is temporarily unavailable. Try again."
        ) from exc
    return SearchResponse(
        results=[SearchResult(**asdict(c)) for c in result.chunks],
        query_tokens=result.query_tokens,
    )
