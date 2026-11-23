"""데이터 수집용 특징값 로그 (JSONL, 세션당 파일 하나).

영상은 없고 MediaPipe 수치와 판정 결과, 사용자가 버튼으로 준 라벨만 저장한다.
나중에 모델 A·B 학습 데이터로 쓴다. 저장소에 올리지 않는다 (.gitignore: data/).
"""
import json
from datetime import datetime
from pathlib import Path

from app.timeutil import to_iso


class FeatureLogger:

    def __init__(self, base_dir: str, session_id: int, user_id: int, started: datetime):
        self._file = None
        if not base_dir:
            return
        folder = Path(base_dir) / started.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"session-{session_id}-user-{user_id}-{started.strftime('%H%M%S')}.jsonl"
        self._file = path.open("a", encoding="utf-8")

    def frame(self, at: datetime, features: dict, active: str | None) -> None:
        self._write({"kind": "frame", "at": at.isoformat(timespec="milliseconds"),
                     "features": features, "active": active})

    def label(self, event_type: str, started_at: datetime, ended_at: datetime,
              false_positive: bool, corrected_label: str | None) -> None:
        self._write({"kind": "label", "eventType": event_type,
                     "startedAt": to_iso(started_at), "endedAt": to_iso(ended_at),
                     "falsePositive": false_positive, "correctedLabel": corrected_label})

    def marker(self, name: str, at: datetime) -> None:
        self._write({"kind": "marker", "name": name, "at": at.isoformat(timespec="milliseconds")})

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None

    def _write(self, row: dict) -> None:
        if self._file:
            self._file.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._file.flush()
