from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from starlette.datastructures import FormData

from app.config import get_settings
from app.storage.artifacts import ArtifactStore
from app.storage.metadata import CallMetadata
from app.telephony.media_stream import MediaStreamSessionRegistry

settings = get_settings()
artifact_store = ArtifactStore(settings.artifacts_root)
session_registry = MediaStreamSessionRegistry(settings, artifact_store)

router = APIRouter()


def _form_string(form: FormData, key: str) -> str | None:
    value = form.get(key)
    return value if isinstance(value, str) and value else None


def _terminal_call_status(status: str | None) -> bool:
    return status in {"completed", "busy", "failed", "no-answer", "canceled"}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post(settings.twilio_status_callback_path)
async def status_callback(request: Request) -> Response:
    form = await request.form()
    call_id = request.query_params.get("call_id")
    if call_id:
        path = artifact_store.paths_for(call_id).metadata_json
        if path.exists():
            metadata = CallMetadata.model_validate_json(path.read_text(encoding="utf-8"))
            call_status = _form_string(form, "CallStatus") or metadata.call_status
            updated = metadata.model_copy(
                update={
                    "provider": "twilio",
                    "is_real_call": True,
                    "provider_call_id": _form_string(form, "CallSid") or metadata.provider_call_id,
                    "call_status": call_status,
                    "duration_seconds": float(call_duration)
                    if (call_duration := _form_string(form, "CallDuration")) is not None
                    else metadata.duration_seconds,
                    "end_time": datetime.now(UTC) if _terminal_call_status(call_status) else metadata.end_time,
                }
            )
            artifact_store.write_metadata(updated)
    return Response(status_code=204)


@router.post(settings.twilio_recording_callback_path)
async def recording_callback(request: Request) -> Response:
    form = await request.form()
    call_id = request.query_params.get("call_id")
    if call_id:
        path = artifact_store.paths_for(call_id).metadata_json
        if path.exists():
            metadata = CallMetadata.model_validate_json(path.read_text(encoding="utf-8"))
            recording_status = _form_string(form, "RecordingStatus") or metadata.provider_recording_status
            problems = list(metadata.problems)
            if recording_status in {"absent", "failed"}:
                problems.append(f"Provider recording callback reported status={recording_status}.")
            updated = metadata.model_copy(
                update={
                    "provider": "twilio",
                    "is_real_call": True,
                    "provider_call_id": _form_string(form, "CallSid") or metadata.provider_call_id,
                    "provider_recording_id": _form_string(form, "RecordingSid") or metadata.provider_recording_id,
                    "provider_recording_status": recording_status,
                    "provider_recording_channels": _form_string(form, "RecordingChannels") or metadata.provider_recording_channels,
                    "provider_recording_source": _form_string(form, "RecordingSource") or metadata.provider_recording_source,
                    "provider_recording_url": _form_string(form, "RecordingUrl") or metadata.provider_recording_url,
                    "provider_recording_duration_seconds": float(recording_duration)
                    if (recording_duration := _form_string(form, "RecordingDuration")) is not None
                    else metadata.provider_recording_duration_seconds,
                    "recording_download_status": (
                        "ready_to_fetch"
                        if recording_status == "completed"
                        else "failed"
                        if recording_status in {"absent", "failed"}
                        else metadata.recording_download_status
                    ),
                    "problems": problems,
                }
            )
            artifact_store.write_metadata(updated)
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
