"""판정 모듈끼리 주고받는 공통 형식 (담당: 공통 / 바꿀 때는 두 사람 합의).

- 브라우저 features 한 프레임 = dict (명세의 features 구조 그대로)
- 각 판정기는 FrameContext를 받아 '이 프레임에서 조건이 성립하는가'만 답한다.
  지속 시간, 반응 시작/종료, 우선순위, 쿨다운은 detector.py가 처리한다.
"""
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.detection.calibration import Calibration, View
from app.detection.thresholds import Sensitivity

AWAY, GAZE_OFF, DROWSY = "AWAY", "GAZE_OFF", "DROWSY"


@dataclass(frozen=True)
class Frame:
    at: datetime
    features: dict

    @property
    def face(self) -> bool:
        return self.features.get("facePresent") is True


@dataclass(frozen=True)
class FrameContext:
    now: datetime
    features: dict
    frames: Sequence[Frame]        # 최근 BUFFER_SECONDS 프레임 (지금 프레임 포함, 오래된 순)
    calibration: Calibration
    sensitivity: Sensitivity

    @property
    def face(self) -> bool:
        return self.features.get("facePresent") is True

    def recent(self, seconds: float, until: datetime | None = None) -> list[Frame]:
        end = until or self.now
        return [fr for fr in self.frames if fr.at <= end and seconds_between(fr.at, end) <= seconds]

    def view_for(self, features: dict) -> View:
        return view_for(self.calibration, features)


def view_for(calibration: Calibration, features: dict) -> View:
    """고개 각도가 화면 자세와 자료 자세 중 어디에 가까운지로 기준값을 고른다."""
    pitch = features.get("headPitch")
    if calibration.material is None or pitch is None:
        return calibration.screen
    near_material = abs(pitch - calibration.material.headPitch) < abs(pitch - calibration.screen.headPitch)
    return calibration.material if near_material else calibration.screen


def seconds_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds()


@dataclass
class ReactionStarted:
    event_type: str
    started_at: datetime


@dataclass
class ReactionEnded:
    event_type: str
    started_at: datetime
    ended_at: datetime
    feature_sample: dict


class Hold:
    """조건이 언제부터 이어지고 있는지 추적. 잠깐 끊기는 건 같은 구간으로 본다."""

    def __init__(self, gap_seconds: float, recover_seconds: float):
        self._gap = gap_seconds
        self._recover = recover_seconds
        self.onset: datetime | None = None
        self.last_true: datetime | None = None
        self.released_at: datetime | None = None

    def feed(self, now: datetime, cond: bool) -> None:
        if cond:
            if self.onset is None or seconds_between(self.last_true, now) > self._gap:
                self.onset = now
            self.last_true = now
        elif self.onset is not None and seconds_between(self.last_true, now) > self._recover:
            self.released_at = self.last_true
            self.onset = self.last_true = None

    def held_seconds(self, now: datetime) -> float:
        return 0.0 if self.onset is None else seconds_between(self.onset, now)

    def reset(self) -> None:
        self.onset = self.last_true = None


def plus(at: datetime, seconds: float) -> datetime:
    return at + timedelta(seconds=seconds)
