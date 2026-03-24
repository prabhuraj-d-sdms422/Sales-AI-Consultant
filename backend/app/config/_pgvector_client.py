"""Phase 2 stub — not used in V1."""

from app.config.vectordb_provider import VectorDBClient


class PgVectorClient(VectorDBClient):
    @classmethod
    async def create(cls) -> "PgVectorClient":
        raise NotImplementedError("PgVectorClient is Phase 2 only")
