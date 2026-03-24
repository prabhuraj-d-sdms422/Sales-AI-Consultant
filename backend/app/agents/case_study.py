"""
DORMANT IN V1. Returns graceful fallback only.
Phase 2: Activated when Store 2 (Project Delivery DB) is populated.
"""

from app.models.state import ConversationState


async def case_study_node(state: ConversationState) -> dict:
    fallback_response = (
        "We have delivered solutions like this across multiple clients and industries. "
        "Let me walk you through exactly what we would build for your specific situation."
    )
    return {
        "current_response": fallback_response,
        "current_agent": "case_study",
        "should_stream": True,
    }
