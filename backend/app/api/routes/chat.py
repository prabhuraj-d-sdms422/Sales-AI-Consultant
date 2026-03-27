import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.config.settings import settings
from app.graph.graph import conversation_graph
from app.models.schemas import ChatRequest
from app.services.conversation_archive_service import save_session_conversation
from app.services.session_service import load_state, save_state

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/message")
async def send_message(request: ChatRequest):
    state = await load_state(request.session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    logger.info(
        "CHAT | session=%s | stage=%s | msg_preview=%.60r",
        request.session_id,
        state.get("conversation_stage", "?"),
        request.message,
    )

    msgs = list(state.get("messages") or [])
    msgs.append(HumanMessage(content=request.message))
    state["messages"] = msgs

    return StreamingResponse(
        _stream_chat(state),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _stream_chat(state: dict):
    accumulated = dict(state)
    client_response_text = ""
    try:
        async for chunk in conversation_graph.astream(accumulated):
            for node_name, node_output in chunk.items():
                if not isinstance(node_output, dict):
                    continue
                accumulated.update(node_output)

                text_to_stream = None
                if node_name == "input_guardrail" and not node_output.get(
                    "input_guardrail_passed", True
                ):
                    text_to_stream = node_output.get("current_response") or ""
                elif node_name == "output_guardrail":
                    text_to_stream = node_output.get("current_response") or accumulated.get(
                        "current_response", ""
                    )

                if text_to_stream is None or not str(text_to_stream).strip():
                    continue

                client_response_text = str(text_to_stream)
                buffer: list[str] = []
                token_count = 0
                buffering = True
                for char in client_response_text:
                    if buffering:
                        buffer.append(char)
                        token_count += 1
                        if token_count >= settings.stream_token_buffer:
                            buffering = False
                            yield f"data: {json.dumps({'token': ''.join(buffer), 'type': 'token'})}\n\n"
                            buffer = []
                    else:
                        yield f"data: {json.dumps({'token': char, 'type': 'token'})}\n\n"
                    await asyncio.sleep(0)
                if buffer:
                    yield f"data: {json.dumps({'token': ''.join(buffer), 'type': 'token'})}\n\n"

        if client_response_text:
            msgs = list(accumulated.get("messages") or [])
            msgs.append(AIMessage(content=client_response_text))
            accumulated["messages"] = msgs
        await save_state(state["session_id"], accumulated)
        if settings.save_conversations_enabled:
            await save_session_conversation(
                session_id=state["session_id"],
                messages=list(accumulated.get("messages") or []),
            )
        yield f"data: {json.dumps({'type': 'done', 'session_id': state['session_id']})}\n\n"
    except Exception:
        # Log the real exception so we can debug why the model/graph failed.
        logger.exception("Chat streaming failed")
        yield f"data: {json.dumps({'type': 'error', 'message': 'Something went wrong. Please try again.'})}\n\n"
