export type CitationSource = {
  chunk_id?: string;
  doc_id?: string;
  title?: string;
  heading?: string;
  text?: string;
  content?: string;
};

export type DisplayCitation = {
  index: number;
  title: string;
};

export function citationTitle(source: CitationSource | null | undefined): string {
  const raw = String(source?.title || source?.heading || '').trim();
  return raw.replace(/^#+\s*/, '').replace(/\s+/g, ' ').trim();
}

export function displayCitations(citations: CitationSource[] | null | undefined): DisplayCitation[] {
  const list: DisplayCitation[] = [];
  const seen = new Set<string>();
  for (const source of citations || []) {
    const title = citationTitle(source);
    if (!title) continue;
    const key = title.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    list.push({ index: list.length + 1, title });
  }
  return list;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function annotateAnswerWithCitations(answer: string, sources: DisplayCitation[]): string {
  const text = String(answer || '');
  if (!text || !sources.length) return text;
  let next = text;
  const placed = new Set<number>();
  const byLength = [...sources].sort((left, right) => right.title.length - left.title.length);
  for (const source of byLength) {
    if (new RegExp(`\\[\\s*${source.index}\\s*\\]`).test(next)) {
      placed.add(source.index);
      continue;
    }
    const found = new RegExp(escapeRegExp(source.title), 'i').exec(next);
    if (!found) continue;
    const insertAt = found.index + found[0].length;
    next = `${next.slice(0, insertAt)} [${source.index}]${next.slice(insertAt)}`;
    placed.add(source.index);
  }
  const missing = sources.filter((item) => !placed.has(item.index)).map((item) => `[${item.index}]`);
  if (!missing.length) return next;
  return `${next.replace(/\s*$/, '')}${missing.join('')}`;
}
