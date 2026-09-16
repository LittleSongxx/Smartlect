import { describe, expect, it } from 'vitest';
import { joinRegionText, matchRegionFromFullAddress, stripRegionText } from '../src/utils/regionGeocode';

describe('收货地址的地区前缀', () => {
  it('普通省市区的编码拼成可读前缀', () => {
    expect(joinRegionText(['44', '4403', '440305'])).toBe('广东省深圳市南山区');
    expect(joinRegionText(['42', '4201', '420106'])).toBe('湖北省武汉市武昌区');
  });

  it('直辖市不把占位层"市辖区"写进地址', () => {
    expect(joinRegionText(['11', '1101', '110101'])).toBe('北京市东城区');
    expect(joinRegionText(['31', '3101', '310101'])).toBe('上海市黄浦区');
  });

  it('只选到省或市时也能拼接', () => {
    expect(joinRegionText(['11'])).toBe('北京市');
    expect(joinRegionText(['44', '4403'])).toBe('广东省深圳市');
  });

  it('保存后再解析，详细地址原样取回', () => {
    const codes = ['11', '1101', '110101'];
    const stored = joinRegionText(codes) + '演示路1号';
    expect(stored).toBe('北京市东城区演示路1号');
    expect(matchRegionFromFullAddress(stored)).toEqual(codes);
    expect(stripRegionText(stored, codes)).toBe('演示路1号');
  });

  it('旧数据里的"市辖区"与重复层也能剥掉', () => {
    expect(stripRegionText('北京市市辖区东城区演示路1号', ['11', '1101', '110101'])).toBe('演示路1号');
    expect(stripRegionText('北京市北京市东城区演示路1号', ['11', '1101', '110101'])).toBe('演示路1号');
    // 早先只存了区县的数据也要能编辑
    expect(stripRegionText('东城区演示路1号', ['11', '1101', '110101'])).toBe('演示路1号');
  });

  it('非直辖市的旧数据不受影响', () => {
    const codes = ['44', '4403', '440305'];
    expect(stripRegionText('广东省深圳市南山区科技园1号', codes)).toBe('科技园1号');
    expect(stripRegionText('深圳市南山区科技园1号', codes)).toBe('科技园1号');
  });
});
