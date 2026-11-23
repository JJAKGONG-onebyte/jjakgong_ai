"""얼굴/자리 이탈 · 시선 이탈 (담당: 성유민)."""
from datetime import timedelta

from app.detection.away_gaze import AwayGazeJudge
from app.detection.base import AWAY, DROWSY, GAZE_OFF, Frame, FrameContext
from app.detection.detector import Detector, ReactionEnded, ReactionStarted
from app.detection.thresholds import SENSITIVITY
from tests.helpers import CAL, T0, face, frames, no_face, run

S = timedelta(seconds=1)


def started(signals):
    return [s for s in signals if isinstance(s, ReactionStarted)]


def ctx_of(history, features):
    """history: [(at, features)], 마지막 프레임이 지금."""
    fr = tuple(Frame(at, f) for at, f in history) + (Frame(T0 + 100 * S, features),)
    return FrameContext(T0 + 100 * S, features, fr, CAL, SENSITIVITY["NORMAL"])


# ===== 판정기 단위 =====

def test_정면이면_이탈_아님():
    r = AwayGazeJudge().evaluate(ctx_of([], face()))
    assert (r.away, r.gaze_off, r.prone) == (False, False, False)


def test_자료_보는_자세는_시선_이탈_아님():
    r = AwayGazeJudge().evaluate(ctx_of([], face(yaw=0.5, pitch=-27.5)))
    assert r.gaze_off is False


def test_고개를_크게_돌리거나_홍채가_끝에_있으면_시선_이탈():
    assert AwayGazeJudge().evaluate(ctx_of([], face(yaw=45))).gaze_off
    assert AwayGazeJudge().evaluate(ctx_of([], face(iris_x=0.9))).gaze_off


def test_얼굴이_없으면_자리_이탈_조건():
    r = AwayGazeJudge().evaluate(ctx_of([], no_face()))
    assert r.away and not r.prone


def test_숙여지다_사라지면_엎드림():
    history = [(T0 + 95 * S + i * S / 5, face(pitch=-10 - i * 1.0)) for i in range(25)]
    r = AwayGazeJudge().evaluate(ctx_of(history, no_face()))
    assert r.prone and not r.away


# ===== 지속 시간까지 포함 =====

def test_얼굴이_30초_이상_없으면_AWAY():
    d = Detector(CAL, "NORMAL")
    sig = run(d, frames(T0, 10, lambda i: face()))
    sig += run(d, frames(T0 + 10 * S, 29, lambda i: no_face()))
    assert started(sig) == []
    sig += run(d, frames(T0 + 39 * S, 5, lambda i: no_face()))
    assert [s.event_type for s in started(sig)] == [AWAY]
    assert started(sig)[0].started_at == T0 + 10 * S


def test_고개를_돌린_채_지속되면_GAZE_OFF():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 5, lambda i: face()))
    sig = run(d, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
    assert [x.event_type for x in started(sig)] == [GAZE_OFF]


def test_엎드림은_LOW면_반응하지_않는다():
    d = Detector(CAL, "LOW")
    run(d, frames(T0, 10, lambda i: face()))
    run(d, frames(T0 + 10 * S, 5, lambda i: face(pitch=-10 - i * 1.5)))
    assert started(run(d, frames(T0 + 15 * S, 90, lambda i: no_face()))) == []


def test_엎드림은_HIGH면_졸음으로_반응한다():
    d = Detector(CAL, "HIGH")
    run(d, frames(T0, 10, lambda i: face()))
    run(d, frames(T0 + 10 * S, 5, lambda i: face(pitch=-10 - i * 1.5)))
    sig = run(d, frames(T0 + 15 * S, 30, lambda i: no_face()))
    assert [x.event_type for x in started(sig)] == [DROWSY]
