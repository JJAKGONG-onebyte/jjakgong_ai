"""판정 조립 (담당: 공통 / 바꿀 때는 두 사람 합의).

초당 5회 들어오는 특징값을 두 판정기에 넘기고, 결과를 모아
'얼마나 지속됐는지'를 보고 반응 시작/종료 신호를 낸다.

    away_gaze.py (성유민)  → AWAY, GAZE_OFF, 엎드림 여부
    drowsy.py    (송유진)  → DROWSY

여기서 처리하는 것: 지속 시간, 우선순위(AWAY > DROWSY > GAZE_OFF), 한 번에 반응 하나,
복귀 판정, 버튼으로 닫은 뒤 쿨다운, 재학습용 featureSample.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from app.detection import thresholds as th
from app.detection.away_gaze import AwayGazeJudge
from app.detection.base import (AWAY, DROWSY, GAZE_OFF, Frame, FrameContext, Hold, ReactionEnded,
                                ReactionStarted, plus, seconds_between, view_for)
from app.detection.calibration import Calibration
from app.detection.drowsy import DrowsyJudge

PRIORITY = (AWAY, DROWSY, GAZE_OFF)

__all__ = ["Detector", "ReactionStarted", "ReactionEnded", "AWAY", "DROWSY", "GAZE_OFF"]


@dataclass
class _Active:
    event_type: str
    started_at: datetime
    feature_sample: dict


class Detector:

    def __init__(self, calibration: Calibration, sensitivity: str = "NORMAL"):
        self.calibration = calibration
        self.sensitivity = th.SENSITIVITY.get(sensitivity, th.SENSITIVITY["NORMAL"])
        self.away_gaze = AwayGazeJudge()
        self.drowsy = DrowsyJudge()
        self._frames: deque[Frame] = deque()
        self._holds = {t: Hold(th.GAP_TOLERANCE_SECONDS, th.RECOVER_SECONDS) for t in PRIORITY}
        self._active: _Active | None = None
        self._cooldown_until: dict[str, datetime] = {}

    @property
    def active_event_type(self) -> str | None:
        return self._active.event_type if self._active else None

    def update(self, now: datetime, features: dict) -> list:
        self._frames.append(Frame(now, features))
        while self._frames and seconds_between(self._frames[0].at, now) > th.BUFFER_SECONDS:
            self._frames.popleft()

        ctx = FrameContext(now, features, tuple(self._frames), self.calibration, self.sensitivity)
        ag = self.away_gaze.evaluate(ctx)
        # 명세: 시선 이탈이 아닐 때(정면·숙임)만 졸음을 본다
        drowsy = self.drowsy.evaluate(ctx, prone=ag.prone) and not ag.gaze_off
        conditions = {AWAY: ag.away, GAZE_OFF: ag.gaze_off, DROWSY: drowsy}
        for event_type, cond in conditions.items():
            self._holds[event_type].feed(now, cond)

        signals = []
        if self._active and self._holds[self._active.event_type].onset is None:
            signals.append(self._end_active(self._holds[self._active.event_type].released_at or now))

        if self._active is None:
            for event_type in PRIORITY:
                hold = self._holds[event_type]
                if self._cooling_down(event_type, now) or hold.held_seconds(now) < self._hold_seconds(event_type):
                    continue
                self._active = _Active(event_type, hold.onset, self._feature_sample(now, event_type))
                signals.append(ReactionStarted(event_type, hold.onset))
                break
        return signals

    def dismiss(self, now: datetime) -> ReactionEnded | None:
        """사용자가 버튼으로 반응을 닫음. 같은 반응은 지속 시간만큼 다시 띄우지 않는다."""
        if self._active is None:
            return None
        event_type = self._active.event_type
        self._cooldown_until[event_type] = plus(now, self._hold_seconds(event_type))
        self._holds[event_type].reset()
        return self._end_active(now)

    def close(self, now: datetime) -> ReactionEnded | None:
        """휴식·종료·연결 끊김: 진행 중 반응을 지금 시각으로 끝내고 상태를 비운다."""
        ended = self._end_active(now) if self._active else None
        self._frames.clear()
        for hold in self._holds.values():
            hold.reset()
        self.away_gaze.reset()
        self.drowsy.reset()
        return ended

    def model_version(self, event_type: str) -> str:
        """이벤트 기록의 modelVersion (판정기마다 따로 관리)."""
        return self._judge(event_type).MODEL_VERSION

    # ===== 내부 =====

    def _judge(self, event_type: str):
        return self.drowsy if event_type == DROWSY else self.away_gaze

    def _hold_seconds(self, event_type: str) -> float:
        return self._judge(event_type).hold_seconds(event_type, self.sensitivity)

    def _cooling_down(self, event_type: str, now: datetime) -> bool:
        until = self._cooldown_until.get(event_type)
        return until is not None and now < until

    def _end_active(self, ended_at: datetime) -> ReactionEnded:
        active, self._active = self._active, None
        return ReactionEnded(active.event_type, active.started_at, max(ended_at, active.started_at),
                             active.feature_sample)

    def _feature_sample(self, fired_at: datetime, event_type: str) -> dict:
        """반응 직전 30초의 캘리브레이션 대비 변화량 (명세 featureSample 구조)."""
        start = plus(fired_at, -th.SAMPLE_WINDOW_SECONDS)
        rows = [{"t": round(seconds_between(start, fr.at), 1), **self._deltas(fr.features)}
                for fr in self._frames if start <= fr.at <= fired_at]
        return {"windowSeconds": th.SAMPLE_WINDOW_SECONDS, "features": rows, "predictedLabel": event_type}

    def _deltas(self, f: dict) -> dict:
        if f.get("facePresent") is not True:
            return {"facePresent": False}
        view = view_for(self.calibration, f)

        def diff(key: str):
            value = f.get(key)
            return None if value is None else round(value - getattr(view, key), 4)

        return {
            "facePresent": True,
            **{k: diff(k) for k in ("headYaw", "headPitch", "headRoll", "leftEyeOpenness",
                                     "rightEyeOpenness", "mouthOpenness", "faceSize")},
            "irisOffsetX": f.get("irisOffsetX"),
            "irisOffsetY": f.get("irisOffsetY"),
        }
