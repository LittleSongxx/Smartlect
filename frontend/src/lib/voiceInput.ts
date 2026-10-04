// 语音输入会话：getUserMedia → AudioWorklet（16kHz/Int16/100ms 帧）→ WS 流式识别。
// 只负责音频采集与转发；识别文本经回调交给调用方回填输入框，
// 不触碰 AG-UI 对话链路。
export type VoiceInputEvent =
  | { type: "partial"; text: string }
  | { type: "final"; text: string }
  | { type: "stopped"; reason: string }
  | { type: "error"; code: string; message: string };

export interface VoiceInputSession {
  /** 正常收口：垫尾静音 → 发 finish → 等 stopped → 清理。 */
  stop: () => Promise<void>;
  /** 异常清理：不等终稿，立即释放麦克风与连接。 */
  abort: () => void;
}

export class VoiceInputError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

// 停止后垫 800ms 静音帮助服务端 VAD 收口，防止最后半句丢失
const SILENCE_TAIL_MS = 800;
const SAMPLE_RATE = 16000;
const STOP_TIMEOUT_MS = 5000;

type WorkletNodeLike = {
  port: Pick<MessagePort, "onmessage" | "close">;
  disconnect(): void;
};

interface VoiceInputDeps {
  WebSocketCtor?: typeof WebSocket;
  mediaDevices?: MediaDevices;
  AudioContextCtor?: typeof AudioContext;
  createWorkletNode?: (
    context: AudioContext, source: AudioNode, name: string, options: AudioWorkletNodeOptions,
  ) => WorkletNodeLike;
  workletUrl?: string;
}

