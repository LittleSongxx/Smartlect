import { afterEach, describe, expect, it } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import ProductImage from '../src/components/common/ProductImage.vue';

// el-image 用桩件替身：只需要它把 src 透出来、并在图片失败时转发 error 事件。
const ElImageStub = {
  name: 'ElImage',
  props: ['src', 'fit', 'lazy'],
  emits: ['error'],
  template: '<img class="stub-image" :src="src" @error="$emit(\'error\')" />',
};

const mountImage = (props: Record<string, unknown>) =>
  mount(ProductImage, {
    props: { lazy: false, ...props },
    global: { stubs: { 'el-image': ElImageStub, 'el-icon': true } },
  });

const srcOf = (wrapper: ReturnType<typeof mount>) => String(wrapper.find('img.stub-image').attributes('src'));

let wrapper: ReturnType<typeof mount> | undefined;
afterEach(() => {
  wrapper?.unmount();
  wrapper = undefined;
});

describe('商品图 URL 与失败回退', () => {
  it('主图请求去掉 _thumbnail 的原图，失败后回退到实际存储的缩略图', async () => {
    wrapper = mountImage({ source: '202601/a_thumbnail.png', useThumbnail: false });
    await flushPromises();
    // 主图：去掉缩略图后缀，向服务端要原图
    expect(srcOf(wrapper)).toContain('/api/file/getResource?sourceName=');
    expect(decodeURIComponent(srcOf(wrapper))).toContain('202601/a.png');
    expect(decodeURIComponent(srcOf(wrapper))).not.toContain('_thumbnail');

    // 原图不存在（历史种子数据只存了缩略图）→ 换 URL 重取，命中已缓存的好图
    await wrapper.find('img.stub-image').trigger('error');
    await flushPromises();
    expect(decodeURIComponent(srcOf(wrapper))).toContain('202601/a_thumbnail.png');
  });

  it('缩略图失败时不会反向切换（避免两列图互相覆盖）', async () => {
    wrapper = mountImage({ source: '202601/a_thumbnail.png', useThumbnail: true });
    await flushPromises();
    const before = srcOf(wrapper);
    await wrapper.find('img.stub-image').trigger('error');
    await flushPromises();
    expect(srcOf(wrapper)).toBe(before);
  });

  it('换图后重置回退状态：下一张仍先试原图', async () => {
    wrapper = mountImage({ source: '202601/a_thumbnail.png', useThumbnail: false });
    await wrapper.find('img.stub-image').trigger('error');
    await flushPromises();
    expect(decodeURIComponent(srcOf(wrapper))).toContain('_thumbnail');

    await wrapper.setProps({ source: '202601/b_thumbnail.png' });
    await flushPromises();
    expect(decodeURIComponent(srcOf(wrapper))).toContain('202601/b.png');
    expect(decodeURIComponent(srcOf(wrapper))).not.toContain('_thumbnail');
  });

  it('缺图时不产生 src，交给占位槽处理', async () => {
    wrapper = mountImage({ source: '', useThumbnail: false });
    await flushPromises();
    expect(srcOf(wrapper)).toBe('');
  });
});
