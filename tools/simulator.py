"""브라우저 없이 AI 서버를 시험하는 가짜 클라이언트.

AI 서버를 TIME_SOURCE=client 로 켜면 시나리오가 몇 초 만에 끝난다.
(server 모드면 실제 시간만큼 걸림: --realtime)

빠른 재생에서는 시나리오 시각을 '지금 - 시나리오 길이'부터 시작한다.
메인 서버는 미래 시각과 세션 시작 이전 시각을 거절하므로,
Spring과 붙여 볼 때는 학습 시작 후 시나리오 길이(약 1~2분)만큼 지난 뒤 실행한다.

예)
  python -m tools.simulator --scenario drowsy --session-id 301
  python -m tools.simulator --scenario away --false-positive
"""
import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime, timedelta

import jwt
import websockets

FPS = 5


def make_token(secret: str, session_id: int, user_id: int, sensitivity: str) -> str:
    return jwt.encode({"type": "FOCUS_STREAM", "sessionId": session_id, "userId": user_id,
                       "focusSensitivity": sensitivity, "exp": int(time.time()) + 3600},
                      secret, algorithm="HS256")


def face(yaw=1.8, pitch=-6.2, eye=0.30):
    j = random.uniform(-0.5, 0.5)
    return {"facePresent": True, "headYaw": yaw + j, "headPitch": pitch + j, "headRoll": 0.9,
            "leftEyeOpenness": eye, "rightEyeOpenness": eye, "irisOffsetX": 0.0, "irisOffsetY": 0.0,
            "mouthOpenness": 0.04, "faceSize": 0.22}


NO_FACE = {"facePresent": False, **{k: None for k in (
    "headYaw", "headPitch", "headRoll", "leftEyeOpenness", "rightEyeOpenness",
    "irisOffsetX", "irisOffsetY", "mouthOpenness", "faceSize")}}

# (초, 특징값 생성 함수)
SCENARIOS = {
    "focused": [(60, lambda: face())],
    "drowsy": [(10, lambda: face()), (60, lambda: face(eye=0.05)), (10, lambda: face())],
    "away": [(10, lambda: face()), (40, lambda: dict(NO_FACE)), (10, lambda: face())],
    "gaze": [(10, lambda: face()), (40, lambda: face(yaw=45)), (10, lambda: face())],
}


async def run(args):
    token = make_token(args.secret, args.session_id, args.user_id, args.sensitivity)
    total = sum(seconds for seconds, _ in SCENARIOS[args.scenario])
    clock = datetime.now() if args.realtime else datetime.now() - timedelta(seconds=total + 5)

    async with websockets.connect(f"{args.url}?token={token}") as ws:
        async def receiver():
            async for raw in ws:
                msg = json.loads(raw)
                print("◀", msg)
                if msg["type"] == "reaction" and args.false_positive:
                    await send("feedback.false_positive", {"reactionId": msg["data"]["reactionId"]})

        async def send(msg_type, data=None):
            data = dict(data or {}, timestamp=clock.isoformat(timespec="milliseconds"))
            await ws.send(json.dumps({"type": msg_type, "data": data}))
            if msg_type not in ("features", "calibration.sample"):
                print("▶", msg_type, data)

        listener = asyncio.create_task(receiver())
        await asyncio.sleep(0.3)

        for phase, pitch in (("SCREEN", -6.2), ("MATERIAL", -27.5)):
            for _ in range(25):
                await send("calibration.sample", {"phase": phase, "features": face(pitch=pitch)})
            await send("calibration.complete", {"phase": phase})
        await asyncio.sleep(0.3)

        for seconds, make in SCENARIOS[args.scenario]:
            for _ in range(int(seconds * FPS)):
                await send("features", {"features": make()})
                clock += timedelta(seconds=1 / FPS)
                await asyncio.sleep(1 / FPS if args.realtime else 0.002)

        await send("session.end")
        await asyncio.sleep(1.0)
        listener.cancel()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="ws://localhost:8000/ws/focus")
    p.add_argument("--secret", default=os.getenv("FOCUS_STREAM_SECRET", ""))
    p.add_argument("--session-id", type=int, default=1)
    p.add_argument("--user-id", type=int, default=1)
    p.add_argument("--sensitivity", default="NORMAL", choices=["LOW", "NORMAL", "HIGH"])
    p.add_argument("--scenario", default="drowsy", choices=list(SCENARIOS))
    p.add_argument("--false-positive", action="store_true", help="반응이 오면 오탐 버튼을 누름")
    p.add_argument("--realtime", action="store_true", help="실제 시간 속도로 보냄 (TIME_SOURCE=server일 때)")
    args = p.parse_args()
    if len(args.secret.encode()) < 32:
        raise SystemExit("FOCUS_STREAM_SECRET 환경변수 또는 --secret 이 필요합니다 (32바이트 이상).")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
