# AI 파이프라인 (개발자 B) — W1

현장 음성 → **CLOVA Speech 실시간 스트리밍** → 텍스트 버퍼(최근 10초) → **GPT-4o-mini** 의도 분류 → 오퍼레이터 추천

## 파일

```
app/
├── routers/operator.py      오퍼레이터 WebSocket (/api/ws/operator, 인증 없음)
└── ai/
    ├── config.py            .env 설정
    ├── intents.py           intent 목록·우선순위·설명(프롬프트용)
    ├── buffer.py            최근 N초 텍스트 버퍼
    ├── classifier.py        GPT-4o-mini 분류기 + 프롬프트 v1 (+ 개발용 키워드 분류기)
    ├── pipeline.py          세션 하나의 흐름: 오디오 → STT → 버퍼 → 분류 → 추천
    └── stt/
        ├── __init__.py      STT 세션 인터페이스 (업체 교체 가능)
        ├── clova.py         CLOVA gRPC 스트리밍
        ├── mock.py          개발용 가짜 STT
        └── proto/           nest.proto + 생성 코드
static/
├── mic_test.html            마이크 테스트 페이지 (개발용)
└── pcm-worklet.js           16kHz PCM16 변환 AudioWorklet (프론트 재사용 가능)
scripts/
├── eval_intent.py           분류 평가 (정확도·혼동행렬·오경보)
├── clova_file_test.py       CLOVA 단독 테스트 (WAV 파일 → 인식 결과)
└── gen_proto.sh             nest.proto → Python 코드 생성
tests/
├── test_ai_pipeline.py      버퍼·분류기·파이프라인
├── test_clova_grpc.py       CLOVA 클라이언트 (로컬 가짜 gRPC 서버)
├── test_operator_ws.py      WebSocket 통합
└── data/intent_testset.csv  분류 테스트셋 61문장
```

## 실행 순서

```bash
pip install -r requirements.txt
cp .env.example .env          # 처음 한 번
pytest -q                     # 키 없이 전부 통과해야 함
uvicorn app.main:app --reload --port 8000
# http://localhost:8000/static/mic_test.html
```

### 1) 키 없이 (mock)
`.env`: `STT_PROVIDER=mock`, `LLM_PROVIDER=mock` → 마이크를 켜면 3초마다 샘플 문장 + 추천.
프론트가 오퍼레이터 화면을 붙일 때 이 모드를 쓰면 된다.

### 2) GPT-4o-mini 평가
`.env`: `OPENAI_API_KEY=sk-...`
```bash
python -m scripts.eval_intent --provider mock     # 기준선 (키워드 규칙)
python -m scripts.eval_intent --provider openai   # GPT-4o-mini
```
- 볼 것: **오경보(NONE → 추천)**, **비상 놓침**, 혼동행렬에서 자주 섞이는 쌍
- 문장별 결과는 `tmp/eval_*.csv` (엑셀로 열림)
- 프롬프트는 `app/ai/classifier.py` 의 `build_system_prompt()`, 설명은 `app/ai/intents.py` 의 `DEFINITIONS`

### 3) CLOVA 연결
1. 네이버 클라우드 콘솔 → CLOVA Speech → **스트리밍 인식** Domain 생성 → Secret Key (Free 플랜은 스트리밍 불가)
2. **`app/ai/stt/proto/nest.proto` 를 공식 문서 파일과 대조** → 다르면 덮어쓰고 `bash scripts/gen_proto.sh`
3. `.env`: `CLOVA_SECRET_KEY=...`
4. 파일로 먼저 확인
   ```bash
   ffmpeg -i 녹음.m4a -ar 16000 -ac 1 -sample_fmt s16 test.wav
   python -m scripts.clova_file_test test.wav
   ```
5. 되면 `.env`: `STT_PROVIDER=clova` → 마이크 테스트 페이지로 실시간 확인

## 설계 메모

- **CLOVA 요금**: 요청 단위 15초 올림 과금 → 청크마다 요청하지 않고 **연결 하나로 스트리밍**.
  오디오가 30초(`STT_IDLE_TIMEOUT_SEC`) 안 오면 연결을 닫고, 다시 오면 새로 연다.
- **확실하지 않으면 NONE**: 프롬프트 규칙 + 코드에서 이상한 응답·타임아웃·오류는 전부 `NONE` → 추천 없음.
- **우선순위**: `FIRE > POWER_OUT > PAUSE > DELAY > INTERMISSION > ETIQUETTE` (프롬프트에 명시)
- **추천 대상** = `LLM_INTENTS ∩ TEMPLATE_INTENTS` (6개). `NONE` 은 템플릿 없음, `INFO` 는 LLM 이 안 뱉음.
- **템플릿 조회**: `store.templates_for_intent(intent)` (개발자 A). DB 로 바뀌어도 함수 이름 유지 합의 필요.
- **인증 없음**: 11/10 회의에서 로그인 제외.
- **픽토그램 키**: 디자인팀 확정 전. 확정되면 `data/templates.json` 의 `pictogram_code` 만 고친다 (코드 변경 없음).
- **다국어**: v0.1 은 한/중/영. 일본어는 이후 추가.
- **공연 녹음 금지**: 오디오는 저장하지 않는다. `DEBUG_SAVE_AUDIO=true` 일 때만 `tmp/recordings/` 에 저장 (gitignore 됨).
