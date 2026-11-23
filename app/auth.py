"""메인 서버가 발급한 focusStream 토큰 검증.

토큰 계약 (메인 서버와 동일해야 함)
- 알고리즘: HS256, 비밀키: FOCUS_STREAM_SECRET
- 클레임: type="FOCUS_STREAM", sessionId(Long), userId(Long), focusSensitivity(LOW/NORMAL/HIGH), exp
"""
from dataclasses import dataclass

import jwt

TOKEN_TYPE = "FOCUS_STREAM"
SENSITIVITIES = ("LOW", "NORMAL", "HIGH")


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class StreamClaims:
    session_id: int
    user_id: int
    focus_sensitivity: str


def verify_token(token: str | None, secret: str) -> StreamClaims:
    if not token:
        raise InvalidToken("토큰이 없습니다.")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp"]})
    except jwt.PyJWTError as e:
        raise InvalidToken(str(e)) from e

    if payload.get("type") != TOKEN_TYPE:
        raise InvalidToken("focusStream 토큰이 아닙니다.")
    try:
        session_id = int(payload["sessionId"])
        user_id = int(payload["userId"])
    except (KeyError, TypeError, ValueError) as e:
        raise InvalidToken("sessionId/userId가 올바르지 않습니다.") from e

    sensitivity = payload.get("focusSensitivity", "NORMAL")
    if sensitivity not in SENSITIVITIES:
        sensitivity = "NORMAL"
    return StreamClaims(session_id, user_id, sensitivity)
