"""졸음 (담당: 송유진)."""
from datetime import timedelta

from app.detection.base import Frame, FrameContext
from app.detection.detector import DROWSY, Detector, ReactionStarted
from app.detection.drowsy import DrowsyJudge
from app.detection.thresholds import SENSITIVITY
from tests.helpers import CAL, T0, face, frames, no_face, run

S = timedelta(seconds=1)


def started(signals):
    return [s for s in signals if isinstance(s, ReactionStarted)]


def ctx_with(items, sensitivity="NORMAL"):
    fr = tuple(Frame(at, f) for at, f in items)
    at, f = items[-1]
    return FrameContext(at, f, fr, CAL, SENSITIVITY[sensitivity])


# ===== 판정기 단위 =====

def test_점수는_최근_10초_눈_감김_비율():
    judge = DrowsyJudge()
    assert judge.score(ctx_with(frames(T0, 11, lambda i: face()))) == 0.0
    assert judge.score(ctx_with(frames(T0, 11, lambda i: face(eye=0.05)))) == 1.0
    half = judge.score(ctx_with(frames(T0, 11, lambda i: face(eye=0.05 if i % 2 else 0.30))))
    assert 0.4 < half < 0.6


def test_구간이_덜_찼으면_판단_보류():
    assert DrowsyJudge().score(ctx_with(frames(T0, 3, lambda i: face(eye=0.05)))) is None


def test_자료를_볼_때는_자료_자세의_눈_기준값을_쓴다():
    # 자료 기준 눈 뜬 정도 0.215 → 0.2는 감긴 게 아님 (화면 기준 0.305였다면 감긴 것에 가까움)
    score = DrowsyJudge().score(ctx_with(frames(T0, 11, lambda i: face(pitch=-27.5, eye=0.2))))
    assert score == 0.0


def test_얼굴이_없고_엎드림도_아니면_졸음_아님():
    assert DrowsyJudge().evaluate(ctx_with(frames(T0, 11, lambda i: no_face())), prone=False) is False


def test_엎드림_정책():
    awake = frames(T0, 11, lambda i: face())
    sleepy = frames(T0, 11, lambda i: face(eye=0.05))
    gone = [(T0 + 12 * S, no_face())]
    assert DrowsyJudge().evaluate(ctx_with(awake + gone, "LOW"), prone=True) is False
    assert DrowsyJudge().evaluate(ctx_with(awake + gone, "NORMAL"), prone=True) is False
    assert DrowsyJudge().evaluate(ctx_with(sleepy + gone, "NORMAL"), prone=True) is True
    assert DrowsyJudge().evaluate(ctx_with(awake + gone, "HIGH"), prone=True) is True


# ===== 지속 시간까지 포함 =====

def test_눈을_감고_있으면_NORMAL은_DROWSY():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 10, lambda i: face()))
    s = started(run(d, frames(T0 + 10 * S, 60, lambda i: face(eye=0.05))))
    assert [x.event_type for x in s] == [DROWSY]
    assert 10 <= (s[0].started_at - T0).total_seconds() <= 20


def test_강도가_HIGH면_더_빨리_LOW면_더_늦게_반응한다():
    def first_reaction_time(sensitivity):
        d = Detector(CAL, sensitivity)
        run(d, frames(T0, 10, lambda i: face()))
        for at, f in frames(T0 + 10 * S, 120, lambda i: face(eye=0.05)):
            if started(d.update(at, f)):
                return at
        return None

    high, normal, low = (first_reaction_time(s) for s in ("HIGH", "NORMAL", "LOW"))
    assert high < normal < low


def test_깜빡임은_졸음이_아니다():
    d = Detector(CAL, "HIGH")
    assert started(run(d, frames(T0, 120, lambda i: face(eye=0.05 if i % 15 == 0 else 0.30)))) == []
