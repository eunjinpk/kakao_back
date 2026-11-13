#!/usr/bin/env bash
# nest.proto → Python gRPC 코드 생성
# 레포 루트에서 실행: bash scripts/gen_proto.sh
set -euo pipefail
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -I. \
  --python_out=. --grpc_python_out=. \
  app/ai/stt/proto/nest.proto
echo "생성 완료: app/ai/stt/proto/nest_pb2.py, nest_pb2_grpc.py"
