import { flushPromises, mount } from '@vue/test-utils'

// 跨测试文件共享的 fetch-stub / 查找工具；语义与各页既有本地实现保持一致。

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

export async function render(component, options = {}) {
  const wrapper = mount(component, options)
  await flushPromises()
  return wrapper
}

// 各测试文件在 afterEach 统一 unmount，防止跨用例泄漏。
export function createWrapperRegistry() {
  const wrappers = []
  return {
    track: (wrapper) => {
      wrappers.push(wrapper)
      return wrapper
    },
    unmountAll: () => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()),
  }
}
