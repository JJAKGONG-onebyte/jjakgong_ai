import time
from datetime import timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from tests.helpers import CAL, T0, face, frames, no_face

SECRET = "test-secret-test-secret-test-secret-1234"
S = timedelta(seconds=1)


class FakeMain:
    """메인 서버 대역."""

    def __init__(self, calibration=None):
        self.calibration = calibration
        self.events = []
        self.saved = []

    async def record_event(self, session_id, payload):
        self.events.append((session_id, payload))
        return True

    async def get_calibration(self, session_id):
        return self.calibration

    async def save_calibration(self, session_id, calibration, sample_count):
        self.saved.append((session_id, calibration, sample_count))
        self.calibration = calibration
        return True

    async def aclose(self):
        pass


def token(session_id=301, sensitivity="NORMAL", exp_delta=600, token_type="FOCUS_STREAM", secret=SECRET):
    return jwt.encode({"type": token_type, "sessionId": session_id, "userId": 1,
                       "focusSensitivity": sensitivity, "exp": int(time.time()) + exp_delta},
                      secret, algorithm="HS256")


@pytest.fixture
def client_factory(tmp_path):
    def make(fake):
        settings = Settings(SECRET, "k", "http://unused", time_source="client", feature_log_dir=str(tmp_path))
        return TestClient(create_app(settings, fake))
    return make


def send_frames(ws, items):
    for at, f in items:
        ws.send_json({"type": "features", "data": {"timestamp": at.isoformat(), "features": f}})


@pytest.mark.parametrize("bad", [None, "garbage", token(exp_delta=-10), token(token_type="ACCESS"),
                                 token(secret="other-secret-other-secret-other-secret-12")])
def test_토큰이_없거나_틀리면_4001로_끊는다(client_factory, bad):
    with client_factory(FakeMain()) as client:
        url = "/ws/focus" + (f"?token={bad}" if bad else "")
        with client.websocket_connect(url) as ws:
            with pytest.raises(WebSocketDisconnect) as e:
                ws.receive_json()
            assert e.value.code == 4001


def test_기준값이_없으면_캘리브레이션을_요청하고_완료하면_저장한다(client_factory):
    fake = FakeMain()
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        assert ws.receive_json() == {"type": "calibration.required"}

        for _ in range(25):
            ws.send_json({"type": "calibration.sample", "data": {"phase": "SCREEN", "features": face()}})
        ws.send_json({"type": "calibration.complete", "data": {"phase": "SCREEN"}})
        assert ws.receive_json() == {"type": "calibration.done", "data": {"phase": "SCREEN"}}

        for _ in range(3):
            ws.send_json({"type": "calibration.sample", "data": {"phase": "MATERIAL", "features": face(pitch=-27)}})
        ws.send_json({"type": "calibration.complete", "data": {"phase": "MATERIAL"}})
        assert ws.receive_json() == {"type": "calibration.failed",
                                     "data": {"phase": "MATERIAL", "reason": "FACE_NOT_DETECTED"}}

    assert len(fake.saved) == 1
    assert fake.saved[0][1].screen.headPitch == -6.2
    assert fake.saved[0][1].material is None


def test_자세가_흔들리면_UNSTABLE(client_factory):
    with client_factory(FakeMain()) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        for i in range(25):
            ws.send_json({"type": "calibration.sample",
                          "data": {"phase": "SCREEN", "features": face(yaw=(-20 if i % 2 else 20))}})
        ws.send_json({"type": "calibration.complete", "data": {"phase": "SCREEN"}})
        assert ws.receive_json()["data"]["reason"] == "UNSTABLE"


