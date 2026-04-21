from langchain_core.messages import AIMessage, HumanMessage

from app.services.hubspot_service import _build_note_html


def test_note_includes_conversation_viewer_link():
    html = _build_note_html(
        {
            "session_id": "s1",
            "client_profile": {"name": "Alice"},
            "conversation_insights": {},
            "solutions_discussed": [],
            "messages": [],
            "conversation_viewer_url": "https://api.example.com/conversation/s1",
        }
    )
    assert "Full conversation transcript" in html
    assert "https://api.example.com/conversation/s1" in html


def test_note_includes_inline_plaintext_transcript():
    html = _build_note_html(
        {
            "session_id": "s1",
            "client_profile": {"name": "Alice"},
            "conversation_insights": {},
            "solutions_discussed": [],
            "messages": [
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there"),
            ],
        }
    )
    assert "Transcript (plaintext)" in html
    assert "Hello" in html
    assert "Hi there" in html
