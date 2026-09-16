import PageHeader from '../src/components/PageHeader.vue'
import StatusTag from '../src/components/StatusTag.vue'
import DetailText from '../src/components/DetailText.vue'
import JsonCollapse from '../src/components/JsonCollapse.vue'
import Dialog from '../src/components/Dialog.vue'
import Drawer from '../src/components/Drawer.vue'
import Table from '../src/components/Table.vue'
import OpBtn from '../src/components/OpBtn.vue'
import Price from '../src/components/Price.vue'
import Avatar from '../src/components/Avatar.vue'
import ImageSelect from '../src/components/ImageSelect.vue'
import Cover from '../src/components/Cover.vue'
import CouponOrderCover from '../src/components/CouponOrderCover.vue'

// 跨测试文件共享的 fetch-stub / 查找工具；语义与各页既有本地实现保持一致。

// main.js 里全局注册的骨架组件。测试直接 mount 页面时要显式带上，否则组件解析失败、
// 页头与状态标签会静默缺失（断言也只是没覆盖，不会报错）。
export const sharedComponents = {
  PageHeader, StatusTag, DetailText, JsonCollapse,
  Dialog, Drawer, Table, OpBtn, Price, Avatar, ImageSelect, Cover, CouponOrderCover,
}

// Element Plus 表格在 jsdom 中需要 ResizeObserver 才会渲染数据行。
export function installJsdomPolyfills() {
  if (!globalThis.ResizeObserver) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  }
  if (!globalThis.matchMedia) {
    globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} })
  }
}

export const response = (value, status = 200) => ({ ok: status < 400, status, json: async () => value })

export const button = (wrapper, text) => wrapper.findAll('button').find((item) => item.text() === text)

export const field = (wrapper, label) => wrapper.findAll('label').find((item) => item.text().startsWith(label)).find('input, select, textarea')
