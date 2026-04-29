"""Voice WebSocket route — proxies browser audio to Deepgram Nova-3.

Mirrors `Public/InsightXpert/backend/src/insightxpert/voice/routes.py` but
adapted to this repo's auth model: signed session cookie via SessionSigner
(not JWT). The FE hook at `apps/web/src/hooks/use-voice-input.ts` opens a
plain WebSocket and relies on the session cookie traveling with the
handshake — it does NOT pass a `?token=` param like the public repo's hook
does, so the cookie-only path is the only one we accept.

Closes with code:
    4001  not authenticated
    4002  speech-to-text not configured (no DEEPGRAM_API_KEY)
    1011  Deepgram upstream connection failed
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth.session import SessionSigner
from ..config import get_settings

logger = logging.getLogger("insightxpert.voice")

router = APIRouter(prefix="/api", tags=["voice"])

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"


def _authenticate_ws(websocket: WebSocket) -> str | None:
    """Resolve the caller via the signed session cookie.

    Falls back to a `?token=` query param to match the public-repo hook
    shape — harmless additional surface, same signing scheme.
    """
    settings = get_settings()
    token = websocket.cookies.get(settings.session_cookie_name)
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        return None
    claims = SessionSigner(settings).verify(token)
    if claims is None:
        return None
    return claims.user_id


@router.websocket("/transcribe")
async def transcribe(websocket: WebSocket) -> None:
    import websockets

    await websocket.accept()

    user_id = _authenticate_ws(websocket)
    if not user_id:
        logger.warning("voice ws rejected: not authenticated")
        await websocket.close(code=4001, reason="Not authenticated")
        return

    settings = get_settings()
    if not settings.deepgram_api_key:
        logger.warning("voice ws rejected: deepgram_api_key not configured")
        await websocket.close(code=4002, reason="Speech-to-text is not configured")
        return

    # Browser sends WebM/opus containers. Don't pass encoding/sample_rate —
    # Deepgram detects from container headers. (Documented gotcha in the
    # public-repo route this is mirrored from.)
    params = urlencode({
        "model": "nova-3",
        "language": "en",
        "punctuate": "true",
        "interim_results": "true",
        "utterance_end_ms": "1000",
        "smart_format": "true",
    })
    dg_url = f"{DEEPGRAM_WS_URL}?{params}"
    dg_headers = {"Authorization": f"Token {settings.deepgram_api_key}"}

    try:
        async with websockets.connect(dg_url, additional_headers=dg_headers) as dg_ws:
            logger.debug("deepgram ws connected for user_id=%s", user_id)

            async def browser_to_deepgram() -> None:
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await dg_ws.send(data)
                except WebSocketDisconnect:
                    logger.debug("voice ws: browser disconnected")
                except Exception as exc:
                    logger.warning("browser_to_deepgram error: %s", exc)

            async def deepgram_to_browser() -> None:
                try:
                    async for message in dg_ws:
                        await websocket.send_text(
                            message if isinstance(message, str) else message.decode()
                        )
                except Exception as exc:
                    logger.warning("deepgram_to_browser error: %s", exc)

            _, pending = await asyncio.wait(
                [
                    asyncio.create_task(browser_to_deepgram()),
                    asyncio.create_task(deepgram_to_browser()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            logger.debug("voice session ended for user_id=%s", user_id)

    except Exception as e:
        logger.warning("deepgram connection failed: %s", e)
        try:
            await websocket.send_json({"error": "Voice connection failed"})
            await websocket.close(code=1011)
        except Exception:
            pass
