from __future__ import annotations

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.telephony.media_stream import MediaStreamSessionRegistry

settings = get_settings()
artifact_store = ArtifactStore(settings.artifacts_root)
session_registry = MediaStreamSessionRegistry(settings, artifact_store)

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(settings.twilio_status_callback_path)
async def status_callback(request: Request) -> Response:
    _ = await request.form()
    return Response(status_code=204)


@router.post(settings.twilio_recording_callback_path)
async def recording_callback(request: Request) -> Response:
    _ = await request.form()
    return Response(status_code=204)


@router.websocket(settings.twilio_media_ws_path)
async def media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    call_id = websocket.query_params.get("call_id")
    scenario_id = websocket.query_params.get("scenario_id")
    if not call_id or not scenario_id:
        await websocket.close(code=1008)
        return

    session = session_registry.get_or_create(call_id, scenario_id)
    try:
        while True:
            message = await websocket.receive_text()
            await session.handle_message(websocket, message)
    except WebSocketDisconnect:
        session_registry.finalize(call_id)

