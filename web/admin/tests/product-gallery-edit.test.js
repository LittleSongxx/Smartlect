import { describe, expect, it } from 'vitest'
import {
  fillCoverDefault,
  joinGallerySlots,
  normalizeValueGalleries,
  toGallerySlots
} from '../src/utils/productEditGallery'

// 图集编辑的三段契约：回显填充与提交 join 互逆；色卡兜底只在
// coverType=1 且色卡为空且图集非空时触发，且不改写入参。

describe('商品编辑图集纯函数', () => {
  it('回显填充固定槽位，不足补空、超长不截断', () => {
    expect(toGallerySlots('a.jpg,b.jpg', 5)).toEqual(['a.jpg', 'b.jpg', '', '', ''])
    expect(toGallerySlots('', 5)).toEqual(['', '', '', '', ''])
    expect(toGallerySlots(null, 3)).toEqual(['', '', ''])
    expect(toGallerySlots('1.jpg,2.jpg,3.jpg,4.jpg,5.jpg,6.jpg', 5)).toHaveLength(6)
  })

  it('join 与填充互逆：回显→清空槽位→join 应还原', () => {
    const gallery = '2026-06/a.jpg,2026-06/b.jpg'
    const slots = toGallerySlots(gallery, 5)
    expect(joinGallerySlots(slots)).toBe(gallery)
    expect(joinGallerySlots(['', '', '', '', ''])).toBe('')
    expect(joinGallerySlots(undefined)).toBe('')
  })

  it('色卡兜底只在 coverType=1、色卡空、图集非空时触发', () => {
    const trigger = fillCoverDefault(
      { propertyCover: '', propertyGalleryArray: ['a.jpg', ''] }, 1)
    expect(trigger.propertyCover).toBe('a.jpg')

    expect(fillCoverDefault({ propertyCover: 'c.jpg', propertyGalleryArray: ['a.jpg'] }, 1)
      .propertyCover).toBe('c.jpg')
    expect(fillCoverDefault({ propertyCover: '', propertyGalleryArray: ['', ''] }, 1)
      .propertyCover).toBe('')
    expect(fillCoverDefault({ propertyCover: '', propertyGalleryArray: ['a.jpg'] }, 0)
      .propertyCover).toBe('')
  })

  it('兜底不改写入参', () => {
    const value = { propertyCover: '', propertyGalleryArray: ['a.jpg'] }
    fillCoverDefault(value, 1)
    expect(value.propertyCover).toBe('')
  })

  it('normalizeValueGalleries 逐值填充且容忍 propertyValues 缺失', () => {
    const list = normalizeValueGalleries([
      { propertyId: '1', propertyValues: [{ propertyGallery: 'a.jpg', propertyCover: 'c.jpg' }] },
      { propertyId: '2' },
    ], 2)
    expect(list[0].propertyValues[0]).toEqual({
      propertyGallery: 'a.jpg', propertyCover: 'c.jpg', propertyGalleryArray: ['a.jpg', '']
    })
    expect(list[1].propertyValues).toEqual([])
    expect(normalizeValueGalleries(null, 5)).toEqual([])
  })
})
