# 세이프큐 백엔드

공연장 실시간 다국어 비상안내 시스템 · 팀 오롯이닿다
개발자 A: 정하민 (Core/송출) · 개발자 B: 박은진 (AI 파이프라인)

> **현재 상태: W1 더미 서버.** DB 없이 메모리로 돕니다.
> 프론트엔드는 지금 바로 연동을 시작할 수 있습니다.
> W1 후반에 저장소만 SQLAlchemy 로 교체하며, **응답 모양은 바뀌지 않습니다.**

---

## 실행

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- 서버 `http://localhost:8000`
- **API 문서 `http://localhost:8000/docs`** ← 여기서 버튼으로 직접 테스트 가능
- 테스트 계정 `operator` / `test1234`

---

## 프론트엔드 연동 요약

### 1. 로그인 (오퍼레이터 화면만)

```js
const r = await fetch('http://localhost:8000/api/admin/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'operator', password: 'test1234' }),
});
const { access_token } = await r.json();
// 이후 오퍼레이터 API 는 모두 헤더에 Authorization: Bearer ${access_token}
```

### 2. 관객 화면 — SSE 구독 (인증 없음)

```js
const es = new EventSource('http://localhost:8000/api/stream/notices');

es.addEventListener('notice_update', (e) => {
  const d = JSON.parse(e.data);
  // d.action         "CREATED" | "CORRECTED" | "ENDED"
  // d.intent_type    "FIRE" | "POWER_OUT" | "PAUSE" | "DELAY" |
  //                  "INTERMISSION" | "ETIQUETTE" | "INFO"
  // d.pictogram_code "fire_exit"            → SVG 파일 선택
  // d.text_ko / text_zh / text_en
  // d.trigger_haptic true 면 진동
  // d.direction      "LEFT" | "RIGHT" | "FRONT" | "REAR" | null  → 화살표
  // d.expires_at     ISO 시각 또는 null      → 타이머. 프론트가 카운트다운
  // d.revision       0보다 크면 "변경됨" 표시
});

es.addEventListener('heartbeat', () => { /* 연결 살아있음 */ });
```

**끊김 복구는 브라우저가 알아서 합니다.** 다시 붙을 때 `Last-Event-ID` 를 자동으로
보내고, 서버가 그 뒤 이벤트를 전부 다시 보냅니다. 거기에 더해, 탭이 다시 활성화되거나
네트워크가 복구될 때 `GET /api/notices/active` 를 한 번 호출해 화면을 맞추면 확실합니다.

### 3. 오퍼레이터 화면 — WebSocket (오디오 올리기 + 자막·추천 받기)

```js
// 인증 없음 (11/10 회의: 로그인 제외)
const ws = new WebSocket('ws://localhost:8000/api/ws/operator');
ws.binaryType = 'arraybuffer';
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  switch (msg.type) {
    case 'connected':  /* 오디오 전송 시작 */ break;
    case 'transcript': /* msg.text, msg.is_final → 실시간 자막 */ break;
    case 'suggestion': /* msg.intent_type, msg.templates[] → 추천 팝업, 하나 골라 POST /api/notices */ break;
    case 'error':      /* msg.code, msg.message */ break;
  }
};
// 오디오: 16kHz mono PCM16 바이너리 (static/pcm-worklet.js 사용)
```

자세한 이벤트 명세: **[docs/WS_OPERATOR.md](docs/WS_OPERATOR.md)** · 마이크 테스트: `http://localhost:8000/static/mic_test.html`
`.env` 의 `STT_PROVIDER=mock` 이면 키 없이도 샘플 자막과 추천이 옵니다.

---

## API

### 오퍼레이터 (`Authorization: Bearer <token>` 필수)

| Method | Endpoint | 역할 |
|---|---|---|
| POST | `/api/admin/login` | 로그인 |
| GET | `/api/templates` | 템플릿 목록 (`templates`, `by_intent` 둘 다 반환) |
| POST | `/api/notices` | 공지 승인·송출 |
| PATCH | `/api/notices/{id}` | 정정 |
| POST | `/api/notices/{id}/end` | 종료 |
| WS | `/api/ws/operator` | 오디오 업로드 + 자막·추천 수신 ([명세](docs/WS_OPERATOR.md)) |

### 관객 (인증 없음)

| Method | Endpoint | 역할 |
|---|---|---|
| GET | `/api/notices/active` | 현재 유효한 공지 (화면 동기화용) |
| GET | `/api/stream/notices` | SSE 구독 |

### 공통

