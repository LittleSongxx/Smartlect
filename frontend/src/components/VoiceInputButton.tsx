import Icon from "./Icon";

interface Props {
  recording: boolean;
  disabled: boolean;
  onToggle: () => void;
}

/** 麦克风按钮：点击开始/结束录音；识别失败由父级 toast 提示，这里只承载录音态。 */
export default function VoiceInputButton({ recording, disabled, onToggle }: Props) {
  return (
    <button
      type="button"
      className={`voice-button ${recording ? "recording" : ""}`}
      disabled={disabled}
      aria-label={recording ? "停止语音输入" : "开始语音输入"}
      aria-pressed={recording}
      title={recording ? "停止语音输入" : "语音输入"}
      onClick={onToggle}
    >
      <Icon name="mic" />
      {recording && <span className="voice-recording-dot" aria-hidden="true" />}
    </button>
  );
}
