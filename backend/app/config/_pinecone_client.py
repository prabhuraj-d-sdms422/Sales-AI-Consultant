"""Phase 2 stub — not used in V1."""

from app.config.vectordb_provider import VectorDBClient


class PineconeClient(VectorDBClient):
    @classmethod
    async def create(cls) -> "PineconeClient":
        raise NotImplementedError("PineconeClient is Phase 2 only")
