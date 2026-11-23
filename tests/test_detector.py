"""판정 조립: 지속 시간, 복귀, 우선순위, 쿨다운, featureSample (담당: 공통)."""
from datetime import timedelta

from app.detection.detector import AWAY, GAZE_OFF, Detector, ReactionEnded, ReactionStarted
from tests.helpers import CAL, T0, face, frames, no_face, run

S = timedelta(seconds=1)


def started(signals):
    return [s for s in signals if isinstance(s, ReactionStarted)]


def ended(signals):
    return [s for s in signals if isinstance(s, ReactionEnded)]


def test_집중_상태면_반응하지_않는다():
    d = Detector(CAL, "NORMAL")
    assert run(d, frames(T0, 120, lambda i: face())) == []
    assert run(d, frames(T0 + 120 * S, 120, lambda i: face(yaw=0.5, pitch=-27.5, eye=0.21))) == []


def test_복귀하면_조건이_마지막으로_성립한_시각으로_끝난다():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 10, lambda i: face()))
    sig = run(d, frames(T0 + 10 * S, 35, lambda i: no_face()))
    sig += run(d, frames(T0 + 45 * S, 5, lambda i: face()))
    end, = ended(sig)
    assert end.event_type == AWAY
    assert end.started_at == T0 + 10 * S
    assert T0 + 44 * S <= end.ended_at <= T0 + 45 * S


def test_반응은_한_번에_하나이고_시선_이탈_중에는_졸음을_보지_않는다():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 5, lambda i: face()))
    sig = run(d, frames(T0 + 5 * S, 90, lambda i: face(yaw=45, eye=0.05)))
    assert [s.event_type for s in started(sig)] == [GAZE_OFF]


def test_버튼으로_닫으면_같은_반응을_지속시간만큼_다시_띄우지_않는다():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 5, lambda i: face()))
    assert len(started(run(d, frames(T0 + 5 * S, 40, lambda i: face(yaw=45))))) == 1
    dismissed_at = T0 + 45 * S
    end = d.dismiss(dismissed_at)
    assert end.event_type == GAZE_OFF and end.ended_at == dismissed_at
    assert started(run(d, frames(dismissed_at, 29, lambda i: face(yaw=45)))) == []
    assert len(started(run(d, frames(dismissed_at + 29 * S, 35, lambda i: face(yaw=45))))) == 1


def test_close는_진행_중_반응을_그_시각으로_끝낸다():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 5, lambda i: face()))
    run(d, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
    end = d.close(T0 + 50 * S)
    assert end.event_type == GAZE_OFF and end.ended_at == T0 + 50 * S
    assert d.close(T0 + 51 * S) is None


def test_featureSample은_반응_직전_30초의_캘리브레이션_대비_변화량():
    d = Detector(CAL, "NORMAL")
    run(d, frames(T0, 5, lambda i: face()))
    run(d, frames(T0 + 5 * S, 40, lambda i: face(yaw=45)))
    sample = d.close(T0 + 50 * S).feature_sample
    assert sample["windowSeconds"] == 30 and sample["predictedLabel"] == GAZE_OFF
    assert sample["features"][-1]["headYaw"] == round(45 - 1.8, 4)
    assert sample["features"][-1]["headPitch"] == 0.0
    assert all(0 <= row["t"] <= 30 for row in sample["features"])
