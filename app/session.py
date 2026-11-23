"""WebSocket 연결 하나(= 학습 세션 하나)의 메시지 처리.

명세: 노션 '집중 감지 WebSocket (브라우저 ↔ AI 서버)'
"""
import asyncio
import json
import logging
from datetime import datetime

from fastapi import WebSocket

from app.auth import StreamClaims
from app.config import Settings
from app.detection.calibration import Calibration, CalibrationFailed, compute_view
from app.detection.detector import Detector, ReactionEnded, ReactionStarted
from app.feature_log import FeatureLogger
from app.main_server import MainServerClient
from app.timeutil import now_kst, parse_client_time, to_iso

log = logging.getLogger(__name__)
PHASES = ("SCREEN", "MATERIAL")
FOCUSED = "FOCUSED"


class FocusSession:

    def __init__(self, ws: WebSocket, claims: StreamClaims, settings: Settings, main: MainServerClient):
        self.ws = ws
        self.claims = claims
        self.settings = settings
        self.main = main
        self.calibration: Calibration | None = None
        self.detector: Detector | None = None
        self.paused = False
        self.closed = False
        self._samples: dict[str, list[dict]] = {p: [] for p in PHASES}
        self._sample_count = 0
        self._reaction_seq = 0
        self._reaction_id: str | None = None
        self._last_at: datetime = now_kst()
        self._pending: set[asyncio.Task] = set()
        self.logger = FeatureLogger(settings.feature_log_dir, claims.session_id, claims.user_id, self._last_at)

    # ===== 연결 =====

    async def start(self) -> None:
        self.calibration = await self.main.get_calibration(self.claims.session_id)
        if self.calibration:
            self.detector = Detector(self.calibration, self.claims.focus_sensitivity)
            await self.send("calibration.ready")
        else:
            await self.send("calibration.required")

    async def handle(self, raw: str) -> None:
        try:
            message = json.loads(raw)
            msg_type = message["type"]
            data = message.get("data") or {}
        except (ValueError, KeyError, TypeError):
            await self.send("error", {"code": "BAD_MESSAGE", "message": "메시지 형식이 올바르지 않습니다."})
            return

        handler = {
            "calibration.sample": self._on_calibration_sample,
            "calibration.complete": self._on_calibration_complete,
            "features": self._on_features,
            "feedback.false_positive": self._on_false_positive,
            "feedback.confirm": self._on_confirm,
            "detection.pause": self._on_pause,
            "detection.resume": self._on_resume,
            "session.end": self._on_session_end,
            "tracking.stop": self._on_session_end,
        }.get(msg_type)
        if handler is None:
            await self.send("error", {"code": "UNKNOWN_TYPE", "message": f"알 수 없는 type: {msg_type}"})
            return
        try:
            await handler(data)
        except (KeyError, TypeError, ValueError) as e:
            await self.send("error", {"code": "BAD_MESSAGE", "message": f"{msg_type} 처리 실패: {e}"})

    async def on_disconnect(self) -> None:
        """브라우저가 session.end 없이 끊김: 진행 중 이벤트를 마지막 수신 시각으로 기록."""
        if not self.closed:
            self._close_detector(self._last_at)
            self.closed = True
        await self._drain()
        self.logger.close()

    # ===== 캘리브레이션 =====

    async def _on_calibration_sample(self, data: dict) -> None:
        phase = data["phase"]
        if phase not in PHASES:
            raise ValueError("phase는 SCREEN 또는 MATERIAL 입니다.")
        self._samples[phase].append(data["features"])

    async def _on_calibration_complete(self, data: dict) -> None:
        phase = data["phase"]
        if phase not in PHASES:
            raise ValueError("phase는 SCREEN 또는 MATERIAL 입니다.")
        samples, self._samples[phase] = self._samples[phase], []
        try:
            view = compute_view(samples)
        except CalibrationFailed as e:
            await self.send("calibration.failed", {"phase": phase, "reason": e.reason})
            return
        if phase == "SCREEN":
            material = self.calibration.material if self.calibration else None
            self.calibration = Calibration(view, material)
        else:
            if self.calibration is None:
                raise ValueError("SCREEN 단계를 먼저 완료해야 합니다.")
            self.calibration = Calibration(self.calibration.screen, view)
        self._sample_count += len(samples)
        self.detector = Detector(self.calibration, self.claims.focus_sensitivity)
        await self.main.save_calibration(self.claims.session_id, self.calibration, self._sample_count)
        await self.send("calibration.done", {"phase": phase})

    # ===== 감지 =====

    async def _on_features(self, data: dict) -> None:
        now = self._now(data)
        features = data["features"]
        self.logger.frame(now, features, self.detector.active_event_type if self.detector else None)
        if self.detector is None or self.paused or self.closed:
            return  # 기준값이 없거나 휴식 중이면 판정하지 않음 (UNKNOWN)
        for signal in self.detector.update(now, features):
            if isinstance(signal, ReactionStarted):
                self._reaction_seq += 1
                self._reaction_id = f"r-{self.claims.session_id}-{self._reaction_seq:04d}"
                await self.send("reaction", {"reactionId": self._reaction_id, "eventType": signal.event_type})
            elif isinstance(signal, ReactionEnded):
                await self._clear("RECOVERED")
                self._record(signal, false_positive=False, corrected_label=None)

    async def _on_false_positive(self, data: dict) -> None:
        await self._on_feedback(data, false_positive=True)

    async def _on_confirm(self, data: dict) -> None:
        await self._on_feedback(data, false_positive=False)

    async def _on_feedback(self, data: dict, false_positive: bool) -> None:
        if self.detector is None or data.get("reactionId") != self._reaction_id:
            return  # 이미 닫힌 반응에 대한 늦은 버튼
        ended = self.detector.dismiss(self._now(data))
        if ended is None:
            return
        await self._clear("FALSE_POSITIVE" if false_positive else "RECOVERED")
        corrected = FOCUSED if false_positive else ended.event_type
        self._record(ended, false_positive=false_positive, corrected_label=corrected)

    async def _on_pause(self, data: dict) -> None:
        now = self._now(data)
        self.logger.marker("pause", now)
        await self._close_and_clear(now)
        self.paused = True

    async def _on_resume(self, data: dict) -> None:
        self.logger.marker("resume", self._now(data))
        self.paused = False

    async def _on_session_end(self, data: dict) -> None:
        now = self._now(data)
        self.logger.marker("end", now)
        await self._close_and_clear(now)
        self.closed = True
        await self._drain()  # 진행 중 이벤트 기록이 끝난 뒤 session.closed
        await self.send("session.closed")
        await self.ws.close(code=1000)

    # ===== 공통 =====

    async def _close_and_clear(self, now: datetime) -> None:
        if self._close_detector(now):
            await self._clear("RECOVERED")

    def _close_detector(self, now: datetime) -> bool:
        if self.detector is None:
            return False
        ended = self.detector.close(now)
        if ended is None:
            return False
        self._record(ended, false_positive=False, corrected_label=None)
        return True

    async def _clear(self, reason: str) -> None:
        if self._reaction_id:
            await self.send("reaction.clear", {"reactionId": self._reaction_id, "reason": reason})
            self._reaction_id = None

    def _record(self, ended: ReactionEnded, false_positive: bool, corrected_label: str | None) -> None:
        self.logger.label(ended.event_type, ended.started_at, ended.ended_at, false_positive, corrected_label)
        sample = dict(ended.feature_sample, correctedLabel=corrected_label)
        payload = {
            "eventType": ended.event_type,
            "startedAt": to_iso(ended.started_at),
            "endedAt": to_iso(ended.ended_at),
            "falsePositive": false_positive,
            "modelVersion": self.detector.model_version(ended.event_type),
            "confidence": None,
            "featureSample": sample if sample["features"] else None,
        }
        task = asyncio.create_task(self.main.record_event(self.claims.session_id, payload))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _drain(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)

    def _now(self, data: dict) -> datetime:
        if self.settings.time_source == "client" and data.get("timestamp"):
            now = parse_client_time(data["timestamp"])
        else:
            now = now_kst()
        self._last_at = now
        return now

    async def send(self, msg_type: str, data: dict | None = None) -> None:
        message = {"type": msg_type}
        if data is not None:
            message["data"] = data
        await self.ws.send_text(json.dumps(message, ensure_ascii=False))
