// AudioWorklet: 마이크 입력(보통 44.1/48kHz Float32) → 16kHz mono PCM16 (little-endian)
// 100ms(1600샘플 = 3,200바이트)마다 메인 스레드로 보낸다.
// 프론트 오퍼레이터 화면에서 그대로 가져다 써도 된다.
class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate; // sampleRate: AudioWorkletGlobalScope 전역
    this.frameSamples = 1600; // 100ms
    this.out = new Int16Array(this.frameSamples);
    this.outIdx = 0;
    this.acc = 0; // 다운샘플링 누적값
    this.accCount = 0;
    this.pos = 0; // 다음 출력 샘플 경계까지 남은 입력 샘플
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0]; // mono: 첫 채널만 사용

    for (let i = 0; i < ch.length; i++) {
      // 구간 평균으로 다운샘플링 (간단한 저역통과 효과)
      this.acc += ch[i];
      this.accCount++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        let s = this.acc / this.accCount;
        this.acc = 0;
        this.accCount = 0;
        s = Math.max(-1, Math.min(1, s));
        this.out[this.outIdx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.outIdx === this.frameSamples) {
          this.port.postMessage(this.out.buffer, [this.out.buffer]);
          this.out = new Int16Array(this.frameSamples);
          this.outIdx = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PcmWorklet);
