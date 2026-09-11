export function resolveSafeRedirect(raw: unknown, fallback = '/'): string {
  const path = String(raw ?? '').trim();
  if (!path.startsWith('/') || path.startsWith('//')) return fallback;
  if (path.startsWith('/login') || path.startsWith('/register')) return fallback;
  return path;
}

export function safeNext(value: unknown, fallback = '/assistant'): string {
  return resolveSafeRedirect(value, fallback);
}

export function loginTarget(path: string, fullPath: string) {
  return path === '/login' ? '/login' : `/login?next=${encodeURIComponent(fullPath)}`;
}
