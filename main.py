"""
Standalone proxy server: receives audio from the SpeakEasy app and forwards
it to Speechmatics' Real-time ASR API for transcription.

FastAPI port of the original Express/Node backend. Same public contract:
POST /api/transcribe with a multipart 'audio' file + 'language' field,
returns { "text": "..." }.
"""

import os
import logging

from dotenv import load_dotenv
from fastapi import FastAPI

from routes.transcribe import router as transcribe_router

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("speechmatics-backend")

app = FastAPI(title="Speechmatics transcription server")


@app.get("/")
async def health_check():
    """Simple health check so you can confirm the server is up from a browser."""
    return {"status": "ok", "message": "Speechmatics transcription server is running"}


app.include_router(transcribe_router)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 3000))
    logger.info(f"Speechmatics backend running on port {port}")
    logger.info(f"Health check: http://localhost:{port}/")
    logger.info(f"Transcribe endpoint: http://localhost:{port}/api/transcribe")
    uvicorn.run("main:app", host="0.0.0.0", port=port)
