"""시각은 메인 서버와 같은 형식(오프셋 없는 KST ISO 8601)으로 주고받는다."""
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)


def parse_client_time(value: str) -> datetime:
    """브라우저 timestamp. 오프셋이 있으면 KST로 바꾸고, 없으면 KST로 본다."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(KST).replace(tzinfo=None)
    return parsed


def to_iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")
