import { onBeforeUnmount, readonly, ref } from 'vue'

/**
 * 容错轮询：用于后台长任务（索引构建、报告生成等）的进度跟踪。
 * 语义取自 MerchantView 轮询与 Smartore 进度页之并集：
 * - 单次网络失败不中止（连续 maxConsecutiveFailures 次才停止并保留 error）
 * - 到 deadlineMs 或 isDone(state) 自动停止
 * - 组件卸载自动清理定时器
 *
 * @param {() => Promise<object>} fetchState 拉取一次任务状态；抛错视为单次失败
 * @param {{intervalMs?: number, deadlineMs?: number, maxConsecutiveFailures?: number, isDone?: (state: object) => boolean}} options
 */
export function useTaskProgress(fetchState, { intervalMs = 1000, deadlineMs = 15 * 60 * 1000, maxConsecutiveFailures = 5, isDone = () => false } = {}) {
  const active = ref(false)
  const state = ref(null)
  const error = ref('')
  let timer = null
  let failures = 0
  let deadlineAt = 0

  const stop = () => {
    active.value = false
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }

  const tick = async () => {
    if (!active.value) return
    try {
      state.value = await fetchState()
      error.value = ''
      failures = 0
      if (isDone(state.value)) {
        stop()
        return
      }
    } catch (cause) {
      failures += 1
      error.value = cause?.message || String(cause)
      if (failures >= maxConsecutiveFailures) {
        stop()
        return
      }
    }
    if (!active.value) return
    if (deadlineMs && Date.now() >= deadlineAt) {
      stop()
      return
    }
    timer = setTimeout(tick, intervalMs)
  }

  const begin = () => {
    stop()
    active.value = true
    failures = 0
    error.value = ''
    deadlineAt = Date.now() + deadlineMs
    tick()
  }

  onBeforeUnmount(stop)

  return { active, state: readonly(state), error: readonly(error), begin, stop }
}
