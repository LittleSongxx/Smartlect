import { describe, expect, it } from 'vitest';
import { annotateAnswerWithCitations, citationTitle, displayCitations } from '../src/utils/citations';

describe('客服引用展示', () => {
  it('只按 chunk_id 去重，标题井号去掉', () => {
    const list = displayCitations([
      { title: '# 退货条件与期限', chunk_id: 'a', text: '原文甲' },
      { title: '退货条件与期限', chunk_id: 'a', text: '重复同一片段' },
      { title: '换货与更换规格', chunk_id: 'c', text: '原文丙' },
      { title: '没有编号的资料' },
    ]);
    expect(list).toEqual([
      { index: 1, title: '退货条件与期限', chunk_id: 'a' },
      { index: 2, title: '换货与更换规格', chunk_id: 'c' },
    ]);
    expect(citationTitle({ title: '## 售后政策' })).toBe('售后政策');
  });

  it('不按文档名正则贴标，只认正文里的 chunk_id 或已有 [n]', () => {
    const sources = displayCitations([
      { title: '退货条件与期限', chunk_id: 'chunk-a' },
      { title: '换货与更换规格', chunk_id: 'chunk-b' },
    ]);
    expect(annotateAnswerWithCitations('退货条件与期限如下，换货请另询。', sources))
      .toBe('退货条件与期限如下，换货请另询。[1][2]');
    expect(annotateAnswerWithCitations('依据 chunk-a 办理。', sources))
      .toBe('依据 chunk-a [1] 办理。[2]');
    expect(annotateAnswerWithCitations('已按说明 [1] 办理。', sources)).toBe('已按说明 [1] 办理。[2]');
  });
});
