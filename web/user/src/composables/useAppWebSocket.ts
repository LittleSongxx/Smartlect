export function useAppWebSocket() {
  return { connected: false };
}

export function ensureAppWebSocket() {
  return Promise.resolve(false);
}
