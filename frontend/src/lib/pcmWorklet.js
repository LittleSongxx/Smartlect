// AudioWorklet 处理器：浏览器原生采样率线性插值降采样到 16kHz，
// 转 Int16 PCM 后按 100ms/帧下发；附带 rms 音量事件供 UI 显示。
// 该文件运行在 AudioWorklet 线程，不能 import 项目内其他模块。
class PcmCollector extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.inputRate = opts.inputRate || sampleRate;
    this.targetRate = 16000;
    this.ratio = this.inputRate / this.targetRate;
    this.samplesPerChunk = Math.floor((this.targetRate * 100) / 1000);
    this.buf = new Int16Array(this.samplesPerChunk);
    this.cursor = 0;
    this.srcIdx = 0;
  }
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    let sum = 0;
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
    this.port.postMessage({ type: "level", rms: Math.sqrt(sum / input.length) });
    while (this.srcIdx < input.length) {
      const i0 = Math.floor(this.srcIdx);
      const frac = this.srcIdx - i0;
      const s0 = input[i0] || 0;
      const s1 = input[i0 + 1] || s0;
      const s = Math.max(-1, Math.min(1, s0 + (s1 - s0) * frac));
      this.buf[this.cursor++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.cursor === this.buf.length) {
        this.port.postMessage({ type: "pcm", data: this.buf.buffer.slice(0) });
        this.cursor = 0;
      }
      this.srcIdx += this.ratio;
    }
    this.srcIdx -= input.length;
    return true;
  }
}
registerProcessor("pcm-collector", PcmCollector);
