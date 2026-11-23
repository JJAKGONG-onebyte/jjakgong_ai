"""졸음 판정 (담당: 송유진).

모델 B(깨어있음 / 졸음)로 바꿀 때는 score()만 모델 확률로 교체하면 된다.
엎드림 여부는 away_gaze.py가 판단해서 넘겨준다.
"""
from app.detection.base import DROWSY, FrameContext
from app.detection.thresholds import Sensitivity

# ===== 기준값 (초안) =====
PERCLOS_WINDOW_SECONDS = 10     # 최근 이 구간의 눈 감김 비율을 점수로 씀
EYE_CLOSED_RATIO = 0.5          # 기준값 대비 눈 뜬 정도가 이 비율 미만이면 감긴 것으로 봄
MIN_WINDOW_COVERAGE = 0.8       # 구간이 이만큼 차야 판단 (연결 직후 오판 방지)
MIN_VALID_FRAME_RATIO = 0.5     # 눈 값이 있는 프레임이 이보다 적으면 판단 보류
PRONE_SURE_SCORE = 0.5          # 엎드리기 직전 점수가 이 이상이면 '확실한 졸음' (NORMAL)


class DrowsyJudge:
    EVENT_TYPES = (DROWSY,)
    MODEL_VERSION = "drowsy-rule-v0.1"   # 모델 B로 바꾸면 버전도 바꾼다

    def __init__(self):
        self._was_prone = False
        self._prone_sure = False

    def hold_seconds(self, event_type: str, sensitivity: Sensitivity) -> float:
        return sensitivity.hold_seconds

    def reset(self) -> None:
        self._was_prone = self._prone_sure = False

    def evaluate(self, ctx: FrameContext, prone: bool) -> bool:
        if prone:
            if not self._was_prone:          # 엎드린 순간, 직전 구간이 졸렸는지 한 번 계산
                self._was_prone = True
                last_face = next((fr for fr in reversed(ctx.frames) if fr.face), None)
                before = self.score(ctx, until=last_face.at) if last_face else None
                self._prone_sure = before is not None and before >= PRONE_SURE_SCORE
            policy = ctx.sensitivity.prone_policy
            return policy == "REACT" or (policy == "SURE_ONLY" and self._prone_sure)

        self._was_prone = self._prone_sure = False
        if not ctx.face:
            return False
        score = self.score(ctx)
        return score is not None and score >= ctx.sensitivity.score_threshold

    def score(self, ctx: FrameContext, until=None) -> float | None:
        """졸음 점수 0~1 (지금은 PERCLOS). 판단할 수 없으면 None."""
        end = until or ctx.now
        window = ctx.recent(PERCLOS_WINDOW_SECONDS, until=end)
        if not window or (end - window[0].at).total_seconds() < PERCLOS_WINDOW_SECONDS * MIN_WINDOW_COVERAGE:
            return None
        closed = valid = 0
        for fr in window:
            f = fr.features
            left, right = f.get("leftEyeOpenness"), f.get("rightEyeOpenness")
            if not fr.face or left is None or right is None:
                continue
            valid += 1
            base = ctx.view_for(f).eye_openness
            if base > 0 and ((left + right) / 2) / base < EYE_CLOSED_RATIO:
                closed += 1
        if valid == 0 or valid < len(window) * MIN_VALID_FRAME_RATIO:
            return None
        return closed / valid