export async function startVoiceInput(
  options: {
    wsUrl: string;
    token?: string;
    buyerId: string;
    onEvent: (event: VoiceInputEvent) => void;
    onLevel?: (rms: number) => void;
  },
  deps: VoiceInputDeps = {},
): Promise<VoiceInputSession> {
  const WebSocketCtor = deps.WebSocketCtor ?? window.WebSocket;
  const mediaDevices = deps.mediaDevices ?? navigator.mediaDevices;
  const AudioContextCtor = deps.AudioContextCtor ?? window.AudioContext;
  const createWorkletNode = deps.createWorkletNode ?? ((context, source, name, nodeOptions) => {
    const node = new AudioWorkletNode(context, name, nodeOptions);
    source.connect(node);
    return node;
  });
  // 注入了 worklet 工厂（测试）或浏览器原生 AudioWorkletNode 可用时才认为支持
  const workletSupported = !!deps.createWorkletNode || typeof window.AudioWorkletNode !== "undefined";
  if (!mediaDevices?.getUserMedia || typeof AudioContextCtor === "undefined" || !workletSupported) {
    throw new VoiceInputError("unsupported", "当前浏览器不支持麦克风采集");
  }

  let ws: WebSocket | null = null;
  let audioCtx: AudioContext | null = null;
  let micStream: MediaStream | null = null;
  let workletNode: WorkletNodeLike | null = null;
  let released = false;

  const cleanup = () => {
    if (released) return;
    released = true;
    if (workletNode) { try { workletNode.port.close?.(); workletNode.disconnect(); } catch { /* 已断开 */ } }
    workletNode = null;
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    if (audioCtx) void audioCtx.close().catch(() => { /* 已关闭 */ });
    audioCtx = null;
    if (ws && (ws.readyState === WebSocketCtor.OPEN || ws.readyState === WebSocketCtor.CONNECTING)) {
      try { ws.close(); } catch { /* 已关闭 */ }
    }
    ws = null;
  };

  try {
    ws = new WebSocketCtor(
      options.wsUrl,
      ["smartlect-voice", options.token ? `smartlect-auth.${options.token}` : ""].filter(Boolean),
    );
    ws.binaryType = "arraybuffer";
    const socket = ws;
    await new Promise<void>((resolve, reject) => {
      socket.onopen = () => resolve();
      socket.onerror = () => reject(new VoiceInputError("network", "无法连接语音识别服务"));
      setTimeout(() => {
        if (socket.readyState !== WebSocketCtor.OPEN) {
          reject(new VoiceInputError("network", "语音识别服务连接超时"));
        }
      }, STOP_TIMEOUT_MS);
    });
    // 首帧身份与主链路一致：demo 模式声明 buyer_id，hmac 模式校验子协议令牌
    socket.send(JSON.stringify({ buyer_id: options.buyerId }));
    socket.onmessage = (event) => {
      if (socket !== ws) return;
      let payload: { type?: string; text?: string; reason?: string; code?: string; message?: string };
      try { payload = JSON.parse(String(event.data)); } catch { return; }
      if (payload.type === "partial" || payload.type === "final") {
        options.onEvent({ type: payload.type, text: payload.text || "" });
      } else if (payload.type === "stopped") {
        options.onEvent({ type: "stopped", reason: payload.reason || "finished" });
        cleanup();
      } else if (payload.type === "error") {
        options.onEvent({ type: "error", code: payload.code || "upstream", message: payload.message || "识别服务错误" });
        cleanup();
      }
    };
    socket.onclose = () => {
      if (socket !== ws || released) return;
      options.onEvent({ type: "stopped", reason: "closed" });
      cleanup();
    };

    audioCtx = new AudioContextCtor();
    const workletUrl = deps.workletUrl ?? new URL("./pcmWorklet.js", import.meta.url).href;
    await audioCtx.audioWorklet.addModule(workletUrl);
    micStream = await mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: false, autoGainControl: true },
    });
    workletNode = createWorkletNode(
      audioCtx,
      audioCtx.createMediaStreamSource(micStream),
      "pcm-collector",
      { processorOptions: { inputRate: audioCtx.sampleRate } },
    );
    workletNode.port.onmessage = (event: MessageEvent) => {
      const message = event.data as { type: string; data?: ArrayBuffer; rms?: number };
      if (message.type === "pcm" && message.data && ws === socket && socket.readyState === WebSocketCtor.OPEN) {
        socket.send(message.data);
      } else if (message.type === "level" && typeof message.rms === "number") {
        options.onLevel?.(message.rms);
      }
    };
  } catch (error) {
    cleanup();
    if (error instanceof VoiceInputError) throw error;
    if (error instanceof DOMException && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
      throw new VoiceInputError("permission", "麦克风权限被拒绝，请在浏览器地址栏允许后重试");
    }
    if (error instanceof DOMException && error.name === "NotFoundError") {
      throw new VoiceInputError("no-device", "未检测到可用麦克风");
    }
    throw new VoiceInputError("microphone", `录音启动失败：${error instanceof Error ? error.message : String(error)}`);
  }

  return {
    stop: async () => {
      if (released || !ws) return;
      const socket = ws;
      // 先停采集（麦克风立即关），再补静音尾帧 + finish，让服务端把最后半句吐完
      if (workletNode) { try { workletNode.disconnect(); } catch { /* 已断开 */ } }
      workletNode = null;
      if (micStream) micStream.getTracks().forEach((track) => track.stop());
      micStream = null;
      if (audioCtx) void audioCtx.close().catch(() => { /* 已关闭 */ });
      audioCtx = null;
      if (socket.readyState === WebSocketCtor.OPEN) {
        socket.send(new Int16Array((SAMPLE_RATE * SILENCE_TAIL_MS) / 1000).buffer);
        socket.send(JSON.stringify({ type: "finish" }));
        await new Promise<void>((resolve) => {
          const timer = setTimeout(() => { cleanup(); resolve(); }, STOP_TIMEOUT_MS);
          const original = socket.onclose;
          socket.onclose = () => {
            clearTimeout(timer);
            original?.call(socket, new CloseEvent("close"));
            resolve();
          };
          // stopped/error 事件到达时 onmessage 已清理，靠 close 兜底；
          // 若服务端 5 秒内既无 stopped 也未关闭，超时强收。
        });
      }
      cleanup();
    },
    abort: () => cleanup(),
  };
}
