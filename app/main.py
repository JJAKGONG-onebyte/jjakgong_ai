"""짝공 AI 서버 (집중 감지 WebSocket).

실행: uvicorn app.main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.auth import InvalidToken, verify_token
from app.config import Settings
from app.main_server import MainServerClient
from app.session import FocusSession

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("jjakgong.ai")

CLOSE_INVALID_TOKEN = 4001


def create_app(settings: Settings | None = None, main_client: MainServerClient | None = None) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings or Settings.from_env()
        app.state.main = main_client or MainServerClient(
            app.state.settings.main_server_url, app.state.settings.internal_api_key)
        yield
        await app.state.main.aclose()

    app = FastAPI(title="짝공 AI 서버", lifespan=lifespan)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.websocket("/ws/focus")
    async def focus(ws: WebSocket):
        await ws.accept()
        try:
            claims = verify_token(ws.query_params.get("token"), app.state.settings.focus_stream_secret)
        except InvalidToken as e:
            log.info("토큰 오류로 연결 종료: %s", e)
            await ws.close(code=CLOSE_INVALID_TOKEN)
            return

        session = FocusSession(ws, claims, app.state.settings, app.state.main)
        log.info("연결 session=%s user=%s sensitivity=%s",
                 claims.session_id, claims.user_id, claims.focus_sensitivity)
        try:
            await session.start()
            while not session.closed:
                await session.handle(await ws.receive_text())
        except WebSocketDisconnect:
            pass
        finally:
            await session.on_disconnect()
            log.info("연결 종료 session=%s", claims.session_id)

    return app


app = create_app()
