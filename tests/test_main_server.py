import asyncio

import httpx

from app import main_server
from app.main_server import MainServerClient
from tests.helpers import CAL


def client_with(handler):
    http = httpx.AsyncClient(base_url="http://main", transport=httpx.MockTransport(handler))
    return MainServerClient("http://main", "secret-key", http)


def test_이벤트_기록은_키_헤더를_붙이고_5xx면_재시도한다(monkeypatch):
    monkeypatch.setattr(main_server, "RETRY_DELAYS", (0.0, 0.0, 0.0))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(500 if len(calls) < 3 else 201, json={"success": True})

    ok = asyncio.run(client_with(handler).record_event(301, {"eventType": "AWAY"}))
    assert ok and len(calls) == 3
    assert calls[0].url.path == "/internal/study-sessions/301/focus-events"
    assert calls[0].headers["X-Internal-Api-Key"] == "secret-key"


def test_4xx는_재시도하지_않는다(monkeypatch):
    monkeypatch.setattr(main_server, "RETRY_DELAYS", (0.0, 0.0, 0.0))
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(409, json={"success": False})

    assert asyncio.run(client_with(handler).record_event(301, {})) is False
    assert len(calls) == 1


def test_기준값_조회_성공과_없음():
    def found(request):
        return httpx.Response(200, json={"success": True, "data": {
            "screenView": CAL.screen.to_dict(), "materialView": None}})

    cal = asyncio.run(client_with(found).get_calibration(301))
    assert cal.screen == CAL.screen and cal.material is None
    assert asyncio.run(client_with(lambda r: httpx.Response(404)).get_calibration(301)) is None
