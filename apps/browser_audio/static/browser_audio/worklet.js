// Bounded PCM capture only. The audio graph outputs silence, never microphone feedback.
class PrivateCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frames = 0;
    this.active = sampleRate === 8000;
    this.paused = false;
    this.port.onmessage = ({data}) => {
      if (!this.active) return;
      if (data === "pause" || data === "resume") {
        this.paused = data === "pause";
        // The same port orders this acknowledgement after all earlier PCM.
        this.port.postMessage({state: this.paused ? "paused" : "recording"});
      } else {
        this.active = false;
      }
    };
  }
  process(inputs) {
    if (!this.active) return false;
    if (this.paused) return true;
    const input = inputs[0]?.[0];
    if (!input) return true;
    const count = Math.min(input.length, 80000 - this.frames);
    const pcm = new Int16Array(count);
    for (let i = 0; i < count; i++) {
      const value = Number.isFinite(input[i]) ? Math.max(-1, Math.min(1, input[i])) : 0;
      pcm[i] = Math.round(value * (value < 0 ? 32768 : 32767));
    }
    this.frames += count;
    this.port.postMessage(pcm, [pcm.buffer]);
    if (this.frames >= 80000) { this.active = false; return false; }
    return true;
  }
}
registerProcessor("private-capture", PrivateCapture);