def test_자리_이탈_반응_후_복귀하면_clear와_이벤트_기록(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        assert ws.receive_json() == {"type": "calibration.ready"}
        send_frames(ws, frames(T0, 5, lambda i: face()))
        send_frames(ws, frames(T0 + 5 * S, 35, lambda i: no_face()))
        reaction = ws.receive_json()
        assert reaction == {"type": "reaction", "data": {"reactionId": "r-301-0001", "eventType": "AWAY"}}

        send_frames(ws, frames(T0 + 40 * S, 5, lambda i: face()))
        assert ws.receive_json() == {"type": "reaction.clear",
                                     "data": {"reactionId": "r-301-0001", "reason": "RECOVERED"}}
        ws.send_json({"type": "session.end", "data": {"timestamp": (T0 + 46 * S).isoformat()}})
        assert ws.receive_json() == {"type": "session.closed"}

    (session_id, payload), = fake.events
    assert session_id == 301
    assert payload["eventType"] == "AWAY"
    assert payload["startedAt"] == "2026-11-24T21:00:05"
    assert payload["falsePositive"] is False
    assert payload["modelVersion"] == "away-gaze-rule-v0.1"
    assert payload["featureSample"]["correctedLabel"] is None


def test_오탐_버튼이면_FALSE_POSITIVE로_닫고_FOCUSED로_기록(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        send_frames(ws, frames(T0, 5, lambda i: face()))
        send_frames(ws, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
        reaction = ws.receive_json()
        assert reaction["data"]["eventType"] == "GAZE_OFF"

        ws.send_json({"type": "feedback.false_positive",
                      "data": {"reactionId": reaction["data"]["reactionId"], "timestamp": (T0 + 45 * S).isoformat()}})
        assert ws.receive_json()["data"]["reason"] == "FALSE_POSITIVE"
        ws.send_json({"type": "session.end"})
        assert ws.receive_json() == {"type": "session.closed"}

    payload = fake.events[0][1]
    assert payload["falsePositive"] is True
    assert payload["featureSample"]["correctedLabel"] == "FOCUSED"
    assert payload["featureSample"]["predictedLabel"] == "GAZE_OFF"
    assert payload["endedAt"] == "2026-11-24T21:00:45"


def test_정탐_확인_버튼이면_원래_라벨로_기록(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        send_frames(ws, frames(T0, 5, lambda i: face()))
        send_frames(ws, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
        reaction_id = ws.receive_json()["data"]["reactionId"]
        ws.send_json({"type": "feedback.confirm", "data": {"reactionId": reaction_id}})
        assert ws.receive_json()["data"]["reason"] == "RECOVERED"
        ws.send_json({"type": "session.end"})
        ws.receive_json()

    payload = fake.events[0][1]
    assert payload["falsePositive"] is False
    assert payload["featureSample"]["correctedLabel"] == "GAZE_OFF"


def test_휴식_중에는_자리를_비워도_반응하지_않는다(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        send_frames(ws, frames(T0, 5, lambda i: face()))
        ws.send_json({"type": "detection.pause", "data": {"timestamp": (T0 + 5 * S).isoformat()}})
        send_frames(ws, frames(T0 + 6 * S, 120, lambda i: no_face()))
        ws.send_json({"type": "detection.resume", "data": {"timestamp": (T0 + 126 * S).isoformat()}})
        send_frames(ws, frames(T0 + 127 * S, 5, lambda i: face()))
        ws.send_json({"type": "session.end"})
        assert ws.receive_json() == {"type": "session.closed"}
    assert fake.events == []


def test_반응_중_휴식하면_그_시각으로_이벤트를_끝낸다(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        send_frames(ws, frames(T0, 5, lambda i: face()))
        send_frames(ws, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
        assert ws.receive_json()["type"] == "reaction"
        ws.send_json({"type": "detection.pause", "data": {"timestamp": (T0 + 50 * S).isoformat()}})
        assert ws.receive_json()["type"] == "reaction.clear"
        ws.send_json({"type": "session.end"})
        ws.receive_json()
    assert fake.events[0][1]["endedAt"] == "2026-11-24T21:00:50"


def test_session_end_없이_끊겨도_진행_중_이벤트를_기록한다(client_factory):
    fake = FakeMain(CAL)
    with client_factory(fake) as client:
        with client.websocket_connect(f"/ws/focus?token={token()}") as ws:
            ws.receive_json()
            send_frames(ws, frames(T0, 5, lambda i: face()))
            send_frames(ws, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
            assert ws.receive_json()["type"] == "reaction"
    assert len(fake.events) == 1 and fake.events[0][1]["eventType"] == "GAZE_OFF"


def test_형식이_틀린_메시지는_error(client_factory):
    with client_factory(FakeMain(CAL)) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        ws.send_text("not json")
        assert ws.receive_json()["data"]["code"] == "BAD_MESSAGE"
        ws.send_json({"type": "dance"})
        assert ws.receive_json()["data"]["code"] == "UNKNOWN_TYPE"
        ws.send_json({"type": "features", "data": {}})
        assert ws.receive_json()["data"]["code"] == "BAD_MESSAGE"


def test_특징값_로그가_파일로_남는다(client_factory, tmp_path):
    fake = FakeMain(CAL)
    with client_factory(fake) as client, client.websocket_connect(f"/ws/focus?token={token()}") as ws:
        ws.receive_json()
        send_frames(ws, frames(T0, 2, lambda i: face()))
        ws.send_json({"type": "session.end"})
        ws.receive_json()
    files = list(tmp_path.rglob("session-301-*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").strip().splitlines()
    assert sum('"kind": "frame"' in line for line in lines) == 10
