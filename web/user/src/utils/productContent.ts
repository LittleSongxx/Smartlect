export const PRODUCT_CONTENT_SECTIONS = [
  { key: 'selling_points', label: '卖点' },
  { key: 'usage', label: '用法' },
  { key: 'ingredients', label: '成分' },
  { key: 'packaging', label: '包装' },
  { key: 'contraindications', label: '禁忌' },
  { key: 'after_sale_note', label: '售后备注' }
] as const;

export type ProductContentSection = { key: string; label: string; text: string };

export function parseProductContent(info: Record<string, any> | null | undefined) {
  const raw = readContentMap(info);
  const sections = PRODUCT_CONTENT_SECTIONS
    .map((item) => ({ key: item.key, label: item.label, text: String(raw[item.key] || '').trim() }))
    .filter((item) => item.text);
  const extra = String(raw.extra_markdown || info?.productDesc || '').trim();
  const brand = String(info?.brand || '').trim();
  return { sections, extra, brand };
}

function readContentMap(info: Record<string, any> | null | undefined): Record<string, unknown> {
  if (info?.content && typeof info.content === 'object') return info.content;
  const json = info?.contentJson;
  if (typeof json === 'string' && json.trim()) {
    try {
      const parsed = JSON.parse(json);
      if (parsed && typeof parsed === 'object') return parsed;
    } catch {
      /* keep productDesc fallback */
    }
  }
  return {};
}
