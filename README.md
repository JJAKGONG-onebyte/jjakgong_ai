# 짝공 AI 서버 (집중 감지)

브라우저가 MediaPipe로 뽑은 얼굴 특징값을 WebSocket으로 받아 집중 상태를 판정하고,
캐릭터 반응을 보내고, 끝난 이벤트를 메인 서버(Spring)에 기록한다.

- 명세: 노션 `집중 감지 WebSocket (브라우저 ↔ AI 서버)`, `집중 이벤트 기록 (내부 API)`
- 현재 판정: **규칙 기반 v0.1** (`modelVersion`: `away-gaze-rule-v0.1`, `drowsy-rule-v0.1`). 모델 A·B는 데이터를 모은 뒤 교체한다.

```
브라우저 ──features(초당 5회)──▶ AI 서버 ──reaction / reaction.clear──▶ 브라우저
                                   │
                                   └─ 이벤트가 끝나면 POST /internal/study-sessions/{id}/focus-events ─▶ 메인 서버
```

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 환경변수 (.env.example 참고)
$env:FOCUS_STREAM_SECRET="local-dev-secret-local-dev-secret-1234"
$env:INTERNAL_API_KEY="local-test-key"
$env:MAIN_SERVER_URL="http://localhost:8080"
$env:TIME_SOURCE="client"         # 시뮬레이터 빠른 재생용. 운영은 server
$env:FEATURE_LOG_DIR="data/raw"

uvicorn app.main:app --reload --port 8000
```

| 환경변수 | 설명 |
|---|---|
| `FOCUS_STREAM_SECRET` | focusStream 토큰 서명 키. **메인 서버와 같은 값**, 32바이트 이상 |
| `INTERNAL_API_KEY` | 메인 서버 내부 API 키. **메인 서버와 같은 값** |
| `MAIN_SERVER_URL` | 메인 서버 주소 |
| `TIME_SOURCE` | `server`: AI 서버 수신 시각 기준(운영) / `client`: 브라우저 timestamp 기준(시뮬레이터) |
| `FEATURE_LOG_DIR` | 특징값 로그 폴더. 비우면 저장 안 함 |

## 테스트

```bash
pytest                                   # 41개: 판정(담당별), WebSocket 흐름, 메인 서버 호출
python -m tools.simulator --scenario drowsy --session-id 1
python -m tools.simulator --scenario away --false-positive
```

시뮬레이터 시나리오: `focused`, `drowsy`, `away`, `gaze`.
Spring과 붙여 볼 때는 트래킹 ON으로 학습을 시작하고 1~2분 지난 뒤 그 `sessionId`로 실행한다.
(빠른 재생은 '지금 − 시나리오 길이'부터 시각을 만들기 때문에, 세션 시작 이전 시각이 되면 메인 서버가 400을 준다)

## 판정 규칙 (v0.1)

판정은 담당자별 파일로 나뉘어 있다. 담당과 협업 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md) 참고.

| 상태 | 파일 (담당) | 규칙 |
|---|---|---|
| `AWAY` | `away_gaze.py` (성유민) | 얼굴 미검출 30초 이상. 고개가 숙여지다 사라지면 엎드림으로 보고 제외 |
| `GAZE_OFF` | `away_gaze.py` (성유민) | 화면·자료 기준 대비 고개 좌우 25°, 위 20°, 자료보다 아래 20° 초과 또는 홍채 \|x\| > 0.8 이 지속 |
| `DROWSY` | `drowsy.py` (송유진) | 최근 10초 눈 감김 비율(PERCLOS)이 강도 기준 이상으로 지속. 눈 기준값은 화면/자료 자세 중 가까운 쪽 |
| 엎드림 | 판단: `away_gaze.py` / 처리: `drowsy.py` | LOW: 반응 안 함 / NORMAL: 엎드리기 직전 PERCLOS ≥ 0.5일 때만 졸음 / HIGH: 졸음 |
| `UNKNOWN` | `session.py` | 기준값이 없거나 휴식 중이면 판정하지 않음 |

| 강도 | 점수 기준 | 지속 시간 |
|---|---|---|
| LOW | 0.9 | 60초 |
| NORMAL | 0.8 | 30초 |
| HIGH | 0.7 | 15초 |

공통 처리 (`detector.py`)
- 우선순위 AWAY > DROWSY > GAZE_OFF, 반응은 한 번에 하나.
- 반응 중 조건이 2초 이상 풀리면 복귀(`reaction.clear` RECOVERED)로 보고 이벤트를 기록한다.
- 버튼으로 닫은 반응은 같은 종류를 지속 시간만큼 다시 띄우지 않는다.
- 이벤트 시각은 조건이 **시작된 시각 ~ 풀린 시각**이다.
- `featureSample`은 반응 직전 30초의 캘리브레이션 대비 변화량이고, 모든 이벤트에 붙인다.
  - 오탐 버튼: `falsePositive: true`, `correctedLabel: FOCUSED`
  - 확인 버튼: `falsePositive: false`, `correctedLabel: 원래 라벨`
  - 버튼 없이 풀림·휴식·종료: `correctedLabel: null`

## 데이터 수집

`FEATURE_LOG_DIR/날짜/session-{id}-user-{id}-{시각}.jsonl`에 한 줄씩 저장한다.
영상은 없고 수치만 있다. 저장소에 올리지 않는다 (`.gitignore`의 `data/`).

```jsonl
{"kind": "frame", "at": "...", "features": {...}, "active": null}
{"kind": "label", "eventType": "DROWSY", "startedAt": "...", "endedAt": "...", "falsePositive": true, "correctedLabel": "FOCUSED"}
{"kind": "marker", "name": "pause", "at": "..."}
```

## 메인 서버와의 계약

**focusStream 토큰** (메인 서버가 학습 시작·트래킹 ON 응답에서 발급)

| 항목 | 값 |
|---|---|
| 알고리즘 / 키 | HS256 / `FOCUS_STREAM_SECRET` |
| 클레임 | `type: "FOCUS_STREAM"`, `sessionId`, `userId`, `focusSensitivity`, `exp` |
| 접속 | `ws://{AI 서버}/ws/focus?token=...` |
| 오류 | 토큰 없음·만료·서명 오류·type 불일치 → 종료 코드 4001 |

