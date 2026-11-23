from datetime import datetime, timedelta

from app.detection.calibration import Calibration, View

T0 = datetime(2026, 11, 24, 21, 0, 0)
FPS = 5

SCREEN = View(headYaw=1.8, headPitch=-6.2, headRoll=0.9, leftEyeOpenness=0.31,
              rightEyeOpenness=0.30, mouthOpenness=0.04, faceSize=0.22)
MATERIAL = View(headYaw=0.5, headPitch=-27.5, headRoll=1.2, leftEyeOpenness=0.22,
                rightEyeOpenness=0.21, mouthOpenness=0.04, faceSize=0.20)
CAL = Calibration(SCREEN, MATERIAL)


def face(yaw=1.8, pitch=-6.2, eye=0.30, iris_x=0.0):
    return {"facePresent": True, "headYaw": yaw, "headPitch": pitch, "headRoll": 0.9,
            "leftEyeOpenness": eye, "rightEyeOpenness": eye, "irisOffsetX": iris_x,
            "irisOffsetY": 0.0, "mouthOpenness": 0.04, "faceSize": 0.22}


def no_face():
    return {"facePresent": False, "headYaw": None, "headPitch": None, "headRoll": None,
            "leftEyeOpenness": None, "rightEyeOpenness": None, "irisOffsetX": None,
            "irisOffsetY": None, "mouthOpenness": None, "faceSize": None}


def frames(start: datetime, seconds: float, make):
    """start부터 seconds 동안 초당 5프레임. make(i)가 특징값을 만든다."""
    n = int(seconds * FPS)
    return [(start + timedelta(seconds=i / FPS), make(i)) for i in range(n)]


def run(detector, items):
    signals = []
    for at, f in items:
        signals.extend(detector.update(at, f))
    return signals
