// crypto.randomUUID 仅在安全上下文（HTTPS/localhost）存在；
// 通过 http://IP 访问时缺失，入口最先 import 本模块补齐，避免整个应用白屏。
if (typeof crypto.randomUUID !== 'function') {
  const bytes = new Uint8Array(16);
  const fallback = (): `${string}-${string}-${string}-${string}-${string}` => {
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}` as `${string}-${string}-${string}-${string}-${string}`;
  };
  crypto.randomUUID = fallback;
}
