from abc import ABC, abstractmethod

from app.models.state import ConversationState


class BaseAgent(ABC):
    """Abstract base for LangGraph agent nodes."""

    name: str = "base"

    @abstractmethod
    async def run(self, state: ConversationState) -> dict:
        """Return partial state updates only."""
