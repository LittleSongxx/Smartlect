import { IMAGE_BASE } from '@/utils/image';

export function isAllowedProductImageSrc(url?: string | null): boolean {
  const raw = String(url ?? '').trim();
  if (!raw || raw.includes('..') || raw.includes('\\')) return false;
  if (/^(https?:|data:|javascript:)/i.test(raw)) return false;
  return raw.startsWith('/api/file/getResource?sourceName=');
}

export function normalizeProductDesc(desc?: string | null): string {
  if (!desc) return '';

  let text = String(desc).trim();

  text = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_match, alt, url) => {
    const raw = String(url).trim();
    if (!raw) return '';

    if (raw.startsWith('http://') || raw.startsWith('https://')) {
      return `![${alt}](${raw})`;
    }

    if (raw.includes('/api/file/getResource')) {
      return `![${alt}](${raw.startsWith('/') ? raw : `/${raw}`})`;
    }

    if (raw.startsWith('sourceName=')) {
      return `![${alt}](${IMAGE_BASE}${raw.replace(/^sourceName=/, '')})`;
    }

    return `![${alt}](${IMAGE_BASE}${raw})`;
  });

  text = text.replace(/^(202601\/[^\s\n]+\.(?:png|jpg|jpeg|gif|webp))$/gim, (path) => {
    return `![](${IMAGE_BASE}${path})`;
  });

  return text;
}
