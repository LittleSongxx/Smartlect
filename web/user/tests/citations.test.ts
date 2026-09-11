import { describe, expect, it } from 'vitest';
import { annotateAnswerWithCitations, citationTitle, displayCitations } from '../src/utils/citations';

describe('客服引用展示', () => {
  it('按文档名去重并去掉标题井号', () => {
    const list = displayCitations([
      { title: '# 退货条件与期限', chunk_id: 'a', text: '原文甲' },
      { title: '退货条件与期限', chunk_id: 'b', text: '原文乙' },
      { title: '换货与更换规格', chunk_id: 'c', text: '原文丙' },
    ]);
    expect(list).toEqual([
      { index: 1, title: '退货条件与期限' },
      { index: 2, title: '换货与更换规格' },
    ]);
    expect(citationTitle({ title: '## 售后政策' })).toBe('售后政策');
  });

  it('在正文首次出现的文档名后加标号，未出现的标号跟在段末', () => {
    const sources = displayCitations([
      { title: '退货条件与期限' },
      { title: '换货与更换规格' },
    ]);
    expect(annotateAnswerWithCitations('退货条件与期限如下，换货请另询。', sources))
      .toBe('退货条件与期限 [1]如下，换货请另询。[2]');
    expect(annotateAnswerWithCitations('可以办理退换货。', sources)).toBe('可以办理退换货。[1][2]');
    expect(annotateAnswerWithCitations('已按退货条件与期限 [1]说明。', sources)).toBe('已按退货条件与期限 [1]说明。[2]');
  });
});
