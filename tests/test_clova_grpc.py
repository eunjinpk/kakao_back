"""
CLOVA gRPC 클라이언트를 로컬 가짜 서버로 검증 (실제 키 불필요).
- 첫 메시지가 CONFIG(JSON) 인지
- 오디오가 DATA 로 그대로 가는지
- 종료 시 epFlag=true 를 보내는지
- 응답 JSON 이 transcript 콜백으로 오는지

    pytest -q tests/test_clova_grpc.py
"""
import asyncio
import json

import grpc

from app.ai.stt.clova import ClovaStreamSession
from app.ai.stt.proto import nest_pb2, nest_pb2_grpc


class FakeNest(nest_pb2_grpc.NestServiceServicer):
    def __init__(self):
        self.requests = []
        self.metadata = None

    async def recognize(self, request_iterator, context):
        self.metadata = dict(context.invocation_metadata())
        audio = 0
        async for req in request_iterator:
            self.requests.append(req)
            if req.type == nest_pb2.RequestType.DATA:
                audio += len(req.data.chunk)
                extra = json.loads(req.data.extra_contents)
                if audio >= 3200 and not getattr(self, "_sent", False):
                    self._sent = True
                    yield nest_pb2.NestResponse(contents=json.dumps(
                        {"responseType": ["transcription"], "transcription": {"text": "화재가 발생했습니다"}},
                        ensure_ascii=False))
                if extra.get("epFlag"):
                    yield nest_pb2.NestResponse(contents=json.dumps(
                        {"responseType": ["transcription"], "transcription": {"text": "대피해 주십시오"}},
                        ensure_ascii=False))
                    return


def test_clova_stream_against_fake_server():
    async def go():
        server = grpc.aio.server()
        fake = FakeNest()
        nest_pb2_grpc.add_NestServiceServicer_to_server(fake, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()

        got = []

        async def on_t(text, final):
            got.append((text, final))

        s = ClovaStreamSession(on_t, secret_key="TEST", host=f"127.0.0.1:{port}", secure=False)
        await s.start()
        for _ in range(3):
            await s.feed(b"\x01\x00" * 800)  # 50ms 프레임
        await asyncio.sleep(0.3)
        await s.close()
        await server.stop(None)
        return fake, got

    fake, got = asyncio.run(go())
    first = fake.requests[0]
    assert first.type == nest_pb2.RequestType.CONFIG
    cfg = json.loads(first.config.config)
    assert cfg["transcription"]["language"] == "ko"
    data = [r for r in fake.requests if r.type == nest_pb2.RequestType.DATA]
    assert sum(len(r.data.chunk) for r in data) == 4800
    assert json.loads(data[-1].data.extra_contents)["epFlag"] is True
    assert fake.metadata["authorization"] == "Bearer TEST"
    assert got == [("화재가 발생했습니다", True), ("대피해 주십시오", True)]
