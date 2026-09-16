import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { defineComponent, h } from 'vue';
import ElementPlus from 'element-plus';
import { createPinia } from 'pinia';
import ProductList from '../src/views/product/ProductList.vue';
import { installJsdomPolyfills, sharedComponents } from './helpers';

// 线上真实故障：商品没有封面时 `row.cover.split(',')` 抛 TypeError，EP 表格丢掉整个
// "商品信息" 单元格，行内其余内容整体左移一列（表头 7 列、行内 6 格）。
// Element Plus 的表格在 jsdom 里不渲染数据行，所以这里用只透传插槽的 Table 替身，
// 让"商品信息"单元格的渲染路径真的跑一遍：没有封面也必须渲染出名称且不报错。
const row = {
  productId: 'p1', productName: '无封面商品', cover: null, minPrice: 10, maxPrice: 20,
  totalStock: 5, skuCount: 2, status: 1, commendType: 0, categoryName: '数码'
};

const TableStub = defineComponent({
  props: ['columns', 'dataSource', 'fetch'],
  setup(props, { slots }) {
    // 真 Table 在 setup 里就发起首次加载，替身保持同样的契约
    props.fetch?.();
    return () => h('div', { class: 'table-stub' },
      (props.dataSource?.list || []).map((row) => h('div', { class: 'row-stub' },
        props.columns.map((column) => h('span', { class: 'cell-stub' },
          slots[column.scopedSlots]?.({ row }))))));
  }
});

let wrapper; let errors;
beforeEach(() => {
  installJsdomPolyfills();
  errors = [];
  vi.spyOn(console, 'error').mockImplementation((...args) => { errors.push(args.map(String).join(' ')); });
});
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); });

describe('商品列表在缺封面时也完整渲染', () => {
  it('商品信息单元格渲染名称与编号，不因封面为空报错', async () => {
    wrapper = mount(ProductList, {
      global: {
        components: sharedComponents,
        stubs: { Table: TableStub },
        plugins: [ElementPlus, createPinia(), {
          // main.js 用 globalProperties 注册这些能力，页面通过 getCurrentInstance().proxy 取用；
          // 测试里必须用同样的注册方式（global.mocks 到不了 proxy）。
          install(app) {
            Object.assign(app.config.globalProperties, {
              Api: { loadProduct: '/api/product/loadProduct', sourcePath: '' },
              Utils: { jump: vi.fn(), getLocalResource: () => '' },
              Request: vi.fn(async () => ({ data: { list: [{ ...row }], totalCount: 1, pageNo: 1, pageSize: 15 } })),
              Message: { warning: vi.fn(), success: vi.fn(), error: vi.fn() },
              ConfirmSensitive: vi.fn(),
              imageThumbnailSuffix: '_thumbnail'
            });
          }
        }]
      }
    });
    await flushPromises();

    const cells = wrapper.find('.row-stub').findAll('.cell-stub');
    expect(cells).toHaveLength(7);
    expect(cells[0].text()).toContain('无封面商品');
    expect(cells[0].text()).toContain('ID:p1');
    expect(errors.join('\n')).not.toContain('split');
  });
});
