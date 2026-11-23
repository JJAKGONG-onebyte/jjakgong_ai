"""캘리브레이션 기준값 계산.

브라우저가 단계(SCREEN/MATERIAL)마다 calibration.sample을 보내고
calibration.complete로 끝을 알리면 평균값을 기준값으로 쓴다.
"""
from dataclasses import asdict, dataclass
from statistics import mean, pstdev

VIEW_FIELDS = ("headYaw", "headPitch", "headRoll", "leftEyeOpenness",
               "rightEyeOpenness", "mouthOpenness", "faceSize")

MIN_FACE_SAMPLES = 10
MAX_ANGLE_STD = 5.0  # 도. 이보다 흔들리면 자세 불안정


@dataclass(frozen=True)
class View:
    headYaw: float
    headPitch: float
    headRoll: float
    leftEyeOpenness: float
    rightEyeOpenness: float
    mouthOpenness: float
    faceSize: float

    @property
    def eye_openness(self) -> float:
        return (self.leftEyeOpenness + self.rightEyeOpenness) / 2

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "View":
        return View(**{k: float(data[k]) for k in VIEW_FIELDS})


@dataclass(frozen=True)
class Calibration:
    screen: View
    material: View | None = None


class CalibrationFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason  # FACE_NOT_DETECTED / UNSTABLE


def compute_view(samples: list[dict]) -> View:
    usable = [s for s in samples
              if s.get("facePresent") and all(s.get(k) is not None for k in VIEW_FIELDS)]
    if len(usable) < MIN_FACE_SAMPLES:
        raise CalibrationFailed("FACE_NOT_DETECTED")
    for angle in ("headYaw", "headPitch"):
        if pstdev(s[angle] for s in usable) > MAX_ANGLE_STD:
            raise CalibrationFailed("UNSTABLE")
    return View(**{k: round(mean(s[k] for s in usable), 4) for k in VIEW_FIELDS})
