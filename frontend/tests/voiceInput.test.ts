import { describe, expect, it, vi } from "vitest";
import { startVoiceInput, VoiceInputError, type VoiceInputEvent } from "../src/lib/voiceInput";

// 可编程的假 WebSocket：构造后异步自动 open（与真实浏览器握手时序一致），
// 测试侧驱动 message/close，记录上行帧
class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: FakeWebSocket[] = [];
  binaryType = "blob";
  readyState = FakeWebSocket.CONNECTING;
  sent: Array<string | ArrayBuffer> = [];
  subprotocols: string[];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string, subprotocols: string[]) {
    this.subprotocols = subprotocols.filter(Boolean);
    FakeWebSocket.instances.push(this);
    setTimeout(() => { this.readyState = FakeWebSocket.OPEN; this.onopen?.(); }, 0);
  }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.();
  }
  serverMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

// 连接即失败的独立实现（不继承自动 open，保证只触发 onerror）
class FailingWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  binaryType = "blob";
  readyState = 0;
  subprotocols: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(_url: string, subprotocols: string[]) {
    this.subprotocols = subprotocols.filter(Boolean);
    setTimeout(() => { this.onerror?.(); this.onclose?.(); }, 0);
  }
  send() { /* 不适用 */ }
  close() { /* 不适用 */ }
}

class FakeWorkletNode {
  port = { onmessage: null, close: () => undefined };
  constructor(_context: unknown, public name: string, public options: unknown) {}
  disconnect() { /* 已断开 */ }
}

class FakeAudioContext {
  closed = false;
  sampleRate = 48000;
  audioWorklet = { addModule: async () => undefined };
  createMediaStreamSource() { return { connect: () => undefined }; }
  async close() { this.closed = true; }
}

const fakeMic = () => ({ getTracks: () => [{ stop: () => undefined }] });

function deps(overrides: Record<string, unknown> = {}) {
  return {
    WebSocketCtor: FakeWebSocket as unknown as typeof WebSocket,
    AudioContextCtor: FakeAudioContext as unknown as typeof AudioContext,
    createWorkletNode: (() => new FakeWorkletNode()) as unknown as () => unknown,
    mediaDevices: { getUserMedia: async () => fakeMic() } as unknown as MediaDevices,
    workletUrl: "blob:fake-worklet",
    ...overrides,
  };
}

describe("语音输入会话封装", () => {
  it("建立连接后发送首帧身份，事件回传，stop 垫静音并发 finish", async () => {
    const events: VoiceInputEvent[] = [];
    const session = await startVoiceInput(
      { wsUrl: "ws://test/voice", token: "tok-1", buyerId: "smartlect", onEvent: (event) => events.push(event) },
      deps(),
    );
    const ws = FakeWebSocket.instances.at(-1)!;
    expect(ws.subprotocols).toEqual(["smartlect-voice", "smartlect-auth.tok-1"]);
    expect(JSON.parse(String(ws.sent[0]))).toEqual({ buyer_id: "smartlect" });
    ws.serverMessage({ type: "partial", text: "我想买" });
    ws.serverMessage({ type: "final", text: "我想买降噪耳机" });
    expect(events).toEqual([
      { type: "partial", text: "我想买" },
      { type: "final", text: "我想买降噪耳机" },
    ]);
    const stopDone = session.stop();
    // stop 先发静音尾帧（二进制 800ms = 25600 字节），再发 finish
    expect(ws.sent[1]).toBeInstanceOf(ArrayBuffer);
    expect((ws.sent[1] as ArrayBuffer).byteLength).toBe(25600);
    expect(JSON.parse(String(ws.sent[2]))).toEqual({ type: "finish" });
    ws.serverMessage({ type: "stopped", reason: "finished" });
    await stopDone;
    expect(events.at(-1)).toEqual({ type: "stopped", reason: "finished" });
    expect(ws.closed).toBe(true);
  });

  it("麦克风权限被拒绝时抛 permission 并清理连接", async () => {
    const denial = new DOMException("denied", "NotAllowedError");
    const error = await startVoiceInput(
      { wsUrl: "ws://test/voice", buyerId: "smartlect", onEvent: () => undefined },
      deps({ mediaDevices: { getUserMedia: () => Promise.reject(denial) } }),
    ).catch((err: unknown) => err);
    expect(error).toBeInstanceOf(VoiceInputError);
    expect((error as VoiceInputError).code).toBe("permission");
    const ws = FakeWebSocket.instances.at(-1)!;
    expect(ws.closed).toBe(true);
  });

  it("WebSocket 连接失败时抛 network", async () => {
    const error = await startVoiceInput(
      { wsUrl: "ws://test/voice", buyerId: "smartlect", onEvent: () => undefined },
      deps({ WebSocketCtor: FailingWebSocket as unknown as typeof WebSocket }),
    ).catch((err: unknown) => err);
    expect((error as VoiceInputError).code).toBe("network");
  });

  it("浏览器不支持麦克风时直接抛 unsupported", async () => {
    const error = await startVoiceInput(
      { wsUrl: "ws://test/voice", buyerId: "smartlect", onEvent: () => undefined },
      deps({ mediaDevices: undefined }),
    ).catch((err: unknown) => err);
    expect((error as VoiceInputError).code).toBe("unsupported");
  });

  it("abort 立即释放，不等待终稿", async () => {
    const session = await startVoiceInput(
      { wsUrl: "ws://test/voice", buyerId: "smartlect", onEvent: () => undefined },
      deps(),
    );
    session.abort();
    const ws = FakeWebSocket.instances.at(-1)!;
    expect(ws.closed).toBe(true);
    expect(ws.sent.filter((frame) => typeof frame === "string" && frame.includes("finish"))).toHaveLength(0);
  });

  it("getUserMedia 不存在时开始前即失败", async () => {
    const spy = vi.fn();
    await startVoiceInput(
      { wsUrl: "ws://test/voice", buyerId: "smartlect", onEvent: spy },
      deps({ mediaDevices: { } as MediaDevices }),
    ).catch(() => undefined);
    expect(spy).not.toHaveBeenCalled();
  });
});
