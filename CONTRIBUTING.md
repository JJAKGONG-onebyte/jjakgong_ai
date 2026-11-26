# 협업 가이드 (AI 서버)

AI 서버는 두 사람이 같이 만든다. **각자 자기 파일만 고치고, 공통 파일은 합의 후에 바꾼다.**

## 담당 파일

| 담당 | 파일 | 내용 |
|---|---|---|
| 성유민 | `app/detection/away_gaze.py`, `tests/test_away_gaze.py` | 얼굴/자리 이탈, 시선 이탈, 엎드림 판단 (모델 A), 측정 불안정(`UNKNOWN`) 판정 |
| 성유민 | `app/detection/calibration.py` | 캘리브레이션 기준값 계산 (`View` 형식을 바꿀 때는 합의) |
| 송유진 | `app/detection/drowsy.py`, `tests/test_drowsy.py` | 졸음 판정 (모델 B) |
| 송유진 | `app/main.py`, `app/session.py`, `app/auth.py`, `app/main_server.py`, `app/feature_log.py`, `tools/` | WebSocket, 토큰, 메시지 처리, 이벤트 기록, 데이터 로그 |
| 송유진 | 학습 코드 공통부 (추가 예정) | JSONL 로그 → 학습용 데이터 변환, 평가 지표. 모델 학습은 각자 |
| 송유진 | 배포 파일 (추가 예정) | Dockerfile, 환경변수. 서버 위치는 메인 서버 배포 담당과 협의 |
| **공통 (합의)** | `app/detection/base.py`, `detector.py`, `thresholds.py`, `tests/helpers.py`, `tests/test_detector.py` | 판정기 사이 형식, 지속 시간·우선순위·쿨다운, 공통 기준값 |

캘리브레이션은 계산 방식(`calibration.py`)을 성유민이 정하고, 메시지 처리(`session.py`)와 저장·조회 API는 송유진이 맞춘다.

## 이 레포 밖의 AI 관련 작업

| 담당 | 작업 | 위치 |
|---|---|---|
| 성유민 | MediaPipe 특징값 계산 + 캘리브레이션 안내 (프론트에서 쓰는 JS 모듈) | 프론트 레포 |
| 성유민 | 데이터 수집 도구 (브라우저와 같은 계산 방식) | 프론트 레포 또는 이 레포 `tools/` |
| 송유진 | 데이터 수집 계획·라벨 기준 | 노션 |
| 송유진 | 캘리브레이션 기준값 저장·조회 내부 API (명세 9, 10번) | 백엔드 레포 |
| 송유진 | `focusStream` 토큰 발급 | 백엔드 레포 |
| 프론트 (학습화면 담당) | WebSocket 연결, 캐릭터 반응·버튼 표시 | 프론트 레포 |
| 팀 전원 | 데이터 수집 참여 | - |

## 판정기 계약 (base.py)

판정기는 **"이 프레임에서 조건이 성립하는가"만** 답한다. 지속 시간, 반응 시작/종료, 우선순위, 쿨다운, featureSample은 `detector.py`가 처리한다.

```python
ctx: FrameContext
  .now          지금 프레임 시각
  .features     지금 프레임 특징값 (명세 features 구조 그대로)
  .frames       최근 40초 프레임 (오래된 순, 지금 포함)
  .calibration  기준값 (screen, material)
  .sensitivity  단속 강도 (score_threshold, hold_seconds, prone_policy)
  .recent(sec)  최근 sec초 프레임
  .view_for(f)  화면/자료 중 가까운 기준 자세

AwayGazeJudge.evaluate(ctx) -> AwayGazeResult(away, gaze_off, prone)   # 성유민
DrowsyJudge.evaluate(ctx, prone) -> bool                                # 송유진
각 판정기.hold_seconds(event_type, sensitivity) -> 반응까지 지속 시간
각 판정기.reset()                                                        # 휴식·종료 시 호출
```

모델로 바꿀 때도 이 계약은 그대로 두고, 판정기 **안쪽**만 바꾼다.
- 성유민: `AwayGazeJudge._gaze_off()` 등 규칙 → 모델 A 확률 ≥ `ctx.sensitivity.score_threshold`
- 송유진: `DrowsyJudge.score()` → 모델 B 확률

## 특징값 정의 (브라우저 ↔ AI 서버, 반드시 일치)

브라우저(MediaPipe) 계산은 성유민 담당이다. 아래 정의가 바뀌면 판정이 틀어지므로 바꿀 때 꼭 공유한다.

| 값 | 단위·범위 | 부호 |
|---|---|---|
| `headYaw` | 도 | 오른쪽(사용자 기준)이 + |
| `headPitch` | 도 | **고개를 숙이면 −** (자료 볼 때 약 −25 ~ −30) |
| `headRoll` | 도 | 오른쪽으로 기울이면 + |
| `left/rightEyeOpenness` | 0~1 | 클수록 크게 뜸 |
| `irisOffsetX/Y` | −1~1 | 눈 중앙이 0 |
| `mouthOpenness` | 0~1 | 클수록 크게 벌림 |
| `faceSize` | 0~1 | 화면 대비 얼굴 크기 |

얼굴이 없으면 `facePresent: false`이고 나머지는 모두 `null`. 초당 5회.

## 작업 방식

백엔드 레포와 같은 규칙을 쓴다.

**브랜치**
- `main`: 배포용. `develop`에서만 머지한다.
- `develop`: 개발 통합 브랜치. **기본 브랜치**로 둔다.
- `feature/{이슈번호}-{내용}`: 작업 브랜치 (예: `feature/3-drowsy-yawn`). `develop`에서 따고 `develop`으로 PR. `#`은 쓰지 않는다.

**순서**
1. 이슈 작성 (템플릿: Feature / Bug / Chore)
2. `git switch develop` → `git pull origin develop` → `git switch -c feature/{번호}-{내용}`
3. 커밋: `feat:`, `fix:`, `chore:`, `test:`, `docs:` + 한글 설명 + `(#이슈번호)`
4. `pytest` 전체 통과 확인 후 push, PR (템플릿 작성, `Resolves: #번호`)
5. 리뷰 후 **Create a merge commit**으로 머지, 브랜치 삭제

**리뷰**
- 자기 담당 파일만 바꾼 PR: 상대방 확인 후 머지 (승인 1명)
- 공통 파일이나 메시지·특징값 형식을 바꾼 PR: **상대방 승인 필수**
- 기준값만 바꾸는 PR도 이유(어떤 데이터로 봤는지)를 적는다

## 데이터 수집

`FEATURE_LOG_DIR`에 쌓이는 JSONL은 개인 학습 데이터라 **저장소에 올리지 않는다** (`.gitignore`의 `data/`).
모은 파일은 팀 드라이브 등 따로 정한 곳에서 공유한다.
