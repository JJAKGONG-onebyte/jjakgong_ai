"""얼굴/자리 이탈 · 시선 이탈 판정 (담당: 성유민).

모델 A(정면 / 숙임 / 이탈)로 바꿀 때는 evaluate()의 규칙 부분만 교체하면 된다.
detector.py는 AwayGazeResult만 보고 지속 시간·반응을 처리한다.
"""
from dataclasses import dataclass

from app.detection.base import AWAY, GAZE_OFF, FrameContext
from app.detection.thresholds import Sensitivity

# ===== 기준값 (초안) =====
AWAY_HOLD_SECONDS = 30                  # 얼굴 미검출 30초 (기능명세서, 강도와 무관)

GAZE_YAW_DEGREES = 25                   # 화면·자료 기준 대비 좌우
GAZE_PITCH_UP_DEGREES = 20              # 화면 기준보다 위
GAZE_PITCH_DOWN_DEGREES = 20            # 자료 기준보다 아래
GAZE_PITCH_DOWN_NO_MATERIAL_DEGREES = 30  # 자료 기준이 없을 때 화면 기준보다 아래
GAZE_IRIS_X = 0.8                       # 홍채 좌우 위치

PRONE_LOOKBACK_SECONDS = 5              # 얼굴이 사라지기 직전 이 구간의 고개 각도를 본다
PRONE_PITCH_BELOW_DOWN_VIEW = 10        # 아래 보는 기준 자세보다 이만큼 더 숙였으면 엎드림
PRONE_PITCH_DROP = 15                   # 구간 동안 이만큼 숙여지다 사라졌으면 엎드림


@dataclass(frozen=True)
class AwayGazeResult:
    away: bool        # 자리 이탈 조건 성립
    gaze_off: bool    # 시선 이탈 조건 성립
    prone: bool       # 얼굴이 없지만 엎드림으로 판단 (자리 이탈 아님, 졸음 판정으로 넘김)


class AwayGazeJudge:
    EVENT_TYPES = (AWAY, GAZE_OFF)
    MODEL_VERSION = "away-gaze-rule-v0.1"   # 모델 A로 바꾸면 버전도 바꾼다

    def __init__(self):
        self._face_lost = False
        self._prone = False

    def hold_seconds(self, event_type: str, sensitivity: Sensitivity) -> float:
        return AWAY_HOLD_SECONDS if event_type == AWAY else sensitivity.hold_seconds

    def reset(self) -> None:
        self._face_lost = self._prone = False

    def evaluate(self, ctx: FrameContext) -> AwayGazeResult:
        if not ctx.face:
            if not self._face_lost:          # 얼굴이 막 사라진 순간에 한 번 판단
                self._face_lost = True
                self._prone = self._judge_prone(ctx)
            return AwayGazeResult(away=not self._prone, gaze_off=False, prone=self._prone)

        self._face_lost = self._prone = False
        return AwayGazeResult(away=False, gaze_off=self._gaze_off(ctx), prone=False)

    def _gaze_off(self, ctx: FrameContext) -> bool:
        cal, f = ctx.calibration, ctx.features
        yaw, pitch, iris_x = f.get("headYaw"), f.get("headPitch"), f.get("irisOffsetX")
        if yaw is None or pitch is None:
            return False
        yaw_dev = abs(yaw - cal.screen.headYaw)
        if cal.material is not None:
            yaw_dev = min(yaw_dev, abs(yaw - cal.material.headYaw))
            too_low = pitch < cal.material.headPitch - GAZE_PITCH_DOWN_DEGREES
        else:
            too_low = pitch < cal.screen.headPitch - GAZE_PITCH_DOWN_NO_MATERIAL_DEGREES
        too_high = pitch > cal.screen.headPitch + GAZE_PITCH_UP_DEGREES
        iris_off = iris_x is not None and abs(iris_x) > GAZE_IRIS_X
        return yaw_dev > GAZE_YAW_DEGREES or too_low or too_high or iris_off

    def _judge_prone(self, ctx: FrameContext) -> bool:
        """얼굴이 사라지기 직전 고개가 많이 숙여져 있었거나 점점 숙여졌으면 엎드림."""
        recent = [fr for fr in ctx.recent(PRONE_LOOKBACK_SECONDS)
                  if fr.face and fr.features.get("headPitch") is not None]
        if not recent:
            return False
        cal = ctx.calibration
        down_ref = cal.material.headPitch if cal.material else cal.screen.headPitch - 20
        first, last = recent[0].features["headPitch"], recent[-1].features["headPitch"]
        return last < down_ref - PRONE_PITCH_BELOW_DOWN_VIEW or (first - last) >= PRONE_PITCH_DROP