**AI 서버가 부르는 내부 API** (헤더 `X-Internal-Api-Key`)

| API | 용도 | 상태 |
|---|---|---|
| `POST /internal/study-sessions/{id}/focus-events` | 이벤트 기록 | 메인 서버 구현 완료 |
| `GET /internal/study-sessions/{id}/calibration` | 기준값 조회 (없으면 캘리브레이션 요청) | 미구현 → 실패 시 캘리브레이션 진행 |
| `POST /internal/study-sessions/{id}/calibration` | 기준값 저장 | 미구현 → 실패해도 감지는 계속 |

## 구조

```
app/
  main.py                FastAPI 앱, /ws/focus, /health                       송유진
  session.py             연결 하나의 메시지 처리                               송유진
  auth.py                focusStream 토큰 검증                                 송유진
  main_server.py         메인 서버 내부 API 호출 (재시도 포함)                 송유진
  feature_log.py         데이터 수집용 JSONL 로그                              송유진
  detection/
    away_gaze.py         자리 이탈·시선 이탈·엎드림 판단 (→ 모델 A)            성유민
    drowsy.py            졸음 판정 (→ 모델 B)                                  송유진
    detector.py          판정 조립: 지속 시간·우선순위·쿨다운·featureSample    공통
    base.py              판정기 사이 형식 (FrameContext 등)                    공통
    thresholds.py        공통 기준값 (단속 강도 등)                            공통
    calibration.py       기준값 계산                                           성유민
tools/simulator.py       브라우저 없이 시험하는 가짜 클라이언트                송유진
tests/                   test_away_gaze(성유민) / test_drowsy(송유진) / 나머지 공통
```
