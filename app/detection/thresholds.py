"""공통 판정 기준값 (담당: 공통 / 바꿀 때는 두 사람 합의).

각 판정 전용 기준값은 away_gaze.py, drowsy.py 맨 위에 있다.
단속 강도별 기준은 노션 '집중 감지 WebSocket' 명세의 초안 표를 따르며,
규칙 기반 단계에서는 '확률' 자리에 규칙 점수(0~1)를 쓴다.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Sensitivity:
    score_threshold: float   # 졸음·시선 이탈 점수 기준
    hold_seconds: float      # 이 시간 이상 지속되면 반응
    prone_policy: str        # 엎드림: IGNORE / SURE_ONLY / REACT


SENSITIVITY = {
    "LOW": Sensitivity(0.9, 60, "IGNORE"),
    "NORMAL": Sensitivity(0.8, 30, "SURE_ONLY"),
    "HIGH": Sensitivity(0.7, 15, "REACT"),
}

# 조건이 잠깐 끊겨도 같은 상태로 보는 시간 (깜빡임·검출 흔들림 흡수)
GAP_TOLERANCE_SECONDS = 2.0
# 반응 중 조건이 이 시간 이상 풀리면 복귀로 본다
RECOVER_SECONDS = 2.0
# 재학습용 특징값 구간 길이
SAMPLE_WINDOW_SECONDS = 30
# 판정에 쓰는 최근 프레임 보관 시간
BUFFER_SECONDS = 40
