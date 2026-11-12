"""
LLM 의도 분류 평가 — 테스트셋으로 정확도, 혼동행렬, 오경보를 본다.

사용법 (레포 루트에서):
    python -m scripts.eval_intent                      # .env 의 LLM_PROVIDER 사용
    python -m scripts.eval_intent --provider openai    # GPT-4o-mini
    python -m scripts.eval_intent --provider mock      # 키워드 규칙 (비교 기준선)

결과: 화면 출력 + tmp/eval_<provider>_<시각>.csv (문장별 예측)
"""
import argparse
import asyncio
import csv
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.ai.classifier import make_classifier
from app.ai.intents import LLM_INTENTS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SET = ROOT / "tests" / "data" / "intent_testset.csv"
EMERGENCY = {"FIRE", "POWER_OUT"}


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["text"].strip()]


async def run(rows: list[dict], provider: str, concurrency: int) -> list[dict]:
    clf = make_classifier(provider)
    sem = asyncio.Semaphore(concurrency)

    async def one(r):
        async with sem:
            t0 = time.perf_counter()
            pred = await clf.classify(r["text"])
            return {**r, "pred": pred, "ms": round((time.perf_counter() - t0) * 1000)}

    return await asyncio.gather(*(one(r) for r in rows))


def report(results: list[dict]) -> None:
    labels = list(LLM_INTENTS)
    n = len(results)
    correct = sum(r["gold"] == r["pred"] for r in results)
    print(f"\n정확도: {correct}/{n} = {correct / n:.1%}")
    print(f"평균 응답 시간: {sum(r['ms'] for r in results) / n:.0f} ms")

    # 혼동행렬 (행=정답, 열=예측)
    cm = Counter((r["gold"], r["pred"]) for r in results)
    short = {l: l[:5] for l in labels}
    print("\n혼동행렬 (행=정답, 열=예측)")
    print(" " * 13 + "".join(f"{short[l]:>7}" for l in labels))
    for g in labels:
        print(f"{g:>12} " + "".join(f"{cm[(g, p)]:>7}" for p in labels))

    print("\nintent별 정밀도 / 재현율")
    for l in labels:
        tp = cm[(l, l)]
        pred_n = sum(cm[(g, l)] for g in labels)
        gold_n = sum(cm[(l, p)] for p in labels)
        prec = tp / pred_n if pred_n else 0
        rec = tp / gold_n if gold_n else 0
        print(f"  {l:>12}  정밀도 {prec:5.0%}  재현율 {rec:5.0%}  (정답 {gold_n}개)")

    # 오경보: 정답이 NONE 인데 무언가를 추천 / 비상이 아닌데 비상으로 추천
    false_alarm = [r for r in results if r["gold"] == "NONE" and r["pred"] != "NONE"]
    false_emergency = [r for r in results if r["gold"] not in EMERGENCY and r["pred"] in EMERGENCY]
    missed_emergency = [r for r in results if r["gold"] in EMERGENCY and r["pred"] != r["gold"]]
    print(f"\n오경보 (NONE → 추천): {len(false_alarm)}건")
    for r in false_alarm:
        print(f"   - [{r['pred']}] {r['text']}  ({r['note']})")
    print(f"비상 오경보 (비상 아님 → FIRE/POWER_OUT): {len(false_emergency)}건")
    for r in false_emergency:
        print(f"   - [{r['gold']}→{r['pred']}] {r['text']}")
    print(f"비상 놓침 (FIRE/POWER_OUT 을 다른 것으로): {len(missed_emergency)}건")
    for r in missed_emergency:
        print(f"   - [{r['gold']}→{r['pred']}] {r['text']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default=None, help="openai | mock (기본: .env LLM_PROVIDER)")
    ap.add_argument("--testset", type=Path, default=DEFAULT_SET)
    ap.add_argument("--concurrency", type=int, default=5)
    args = ap.parse_args()

    from app.ai import config

    provider = args.provider or config.LLM_PROVIDER
    rows = load(args.testset)
    print(f"테스트셋 {len(rows)}문장 · 분류기 {provider}")
    results = asyncio.run(run(rows, provider, args.concurrency))
    report(results)

    out = ROOT / "tmp" / f"eval_{provider}_{datetime.now():%m%d_%H%M}.csv"
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "gold", "pred", "ms", "note"])
        w.writeheader()
        for r in results:
            w.writerow({k: r[k] for k in w.fieldnames})
    print(f"\n문장별 결과: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
