"""
Receives recorded audio from the app (Flutter recordings, or a shared
WhatsApp voice note) and forwards it to Speechmatics' REAL-TIME ASR API
over a WebSocket. Single streaming session: open socket -> stream the file
straight in -> read back the final transcript as it's produced.

The public contract is unchanged: POST /api/transcribe with a multipart
'audio' file + 'language' field, returns { "text": "..." }.
"""

import asyncio
import json
import logging
import os

import websockets
from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

logger = logging.getLogger("speechmatics-backend")

router = APIRouter()

# 25 MB covers even long WhatsApp voice notes comfortably.
MAX_FILE_SIZE = 25 * 1024 * 1024

# Real-time endpoints live on a different host to the Batch ones
# (eu2.rt.speechmatics.com / us2.rt.speechmatics.com), not the
# asr.api.speechmatics.com hosts used for Batch jobs. Override with
# SPEECHMATICS_RT_HOST in your .env if you're on the US contract
# (us2.rt.speechmatics.com) or want to pin a specific region.
SPEECHMATICS_RT_HOST = os.environ.get("SPEECHMATICS_RT_HOST", "eu2.rt.speechmatics.com")
RT_URL = f"wss://{SPEECHMATICS_RT_HOST}/v2"

# 'enhanced' is Speechmatics' most accurate model - noticeably better than
# 'standard' for Urdu specifically (harder language, more benefit from the
# bigger model). Override with SPEECHMATICS_OPERATING_POINT=standard in
# your .env if you want to trade some accuracy back for raw speed.
OPERATING_POINT = os.environ.get("SPEECHMATICS_OPERATING_POINT", "enhanced")

# How long Speechmatics waits after a word ends before finalizing it. Using
# the maximum (4s) in 'flexible' mode gives the model the most context to
# get words, punctuation, and smart formatting right. Override with
# SPEECHMATICS_MAX_DELAY in your .env (0.7-4, lower = faster/less accurate).
MAX_DELAY = float(os.environ.get("SPEECHMATICS_MAX_DELAY", 4))

# How big a slice of the file we send per AddAudio message.
CHUNK_SIZE = 16 * 1024

# Safety net: if Speechmatics never finishes (bad network, stuck session),
# don't hang the request forever.
SESSION_TIMEOUT_S = 30


async def transcribe_realtime(file_bytes: bytes, language: str | None) -> str:
    api_key = os.environ.get("SPEECHMATICS_API_KEY")
    final_chunks: list[str] = []
    sent_chunks = 0
    offset = 0

    async def run() -> str:
        nonlocal offset, sent_chunks

        async with websockets.connect(
            RT_URL,
            additional_headers={"Authorization": f"Bearer {api_key}"},
            max_size=None,
        ) as ws:

            async def send_next_chunk():
                nonlocal offset, sent_chunks
                if offset >= len(file_bytes):
                    # Every AddAudio has been sent and acked - tell the
                    # server we're done.
                    await ws.send(json.dumps({"message": "EndOfStream", "last_seq_no": sent_chunks}))
                    return
                chunk = file_bytes[offset:offset + CHUNK_SIZE]
                offset += len(chunk)
                sent_chunks += 1
                await ws.send(chunk)

            await ws.send(json.dumps({
                "message": "StartRecognition",
                "audio_format": {"type": "file"},
                "transcription_config": {
                    "language": language or "ur",
                    "operating_point": OPERATING_POINT,
                    "enable_partials": False,
                    "max_delay": MAX_DELAY,
                    "max_delay_mode": "flexible",
                },
            }))

            async for raw in ws:
                if isinstance(raw, (bytes, bytearray)):
                    continue  # server never sends binary back, but be safe
                try:
                    data = json.loads(raw)
                except ValueError:
                    continue  # ignore anything that isn't JSON

                msg = data.get("message")

                if msg == "RecognitionStarted":
                    # Kick off streaming; server acks each chunk with
                    # AudioAdded, which drives send_next_chunk - this keeps
                    # us from ever flooding the socket faster than the
                    # server can read.
                    await send_next_chunk()
                elif msg == "AudioAdded":
                    await send_next_chunk()
                elif msg == "AddTranscript":
                    metadata = data.get("metadata") or {}
                    transcript = metadata.get("transcript")
                    if transcript:
                        final_chunks.append(transcript)
                elif msg == "EndOfTranscript":
                    return " ".join(final_chunks).strip()
                elif msg == "Error":
                    raise RuntimeError(
                        f"Speechmatics real-time error ({data.get('type')}): {data.get('reason')}"
                    )
                # Info / Warning messages are safe to ignore.

            # Socket closed without EndOfTranscript.
            raise RuntimeError("Speechmatics WebSocket closed before finishing")

    try:
        return await asyncio.wait_for(run(), timeout=SESSION_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise RuntimeError("Speechmatics real-time session timed out")
    except websockets.exceptions.WebSocketException as exc:
        raise RuntimeError(f"Speechmatics WebSocket error: {exc}")


@router.post("/api/transcribe")
async def transcribe(audio: UploadFile | None = None, language: str = Form(default=None)):
    if audio is None:
        raise HTTPException(status_code=400, detail="No audio file received")

    file_bytes = await audio.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Audio file too large (max 25 MB)")

    logger.info(f"[transcribe] received file: {audio.filename}, size: {len(file_bytes)} bytes")
    logger.info(f"[transcribe] streaming to Speechmatics real-time ({RT_URL})")

    try:
        text = await transcribe_realtime(file_bytes, language)
        return {"text": text}
    except Exception as exc:
        logger.error(f"Transcription error: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})
