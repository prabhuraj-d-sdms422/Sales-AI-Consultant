"""
Vector DB abstraction — built in V1, NOT called by any agent.
Phase 2: Solution Advisor and Case Study Agent will call get_vector_db().
"""

from typing import Protocol

from app.config.settings import settings


class VectorDBClient(Protocol):
    async def upsert(self, vectors: list[dict]) -> None: ...

    async def query(
        self, vector: list[float], top_k: int, filter: dict | None = None
    ) -> list[dict]: ...

    async def delete(self, ids: list[str]) -> None: ...


async def get_vector_db() -> VectorDBClient:
    """Phase 2 only. Not called in V1."""
    if settings.vector_db_provider == "pinecone":
        from app.config._pinecone_client import PineconeClient

        return await PineconeClient.create()
    if settings.vector_db_provider == "pgvector":
        from app.config._pgvector_client import PgVectorClient

        return await PgVectorClient.create()
    raise ValueError(f"Unsupported vector DB: {settings.vector_db_provider}")