| Method | Endpoint | 역할 |
|---|---|---|
| GET | `/api/health` | 서버 상태, 접속자 수 |
| GET | `/api/intents` | intent 목록 (코드에 박지 말고 여기서 받아가세요) |

---

## 공지 보내기 예시

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"operator","password":"test1234"}' | jq -r .access_token)

# 화재 대피 (방향 필수)
curl -X POST localhost:8000/api/notices -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"intent_type":"FIRE","template_code":"FIRE_EVAC","direction":"LEFT"}'

# 인터미션 15분 (타이머 필수)
curl -X POST localhost:8000/api/notices -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"intent_type":"INTERMISSION","template_code":"INTERMISSION","duration_min":15}'

# 자유 입력
curl -X POST localhost:8000/api/notices -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"intent_type":"INFO","pictogram_code":"info","text_ko":"좌석 안내","text_zh":"座位指引"}'
```

---

## 템플릿 문구 고치기

`data/templates.json` 만 고치고 서버를 다시 켜면 됩니다. **코드를 몰라도 됩니다.**

```json
{
  "template_code": "FIRE_EVAC",      ← 바꾸지 마세요 (코드가 참조함)
  "intent_type": "FIRE",             ← 바꾸지 마세요
  "pictogram_code": "fire_exit",     ← 디자인팀 SVG 파일명과 같아야 함
  "needs_direction": true,           ← true 면 송출 시 방향을 꼭 골라야 함
  "needs_duration": true,            ← true 면 송출 시 분(分)을 꼭 입력해야 함
  "text_ko": "비상구로 이동하세요",    ← 여기를 고치세요
  "text_zh": "请前往紧急出口",
  "text_en": "Move to the emergency exit"
}
```

중국어는 **초안입니다. 검수가 필요합니다.**

---

## intent 목록 (기획서 섹션 4)

| intent | LLM 분류 | 템플릿 | 우선순위 |
|---|---|---|---|
| FIRE | O | O | 1 |
| POWER_OUT | O | O | 2 |
| PAUSE | O | O | 3 |
| DELAY | O | O | 4 |
| INTERMISSION | O | O | 5 |
| ETIQUETTE | O | O | 6 |
| INFO | X | O | – |
| NONE | O | X | – |

코드에서 `LLM_INTENTS` 와 `TEMPLATE_INTENTS` 로 분리해 두었습니다 (`app/store.py`).

---

## 기획서와 다른 점 3가지 (의도적)

프론트엔드가 **몰라도 깨지지 않는** 추가 필드입니다. 쓰면 기능이 하나 더 되고,
안 쓰면 그냥 무시됩니다.

| | 기획서 | 여기 | 이유 |
|---|---|---|---|
| SSE `id` | 공지 id (`105`) | **이벤트 번호** | 같은 공지의 CREATED 와 ENDED 가 같은 번호면 재접속 복구가 깨집니다. 브라우저가 자동으로 쓰는 값이라 프론트는 신경 쓸 필요 없습니다 |
| `expires_at` | SSE 예시에 없음 | **추가** | DB 에는 있는데 SSE 로 안 보내면 타이머(기능 ⑦)를 관객 화면에 띄울 수 없습니다 |
| `direction`, `revision` | 없음 | **추가** | 대피 화살표(기능 ③)와 "변경됨" 표시(기능 ⑥)에 필요합니다 |

---

## 폴더 구조

```
app/
├── main.py              FastAPI 앱, CORS, health, intents
├── store.py             메모리 저장소 ← W1 후반에 DB 로 교체할 유일한 파일
├── hub.py               SSE 구독자 + 오퍼레이터 WebSocket 관리
└── routers/
    ├── auth.py          로그인 (W1 후반 bcrypt + JWT 로 교체)
    ├── notices.py       송출 / 정정 / 종료 / 조회
    ├── stream.py        관객 SSE
    └── operator.py      오퍼레이터 WebSocket (개발자 B)

app/ai/                  AI 파이프라인 (개발자 B) → docs/AI_PIPELINE.md
data/templates.json      템플릿 문구 (개발자 B 관리)
```

---

## 남은 일 (개발자 A)

- [ ] W1: `store.py` → SQLAlchemy 로 교체 (`Users`, `Notices`, `Notice_History`)
- [ ] W1: `auth.py` → bcrypt 해시 + JWT 로 교체
- [ ] W2: 개발 서버 배포
- [ ] 논의: `show_id`(공연 회차 구분) 추가 — 두 공연이 동시에 돌면 공지가 섞입니다
- [ ] 논의: `Notice_History` 에 `snapshot` JSON 추가 — 지금 설계는 한국어 정정만 기록됩니다
