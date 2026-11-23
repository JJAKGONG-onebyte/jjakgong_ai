"""메인 서버(Spring) 내부 API 호출. 모든 요청에 X-Internal-Api-Key를 붙인다."""
import asyncio
import logging

import httpx

from app.detection.calibration import Calibration, View

log = logging.getLogger(__name__)
RETRY_DELAYS = (0.5, 1.0, 2.0)


class MainServerClient:

    def __init__(self, base_url: str, api_key: str, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(base_url=base_url, timeout=5.0)
        self._headers = {"X-Internal-Api-Key": api_key}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def record_event(self, session_id: int, payload: dict) -> bool:
        """POST /internal/study-sessions/{id}/focus-events. 네트워크·5xx만 재시도한다."""
        url = f"/internal/study-sessions/{session_id}/focus-events"
        for attempt, delay in enumerate((0.0, *RETRY_DELAYS)):
            if delay:
                await asyncio.sleep(delay)
            try:
                res = await self._http.post(url, json=payload, headers=self._headers)
            except httpx.HTTPError as e:
                log.warning("이벤트 기록 실패(네트워크) session=%s try=%s: %s", session_id, attempt + 1, e)
                continue
            if res.status_code < 300:
                return True
            if res.status_code < 500:
                log.error("이벤트 기록 거절 session=%s status=%s body=%s", session_id, res.status_code, res.text)
                return False
            log.warning("이벤트 기록 실패(서버) session=%s status=%s", session_id, res.status_code)
        log.error("이벤트 기록 최종 실패 session=%s payload=%s", session_id, payload)
        return False

    async def get_calibration(self, session_id: int) -> Calibration | None:
        """GET /internal/study-sessions/{id}/calibration. 없거나 실패하면 None (캘리브레이션 진행)."""
        url = f"/internal/study-sessions/{session_id}/calibration"
        try:
            res = await self._http.get(url, headers=self._headers)
        except httpx.HTTPError as e:
            log.warning("기준값 조회 실패 session=%s: %s", session_id, e)
            return None
        if res.status_code != 200:
            return None
        try:
            data = res.json()["data"]
            material = data.get("materialView")
            return Calibration(View.from_dict(data["screenView"]),
                               View.from_dict(material) if material else None)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("기준값 응답 형식 오류 session=%s: %s", session_id, e)
            return None

    async def save_calibration(self, session_id: int, calibration: Calibration, sample_count: int) -> bool:
        """POST /internal/study-sessions/{id}/calibration."""
        url = f"/internal/study-sessions/{session_id}/calibration"
        body = {
            "screenView": calibration.screen.to_dict(),
            "materialView": calibration.material.to_dict() if calibration.material else None,
            "sampleCount": sample_count,
        }
        try:
            res = await self._http.post(url, json=body, headers=self._headers)
        except httpx.HTTPError as e:
            log.warning("기준값 저장 실패 session=%s: %s", session_id, e)
            return False
        if res.status_code >= 300:
            log.warning("기준값 저장 거절 session=%s status=%s", session_id, res.status_code)
            return False
        return True
