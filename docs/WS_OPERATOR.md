# 오퍼레이터 WebSocket 명세

담당: 개발자 B · 피드백 #2~#4 반영

```
ws://localhost:8000/api/ws/operator      # 로컬
wss://<AWS 서버>/api/ws/operator          # 배포 (HTTPS 페이지에서는 wss)
```

- **인증 없음** (11/10 회의: 로그인 제외). 연결하면 바로 `connected` 가 온다.
- 오퍼레이터 화면 1개 = 연결 1개 = CLOVA 스트림 1개.
- 서버는 오디오를 **저장하지 않는다** (공연 녹음 금지).

---

## 1. 클라이언트 → 서버

| type | 형식 | 설명 |
|---|---|---|
| (오디오) | **binary** | 16kHz · mono · PCM16 little-endian · 헤더 없음. **100ms(3,200바이트) 단위 권장** |
| `ping` | `{"type": "ping"}` | 연결 유지. 20~30초마다 |

오디오 만들기: `static/pcm-worklet.js` (AudioWorklet) 를 그대로 쓰면 된다.
브라우저 기본 샘플레이트(44.1/48kHz)를 worklet 안에서 16kHz 로 바꿔 Int16 으로 보낸다.

```js
const ctx = new AudioContext();
await ctx.audioWorklet.addModule('/static/pcm-worklet.js');
const src = ctx.createMediaStreamSource(await navigator.mediaDevices.getUserMedia({ audio: true }));
const node = new AudioWorkletNode(ctx, 'pcm-worklet');
node.port.onmessage = (e) => ws.readyState === 1 && ws.send(e.data);  // ArrayBuffer
src.connect(node);
```

## 2. 서버 → 클라이언트

모든 메시지는 JSON 이고 `type` 으로 구분한다.

### `connected` — 연결·인증 성공
```json
{
  "type": "connected",
  "session_id": "3f9a1c2b7d10",
  "user": {"id": 1, "name": "오퍼레이터"},
  "stt_provider": "clova",
  "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1}
}
```
이 메시지를 받은 뒤 오디오 전송을 시작한다.

### `transcript` — 실시간 자막 (피드백 #4)
```json
{"type": "transcript", "text": "화재가 발생했습니다", "is_final": true, "ts": "2026-11-15T10:00:00+00:00"}
```
| 필드 | 설명 |
|---|---|
| `is_final: false` | 중간 결과. 화면에서 **직전 중간 결과를 덮어쓴다** |
| `is_final: true` | 확정 문장. 로그에 한 줄 추가 |

> CLOVA 스트리밍은 문장 끝을 감지(EPD)할 때 그 구간 결과를 한 번에 주기 때문에 현재는 `true` 만 온다.
> 프론트는 `false` 처리도 넣어 두면 나중에 STT 를 바꿔도 그대로 동작한다.

### `suggestion` — AI 추천
```json
{
  "type": "suggestion",
  "intent_type": "ETIQUETTE",
  "stt_text": "공연 중 사진 및 영상 촬영은 금지되어 있습니다",
  "templates": [
    {"template_code": "ETIQUETTE_PHOTO", "intent_type": "ETIQUETTE", "pictogram_code": "no_photo",
     "needs_direction": false, "needs_duration": false,
     "text_ko": "공연 중 촬영은 금지됩니다", "text_zh": "演出期间禁止拍照", "text_en": "No photography during the show", "...": "..."},
    {"template_code": "ETIQUETTE_FOOD", "...": "..."}
  ],
  "ts": "2026-11-15T10:00:03+00:00"
}
```
- `templates` = 해당 intent 의 템플릿 **전부** (`GET /api/templates` 의 항목과 같은 객체, 한/중/영). 오퍼레이터가 하나를 고른다.
- `pictogram_code` 이름은 디자인팀과 **확정 전**이다. 확정되면 `data/templates.json` 만 바뀌고 이 형식은 그대로다.
- 비상(`FIRE`, `POWER_OUT`)은 템플릿이 하나라 바로 하나만 온다.
- 고른 뒤 송출은 `POST /api/notices` (`template_code` + 필요하면 `direction` / `duration_min`).
- **관객에게는 아무것도 가지 않는다.** 오퍼레이터가 [송출] 을 눌러야 나간다.
- 같은 intent 는 **30초 안에 다시 추천하지 않는다** (`SUGGEST_COOLDOWN_SEC`).
- AI 가 확실하지 않으면(`NONE`) 아무것도 보내지 않는다.

### `error`
```json
{"type": "error", "code": "STT_ERROR", "message": "..."}
```
| code | 의미 | 연결 |
|---|---|---|
| `STT_UNAVAILABLE` | STT 시작 실패 (키 없음 등) | 유지 (자막·추천만 안 됨) |
| `STT_ERROR` | STT 처리 중 오류 | 유지. 다음 오디오에서 자동 재연결 |
| `BAD_AUDIO` | PCM16 형식 아님 (홀수 바이트) | 유지 |
| `BAD_JSON` / `UNKNOWN_TYPE` | 텍스트 메시지 형식 오류 | 유지 |

### `pong`
```json
{"type": "pong"}
```

## 3. 순서 예시

```
클라  ── connect ───────────────────────▶ 서버
클라  ◀──────────── connected ────────── 서버
클라  ── PCM 100ms ×N ─────────────────▶ 서버 ──▶ CLOVA
클라  ◀──────────── transcript ───────── 서버 ◀── CLOVA
클라  ◀──────────── suggestion ───────── 서버 (GPT-4o-mini 분류 → 템플릿 조회)
클라  ── POST /api/notices (REST) ─────▶ 서버 ──▶ 관객 SSE
```

## 4. 직접 테스트

1. `uvicorn app.main:app --reload --port 8000`
2. 브라우저에서 `http://localhost:8000/static/mic_test.html`
3. WebSocket 연결 → 마이크 시작

`.env` 에서 `STT_PROVIDER=mock` 이면 키 없이도 3초마다 샘플 문장이 transcript 로 오고 추천이 뜬다.
